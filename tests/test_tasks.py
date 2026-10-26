import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import http.client
import threading
from unittest.mock import patch

from backend.provider import Budget, BudgetExceeded, ResponsesProvider, ProviderError
from backend.tasks import TaskManager
from backend.tools import ToolService
from tests.test_tools import LocalGateway
from backend.server import make_server


class ScriptedProvider:
    def __init__(self, script, cost=100):
        self.script = list(script)
        self.cost = cost
        self.contexts = []

    def call(self, instructions, context, tools, budget, forced=None):
        reserved = budget.reserve(self.cost, 2048)
        self.contexts.append(context)
        budget.settle(reserved, {'input_tokens': self.cost, 'output_tokens': 20})
        if not self.script:
            raise RuntimeError('Script exhausted')
        return self.script.pop(0)


def wait(run):
    run.thread.join(timeout=8)
    if run.thread.is_alive():
        raise AssertionError('Task did not stop at a bounded checkpoint')
    return run.snapshot()


class GraphTests(unittest.TestCase):
    def test_provider_diagnostic_survives_graph_without_raw_exception(self):
        class RejectedProvider:
            def call(self, *_args, **_kwargs):
                raise ProviderError('authentication')
        manager = TaskManager(self.tools, RejectedProvider)
        manager.start('project', 'Check the task')
        state = wait(manager.current)
        self.assertEqual(state['status'], 'stopped')
        self.assertIn('HTTP 401', state['report']['unresolved'][0])
        self.assertEqual(state['changed_files'], [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gateway = LocalGateway(self.root)
        self.tools = ToolService(self.gateway)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, script, cost=100):
        provider = ScriptedProvider(script, cost)
        manager = TaskManager(self.tools, lambda: provider)
        manager.start('project', 'Create a small file and verify it.')
        return manager, manager.current, provider

    def test_plan_before_edit_ordered_steps_approval_and_report(self):
        manager, run, provider = self.start([
            ('set_plan', {'steps': ['Create file', 'Run checks']}),
            ('create_file', {'path': 'a.txt', 'content': 'hello'}),
            ('finish_step', {'summary': 'File created', 'acceptance_met': True}),
            ('run_command', {'command': 'python3 -m unittest', 'cwd': '.'}),
            ('finish_step', {'summary': 'Acceptance checked', 'acceptance_met': True}),
        ])
        state = wait(run)
        self.assertEqual(state['status'], 'awaiting_approval')
        self.assertEqual(self.gateway.commands, [])
        self.assertEqual((self.root / 'a.txt').read_text(), 'hello')
        self.assertEqual(state['plan'][0]['status'], 'completed')
        self.assertEqual(state['step'], 1)
        run.decide(state['approval']['decision_id'], True)
        state = wait(run)
        self.assertEqual(state['status'], 'completed', state)
        self.assertEqual(state['report']['changed_files'], ['a.txt'])
        self.assertEqual(state['report']['commands'][0]['exit_code'], 0)
        self.assertEqual(state['tokens_used'], 600)
        self.assertEqual(provider.contexts[0]['plan'], [])
        self.assertEqual(provider.contexts[1]['current_step'], 0)

    def test_denied_command_does_not_run_or_call_model_again(self):
        manager, run, provider = self.start([
            ('set_plan', {'steps': ['Check']}),
            ('run_command', {'command': 'echo check', 'cwd': '.'}),
        ])
        state = wait(run)
        decision_id = state['approval']['decision_id']
        with self.assertRaises(PermissionError):
            run.decide('forged', True)
        run.decide(decision_id, False)
        state = wait(run)
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(self.gateway.commands, [])
        self.assertEqual(state['model_calls'], 2)
        with self.assertRaises(PermissionError):
            run.decide(decision_id, True)

    def test_budget_stops_calls_preserves_changes_and_report(self):
        manager, run, provider = self.start([
            ('set_plan', {'steps': ['Create and check']}),
            ('create_file', {'path': 'a.txt', 'content': 'preserve'}),
            ('finish_step', {'summary': 'Must never run', 'acceptance_met': True}),
        ], cost=10000)
        state = wait(run)
        self.assertEqual(state['status'], 'budget_exhausted', state)
        self.assertEqual((self.root / 'a.txt').read_text(), 'preserve')
        self.assertEqual(state['changed_files'], ['a.txt'])
        self.assertEqual(state['model_calls'], 2)
        self.assertLessEqual(state['tokens_used'], 25000)

    def test_no_checks_means_incomplete_not_verified_success(self):
        manager, run, provider = self.start([
            ('set_plan', {'steps': ['Inspect']}),
            ('finish_step', {'summary': 'Inspection complete', 'acceptance_met': True}),
        ])
        state = wait(run)
        self.assertEqual(state['status'], 'incomplete')
        self.assertTrue(state['report']['skipped_checks'])

    def test_failed_command_requests_correction_and_does_not_retry_transport(self):
        self.gateway.command_result.code = 1
        manager, run, provider = self.start([
            ('set_plan', {'steps': ['Check']}),
            ('run_command', {'command': 'python3 -m unittest', 'cwd': '.'}),
            ('finish_step', {'summary': 'Cannot fix', 'acceptance_met': False}),
        ])
        state = wait(run)
        run.decide(state['approval']['decision_id'], True)
        state = wait(run)
        self.assertEqual(state['status'], 'incomplete')
        self.assertEqual(state['correction_cycles'], 1)
        self.assertEqual(state['model_calls'], 3)
        self.assertEqual(len(self.gateway.commands), 1)

    def test_revised_plan_pauses_and_new_task_does_not_inherit_plan(self):
        manager, run, provider = self.start([
            ('set_plan', {'steps': ['Original']}),
            ('set_plan', {'steps': ['Revised']}),
            ('finish_step', {'summary': 'Inspected', 'acceptance_met': False}),
        ])
        state = wait(run)
        self.assertEqual(state['status'], 'awaiting_approval')
        self.assertEqual(state['plan'][0]['title'], 'Original')
        with self.assertRaises(PermissionError):
            manager.start('project', 'Second task')
        run.decide(state['approval']['decision_id'], True)
        state = wait(run)
        self.assertEqual(state['plan'][0]['title'], 'Revised')
        self.assertEqual(state['status'], 'incomplete')
        manager.provider_factory = lambda: ScriptedProvider([('set_plan', {'steps': ['New task']}),
            ('finish_step', {'summary': 'Done', 'acceptance_met': False})])
        manager.start('project', 'New task')
        self.assertEqual(wait(manager.current)['status'], 'incomplete')

    def test_model_that_never_finishes_is_bounded_to_forty_calls(self):
        manager, run, provider = self.start([('set_plan', {'steps': ['Inspect']})] +
                                             [('list_files', {'path': '.'})] * 50)
        state = wait(run)
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(state['model_calls'], 40)

    def test_invalid_planner_cannot_edit_or_inherit_prior_task_plan(self):
        self.tools.plans['project'] = {'version': 99, 'steps': ['Previous task']}
        manager, run, provider = self.start([('create_file', {'path': 'a.txt', 'content': 'not allowed'})])
        state = wait(run)
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(state['plan'], [])
        self.assertFalse((self.root / 'a.txt').exists())


class ProviderTests(unittest.TestCase):
    def provider(self, replies):
        class FixtureProvider(ResponsesProvider):
            def __init__(self):
                super().__init__('test-model', 'fixture-key', base_url='https://api.openai.com/v1')
                self.requests = []

            def _post(self, endpoint, payload):
                self.requests.append((endpoint, payload))
                result = replies.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result
        return FixtureProvider()

    def completed(self, usage=None):
        return {'status': 'completed', 'usage': usage, 'output': [
            {'type': 'function_call', 'name': 'set_plan', 'arguments': '{"steps":["Inspect"]}'}]}

    def test_count_then_reserve_then_response_and_usage(self):
        provider = self.provider([{'input_tokens': 123}, self.completed({'input_tokens': 123, 'output_tokens': 10})])
        budget = Budget()
        name, args = provider.call('policy', {'task': 'inspect'}, [], budget)
        self.assertEqual(name, 'set_plan')
        self.assertEqual(budget.used, 133)
        count, create = provider.requests
        self.assertEqual(count[0], 'responses/input_tokens')
        self.assertEqual(create[0], 'responses')
        self.assertEqual(create[1]['max_output_tokens'], 2048)
        self.assertFalse(create[1]['store'])
        for key, value in count[1].items():
            self.assertEqual(create[1][key], value)

    def test_missing_usage_keeps_full_reservation_and_network_has_no_retry(self):
        provider = self.provider([{'input_tokens': 100}, self.completed()])
        budget = Budget()
        provider.call('p', {}, [], budget)
        self.assertEqual(budget.used, 2148)
        provider = self.provider([{'input_tokens': 100}, RuntimeError('network')])
        with self.assertRaises(RuntimeError):
            provider.call('p', {}, [], budget)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(budget.used, 4296)

    def test_budget_or_unknown_count_prevents_model_request(self):
        for count in ({'input_tokens': 24999}, {}, {'input_tokens': True}):
            provider = self.provider([count])
            with self.subTest(count=count), self.assertRaises(RuntimeError):
                provider.call('p', {}, [], Budget())
            self.assertEqual(len(provider.requests), 1)

    def test_unconfigured_model_or_key_fails_without_network(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            ResponsesProvider()

    def test_incomplete_or_parallel_calls_are_not_actions(self):
        for response in ({'status': 'incomplete', 'output': []},
                         {'status': 'completed', 'output': self.completed()['output'] * 2}):
            provider = self.provider([{'input_tokens': 10}, response])
            with self.subTest(response=response['status']), self.assertRaises(RuntimeError):
                provider.call('p', {}, [], Budget())

    def test_count_network_failure_prevents_inference_and_usage_overrun_stops(self):
        provider = self.provider([RuntimeError('count failed')])
        budget = Budget()
        with self.assertRaises(RuntimeError):
            provider.call('p', {}, [], budget)
        self.assertEqual(budget.calls, 0)
        self.assertEqual(len(provider.requests), 1)
        reserved = budget.reserve(100, 100)
        with self.assertRaises(RuntimeError):
            budget.settle(reserved, {'input_tokens': 100, 'output_tokens': 101})


class TaskApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gateway = LocalGateway(Path(self.temp.name))
        self.tools = ToolService(self.gateway)
        self.tasks = TaskManager(self.tools, lambda: ScriptedProvider([
            ('set_plan', {'steps': ['Check']}),
            ('run_command', {'command': 'echo check', 'cwd': '.'}),
            ('finish_step', {'summary': 'Checked', 'acceptance_met': True}),
        ]))
        self.token = 'e' * 64
        self.server = make_server(self.token, 0, tool_service=self.tools, task_manager=self.tasks)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, endpoint, body):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        client.request('POST', endpoint, body=json.dumps(body), headers={'Authorization': f'Bearer {self.token}'})
        response = client.getresponse()
        status, data = response.status, json.loads(response.read())
        client.close()
        return status, data

    def test_active_task_locks_manual_tools_and_only_matching_decision_resumes(self):
        status, result = self.post('/tasks/start', {'project_id': 'project', 'request': 'Run a check'})
        self.assertEqual(status, 200)
        state = wait(self.tasks.current)
        task_id = result['task_id']
        status, _ = self.post('/tools/propose', {'project_id': 'project', 'name': 'create_file',
                                               'arguments': {'path': 'bypass.txt', 'content': 'x'}})
        self.assertEqual(status, 403)
        status, _ = self.post('/tasks/decide', {'task_id': task_id, 'decision_id': 'forged', 'approved': True})
        self.assertEqual(status, 403)
        self.assertEqual(self.gateway.commands, [])
        status, _ = self.post('/tasks/decide', {'task_id': task_id, 'decision_id': state['approval']['decision_id'], 'approved': True})
        self.assertEqual(status, 200)
        self.assertEqual(wait(self.tasks.current)['status'], 'completed')
        self.assertEqual(len(self.gateway.commands), 1)
        self.assertFalse((Path(self.temp.name) / 'bypass.txt').exists())
