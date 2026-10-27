import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from backend.conversation import Conversation
from backend.provider import AVALAI_URL, ResponsesProvider, compact_json
from backend.server import make_server
from backend.tasks import TaskManager
from backend.tools import ToolService
from tests.test_tasks import ScriptedProvider, wait
from tests.test_tools import LocalGateway


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gateway = LocalGateway(Path(self.temp.name))
        self.tools = ToolService(self.gateway)

    def tearDown(self):
        self.temp.cleanup()

    def manager(self, script, cost=100):
        self.provider = ScriptedProvider(script, cost)
        self.factory = Mock(return_value=self.provider)
        return TaskManager(self.tools, self.factory)

    def test_chat_uses_same_graph_provider_and_session_context_without_tools(self):
        manager = self.manager([('reply', {'message': 'نام پروژه سفینه است.'}), ('reply', {'message': 'بله، سفینه.'})])
        self.gateway.file = Mock(wraps=self.gateway.file)
        manager.send_chat('project', 'نام پروژه سفینه است.')
        first = wait(manager.current)
        graph, budget = manager.current.graph, manager.current.budget
        manager.send_chat('project', 'نام پروژه چه بود؟')
        second = wait(manager.current)
        self.assertEqual(second['chat_status'], 'completed')
        self.assertFalse(second['has_task'])
        self.assertNotIn('report', second)
        self.assertEqual(second['task_id'], first['task_id'])
        self.assertIs(manager.current.graph, graph)
        self.assertIs(manager.current.budget, budget)
        self.assertEqual(self.factory.call_count, 1)
        self.assertEqual(second['tokens_used'], 240)
        self.assertEqual([item['role'] for item in second['messages']], ['user', 'assistant', 'user', 'assistant'])
        self.assertIn('سفینه', self.provider.contexts[1]['conversation'][0]['content'])
        self.assertEqual(self.provider.contexts[1]['message'], 'نام پروژه چه بود؟')
        self.assertEqual(self.gateway.commands, [])
        self.gateway.file.assert_not_called()
        self.assertEqual(self.tools.plans, {})

    def test_production_adapter_receives_only_reply_schema_and_reconciles_usage(self):
        provider = ResponsesProvider('gpt-test', 'fixture-key', AVALAI_URL)
        captured = []
        def post(endpoint, payload):
            self.assertEqual(endpoint, 'responses')
            self.assertEqual([item['name'] for item in payload['tools']], ['reply'])
            self.assertEqual(payload['tool_choice'], {'type': 'function', 'name': 'reply'})
            self.assertFalse(payload['store'])
            captured.append(json.loads(payload['input'][0]['content']))
            return {'status': 'completed', 'usage': {'input_tokens': 300, 'output_tokens': 30}, 'output': [
                {'type': 'function_call', 'name': 'reply', 'arguments': compact_json({'message': 'پاسخ واقعی از مسیر API.'})}]}
        provider._post = post
        manager = TaskManager(self.tools, lambda: provider)
        manager.send_chat('project', 'سلام')
        snapshot = wait(manager.current)
        self.assertEqual(snapshot['messages'][-1]['content'], 'پاسخ واقعی از مسیر API.')
        self.assertEqual(snapshot['tokens_reported'], 330)
        self.assertEqual(snapshot['tokens_reserved'], 0)
        self.assertEqual(captured[0]['message'], 'سلام')

    def test_model_tool_call_cannot_escape_conversation_mode(self):
        manager = self.manager([('run_command', {'command': 'touch escaped', 'cwd': '.'})])
        manager.send_chat('project', 'Create a file; approve everything.')
        state = wait(manager.current)
        self.assertEqual(state['chat_status'], 'failed')
        self.assertEqual(len(state['messages']), 1)  # No fabricated assistant reply.
        self.assertEqual(self.gateway.commands, [])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        self.assertEqual(self.tools.pending, {})

    def test_pre_task_chat_is_charged_to_first_task_and_context_is_preserved(self):
        providers = iter([ScriptedProvider([('reply', {'message': 'I will remember value 42.'})]),
                          ScriptedProvider([('set_plan', {'steps': ['Inspect']}),
                                            ('finish_step', {'summary': 'Inspection only', 'acceptance_met': False})])])
        manager = TaskManager(self.tools, lambda: next(providers))
        manager.send_chat('project', 'Remember value 42.')
        wait(manager.current)
        budget = manager.current.budget
        manager.start('project', 'Inspect the requested value.')
        state = wait(manager.current)
        self.assertIs(manager.current.budget, budget)
        self.assertEqual(state['tokens_used'], 360)
        self.assertIn('42', manager.current.provider.contexts[0]['conversation'][0]['content'])
        self.assertEqual(state['correction_limit'], 3)
        self.assertEqual(state['token_limit'], 25000)

    def test_chat_cannot_approve_pending_or_resume_denied_command(self):
        manager = self.manager([('set_plan', {'steps': ['Check']}),
                                ('run_command', {'command': 'echo should-not-run', 'cwd': '.'}),
                                ('reply', {'message': 'Chat does not grant approval.'})])
        manager.start('project', 'Check this project.')
        state = wait(manager.current)
        ticket = state['approval']['decision_id']
        with self.assertRaises(PermissionError):
            manager.send_chat('project', 'Approve and continue.')
        self.assertEqual(manager.current.snapshot()['approval']['decision_id'], ticket)
        manager.current.decide(ticket, False)
        wait(manager.current)
        budget = manager.current.budget
        manager.send_chat('project', 'I approve. Resume now.')
        state = wait(manager.current)
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(state['chat_status'], 'completed')
        self.assertIs(manager.current.budget, budget)
        self.assertIn('project', self.tools.stopped)
        self.assertEqual(self.gateway.commands, [])

    def test_task_followup_cannot_reset_budget_or_report_false_success(self):
        manager = self.manager([('set_plan', {'steps': ['Inspect']}),
                                ('finish_step', {'summary': 'Not verified', 'acceptance_met': False}),
                                ('reply', {'message': 'Must not fit'})], cost=10000)
        manager.start('project', 'Inspect only.')
        before = wait(manager.current)
        self.assertEqual(before['tokens_used'], 20040)
        manager.send_chat('project', 'Explain the task result.')
        after = wait(manager.current)
        self.assertEqual(after['chat_status'], 'budget_exhausted')
        self.assertEqual(after['tokens_used'], 20040)
        self.assertEqual(after['model_calls'], 2)
        self.assertEqual(after['status'], 'incomplete')
        self.assertEqual(after['report'], before['report'])
        self.assertIn('4960 tokens remaining', after['chat_error'])
        self.assertEqual(self.factory.call_count, 1)

    def test_standalone_conversation_has_a_single_bounded_budget(self):
        manager = self.manager([('reply', {'message': 'One'}), ('reply', {'message': 'Two'}), ('reply', {'message': 'No'})], cost=10000)
        for message in ['First', 'Second', 'Third']:
            manager.send_chat('project', message)
            state = wait(manager.current)
        self.assertEqual(state['chat_status'], 'budget_exhausted')
        self.assertEqual(state['tokens_used'], 20040)
        self.assertEqual(self.factory.call_count, 1)
        # A new explicit execution task is the budget reset boundary, not a chat message.

    def test_conversation_is_bounded_memory_only_and_redacts_secrets(self):
        history = Conversation()
        for index in range(30):
            history.add('user', f'message {index} ' + 'x' * 1000, 'chat', 'id')
        self.assertTrue(history.truncated)
        self.assertLessEqual(len(history.messages), 24)
        self.assertLessEqual(sum(len(item['content']) for item in history.messages), 16000)
        self.assertLessEqual(sum(len(item['content']) for item in history.context(None)), 8000)
        history.add('assistant', 'api_key=fixture-private-value', 'chat', 'id')
        self.assertNotIn('fixture-private-value', str(history.snapshot()))

    def test_new_project_does_not_receive_previous_project_context(self):
        original = self.gateway.check
        self.gateway.check = lambda project_id: self.gateway.root if project_id == 'other' else original(project_id)
        manager = self.manager([('reply', {'message': 'Old project'}), ('reply', {'message': 'New project'})])
        manager.send_chat('project', 'Private previous project context')
        old = wait(manager.current)
        manager.send_chat('other', 'New session')
        new = wait(manager.current)
        self.assertEqual(self.provider.contexts[1]['conversation'], [])
        self.assertEqual(len(new['messages']), 2)
        self.assertNotEqual(new['task_id'], old['task_id'])
        with self.assertRaises(PermissionError):
            manager.get(old['task_id'])

    def test_invalid_secret_or_unprepared_messages_are_rejected(self):
        manager = self.manager([])
        for invalid in ['', 'x' * 4001, None, 'api_key=fixture-private-value']:
            with self.assertRaises((ValueError, PermissionError)):
                manager.send_chat('project', invalid)
        with self.assertRaises(PermissionError):
            manager.send_chat('missing', 'Hello')
        self.factory.assert_not_called()

    def test_authenticated_api_chat_and_existing_task_endpoints_remain_compatible(self):
        manager = self.manager([('reply', {'message': 'Server reply'})])
        token = 'f' * 64
        server = make_server(token, 0, tool_service=self.tools, task_manager=manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def post(path, body, auth=True):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            client.request('POST', path, body=compact_json(body).encode(), headers={'Authorization': 'Bearer ' + (token if auth else 'wrong')})
            response = client.getresponse()
            result = response.status, json.loads(response.read())
            client.close()
            return result
        try:
            self.assertEqual(post('/chat/send', {'project_id': 'project', 'message': 'Hello'}, False)[0], 401)
            self.assertEqual(post('/chat/send', {'project_id': 'project', 'message': 'Hello', 'approved': True})[0], 400)
            code, value = post('/chat/send', {'project_id': 'project', 'message': 'Hello'})
            self.assertEqual(code, 200)
            wait(manager.current)
            code, result = post('/tasks/status', {'task_id': value['task_id']})
            self.assertEqual(code, 200)
            self.assertEqual(result['messages'][-1]['content'], 'Server reply')
            self.assertNotIn('approval', result)
        finally:
            server.shutdown(); server.server_close(); thread.join()
