"""Allowlisted AvalAI/OpenAI Responses transport and per-task token budget."""
import json
import os
import re
import urllib.request
from backend.credentials import load_key

AVALAI_URL = 'https://api.avalai.ir/v1'
OPENAI_URL = 'https://api.openai.com/v1'


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    LIMIT = 25000

    def __init__(self):
        self.used = 0
        self.calls = 0

    def reserve(self, input_tokens, output_tokens):
        if type(input_tokens) is not int or input_tokens < 0:
            raise RuntimeError('Reliable input token count unavailable; no model request sent.')
        amount = input_tokens + output_tokens
        if self.used + amount > self.LIMIT:
            raise BudgetExceeded('Task token budget cannot accommodate another model call.')
        self.used += amount
        self.calls += 1
        return amount

    def settle(self, reserved, usage):
        if not isinstance(usage, dict):
            return  # Retain the entire reserved upper bound when usage is missing.
        incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
        if type(incoming) is not int or type(outgoing) is not int or incoming < 0 or outgoing < 0:
            return
        actual = incoming + outgoing
        if actual > reserved:
            raise RuntimeError('Provider usage exceeded its preflight reservation; automatic work stopped.')
        self.used -= reserved - actual


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError('API redirects are blocked.')


class ResponsesProvider:
    def __init__(self, model=None, key=None, base_url=None):
        self.model = model if model is not None else os.getenv('CODIX_MODEL', '')
        self.key = key if key is not None else load_key()
        self.base_url = (base_url if base_url is not None else os.getenv('OPENAI_BASE_URL', AVALAI_URL)).rstrip('/')
        if self.base_url not in (AVALAI_URL, OPENAI_URL):
            raise RuntimeError('API endpoint must be the approved HTTPS AvalAI or OpenAI base URL.')
        if not self.key or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,100}', self.model):
            raise RuntimeError('Save the private AvalAI Windows key (or configure AVALAI_API_KEY/OPENAI_API_KEY) and set CODIX_MODEL before starting a task. Never paste the key into chat.')
        self.opener = urllib.request.build_opener(NoRedirect())

    def _post(self, endpoint, payload):
        request = urllib.request.Request(self.base_url + '/' + endpoint,
                                         data=json.dumps(payload).encode(), method='POST',
                                         headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=90) as response:
                raw = response.read(512001)
                if len(raw) > 512000:
                    raise ValueError('Oversized response')
                return json.loads(raw)
        except Exception:
            # Do not forward urllib errors, response bodies, headers or secrets into logs/UI.
            raise RuntimeError('Provider request failed; no automatic retry was made. Check configuration, model access and network.') from None

    def call(self, instructions, context, tools, budget, forced=None):
        choice = {'type': 'function', 'name': forced} if forced else 'required'
        payload = {'model': self.model, 'instructions': instructions,
                   'input': [{'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
                   'tools': tools, 'tool_choice': choice}
        # Exact same input/instructions/schema/choice used for count and generation.
        if self.base_url == AVALAI_URL:
            # AvalAI currently marks exact counting as not implemented. Only text/function schemas
            # for OpenAI model routes are supported by this conservative byte upper estimate.
            if not re.match(r'^(gpt-|o[134](?:-|$))', self.model):
                raise RuntimeError('AvalAI conservative token budgeting currently requires an OpenAI gpt-/o1/o3/o4 model route.')
            input_tokens = len(json.dumps(payload).encode('utf-8')) + 4096
        else:
            count = self._post('responses/input_tokens', payload)
            input_tokens = count.get('input_tokens')
        reserved = budget.reserve(input_tokens, 2048)
        # Reserve before send; an ambiguous network failure retains the full reservation.
        response = self._post('responses', {**payload, 'max_output_tokens': 2048, 'parallel_tool_calls': False,
                                            'store': False, 'truncation': 'disabled'})
        budget.settle(reserved, response.get('usage'))
        if response.get('status') != 'completed':
            raise RuntimeError('Model response incomplete; no tool action was executed.')
        calls = [item for item in response.get('output', []) if item.get('type') == 'function_call']
        if len(calls) != 1 or not isinstance(calls[0].get('arguments'), str) or len(calls[0]['arguments']) > 65536:
            raise RuntimeError('Expected exactly one bounded model tool call.')
        try:
            return calls[0]['name'], json.loads(calls[0]['arguments'])
        except (KeyError, ValueError):
            raise RuntimeError('Invalid model tool arguments; task stopped.') from None
