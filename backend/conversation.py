"""Bounded, memory-only context for the single active project session."""
import copy
import secrets

from backend.policy import redact

REPLY = {'type': 'function', 'name': 'reply', 'description': 'Reply conversationally without executing any action.',
         'strict': True, 'parameters': {'type': 'object', 'additionalProperties': False,
         'properties': {'message': {'type': 'string'}}, 'required': ['message']}}


class Conversation:
    def __init__(self):
        self.messages = []
        self.truncated = False

    def add(self, role, content, kind, task_id):
        message = {'id': secrets.token_urlsafe(12), 'role': role, 'content': redact(content)[:8000],
                   'kind': kind, 'task_id': task_id}
        self.messages.append(message)
        while len(self.messages) > 24 or sum(len(item['content']) for item in self.messages) > 16000:
            self.messages.pop(0)
            self.truncated = True
        return message['id']

    def context(self, pending_id):
        recent, size = [], 0
        for item in reversed(self.messages):
            if item['id'] == pending_id:
                continue
            if len(recent) == 10 or size + len(item['content']) > 8000:
                break
            recent.append({'role': item['role'], 'content': item['content']})
            size += len(item['content'])
        return list(reversed(recent))

    def snapshot(self):
        return copy.deepcopy(self.messages)
