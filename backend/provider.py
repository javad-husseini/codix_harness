"""Allowlisted AvalAI/OpenAI Responses transport and per-task token budget."""
import json
import os
import re
import urllib.request
import urllib.error
import ssl
import certifi
from backend.credentials import load_key

AVALAI_URL = 'https://api.avalai.ir/v1'
OPENAI_URL = 'https://api.openai.com/v1'


class BudgetExceeded(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """Only fixed, credential-free diagnostics may cross the provider boundary."""
    MESSAGES = {
        'authentication': 'Provider rejected the API key (HTTP 401). Check or replace the AvalAI key.',
        'permission': 'Provider denied access (HTTP 403). Check account/model permissions.',
        'not_found': 'Provider model or Responses endpoint was not found (HTTP 404). Check model availability.',
        'request': 'Provider rejected the request (HTTP 400/422). Check model/Responses/tool-schema compatibility.',
        'quota': 'Provider reports insufficient credit/quota. Check AvalAI account balance and limits.',
        'rate_limit': 'Provider rate limit reached (HTTP 429). Wait before manually starting another task.',
        'server': 'Provider service failed (HTTP 5xx). No automatic retry was made.',
        'network': 'Cannot connect to the provider. Check network, proxy and DNS; no automatic retry was made.',
        'tls': 'Provider TLS certificate verification failed. Check Windows certificates/proxy; TLS verification remains enabled.',
        'tls_protocol': 'Provider TLS negotiation failed. Check network/proxy and TLS compatibility; certificate verification remains enabled.',
        'redirect': 'Provider attempted an HTTP redirect; credential forwarding was blocked.',
        'response': 'Provider returned an invalid or oversized JSON response.',
        'http': 'Provider returned an unexpected HTTP error. No automatic retry was made.',
        'incomplete': 'Model response was incomplete (possibly the output-token limit). No tool action was executed.',
        'tool_response': 'Model did not return exactly one valid function call. No tool action was executed.',
        'budget_usage': 'Provider usage exceeded the reserved token estimate. Further automatic work stopped.',
    }

    def __init__(self, code, verification_code=None, reason=None):
        self.code = code if code in self.MESSAGES else 'http'
        message = self.MESSAGES[self.code]
        if type(verification_code) is int and 0 <= verification_code <= 100:
            message += f' Certificate verification code: {verification_code}.'
        if reason in {'CERTIFICATE_VERIFY_FAILED', 'SSLV3_ALERT_HANDSHAKE_FAILURE', 'TLSV1_ALERT_PROTOCOL_VERSION',
                      'UNEXPECTED_EOF_WHILE_READING', 'TLSV1_ALERT_INTERNAL_ERROR', 'WRONG_VERSION_NUMBER',
                      'UNSUPPORTED_PROTOCOL', 'NO_CIPHERS_AVAILABLE', 'SSLV3_ALERT_BAD_CERTIFICATE', 'TLSV1_ALERT_DECODE_ERROR'}:
            message += f' TLS reason: {reason}.'
        super().__init__(message)


def tls_error(error):
    return ProviderError('tls' if isinstance(error, ssl.SSLCertVerificationError) else 'tls_protocol',
                         getattr(error, 'verify_code', None), getattr(error, 'reason', None))


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
            raise ProviderError('budget_usage')
        self.used -= reserved - actual


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ProviderError('redirect')


class ResponsesProvider:
    def __init__(self, model=None, key=None, base_url=None):
        self.model = model if model is not None else os.getenv('CODIX_MODEL', '')
        self.key = key if key is not None else load_key()
        self.base_url = (base_url if base_url is not None else os.getenv('OPENAI_BASE_URL', AVALAI_URL)).rstrip('/')
        if self.base_url not in (AVALAI_URL, OPENAI_URL):
            raise RuntimeError('API endpoint must be the approved HTTPS AvalAI or OpenAI base URL.')
        if not self.key or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,100}', self.model):
            raise RuntimeError('Save the private AvalAI Windows key (or configure AVALAI_API_KEY/OPENAI_API_KEY) and set CODIX_MODEL before starting a task. Never paste the key into chat.')
        # Frozen Windows Python may lack an up-to-date system issuer chain.
        # Keep Windows trust, hostname verification and TLS validation, adding public roots.
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        handlers = [NoRedirect(), urllib.request.HTTPSHandler(context=context)]
        if self.base_url == AVALAI_URL:
            # User-approved direct route applies only to this exact allowlisted origin.
            handlers.append(urllib.request.ProxyHandler({}))
        self.opener = urllib.request.build_opener(*handlers)

    def _post(self, endpoint, payload):
        request = urllib.request.Request(self.base_url + '/' + endpoint,
                                         data=json.dumps(payload).encode(), method='POST',
                                         headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=90) as response:
                raw = response.read(512001)
                if len(raw) > 512000:
                    raise ProviderError('response')
                return json.loads(raw)
        except ProviderError:
            raise
        except urllib.error.HTTPError as error:
            code = {400: 'request', 401: 'authentication', 403: 'permission',
                    404: 'not_found', 422: 'request', 429: 'rate_limit'}.get(error.code,
                    'server' if 500 <= error.code <= 599 else 'http')
            # Inspect only a bounded error code against a fixed allowlist. Never publish bodies.
            try:
                details = json.loads(error.read(8192)).get('error', {})
                if isinstance(details, dict) and details.get('code') in ('insufficient_quota', 'insufficient_balance', 'credit_balance_too_low'):
                    code = 'quota'
            except Exception:
                pass
            finally:
                error.close()
            raise ProviderError(code) from None
        except urllib.error.URLError as error:
            raise (tls_error(error.reason) if isinstance(error.reason, ssl.SSLError) else ProviderError('network')) from None
        except ssl.SSLError as error:
            raise tls_error(error) from None
        except (ValueError, UnicodeError):
            raise ProviderError('response') from None
        except Exception:
            # Do not forward urllib errors, response bodies, headers or secrets into logs/UI.
            raise ProviderError('network') from None

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
            raise ProviderError('incomplete')
        calls = [item for item in response.get('output', []) if item.get('type') == 'function_call']
        if len(calls) != 1 or not isinstance(calls[0].get('arguments'), str) or len(calls[0]['arguments']) > 65536:
            raise ProviderError('tool_response')
        try:
            return calls[0]['name'], json.loads(calls[0]['arguments'])
        except (KeyError, ValueError):
            raise ProviderError('tool_response') from None
