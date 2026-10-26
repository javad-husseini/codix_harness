import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from backend.processes import run as process_run
from backend.provider import AVALAI_URL, Budget, BudgetExceeded, ResponsesProvider, compact_json
from backend.tasks import TaskManager, compact_listing
from backend.tools import ToolService
from tests.test_tasks import wait
from tests.test_tools import LocalGateway


def completed(name='set_plan', args=None, usage=None):
    return {'status': 'completed', 'usage': usage, 'output': [
        {'type': 'function_call', 'name': name, 'arguments': compact_json(args or {})}]}


class BudgetRegressionTests(unittest.TestCase):
    def test_utf8_request_matches_estimate_without_ascii_escape_inflation(self):
        provider = ResponsesProvider('gpt-test', 'fixture-key', AVALAI_URL)
        context = {'task': 'فایل پایتون بساز و اجرا کن. ' * 90}
        budget = Budget()
        budget.used = 13786
        requests = []

        def post(endpoint, payload):
            self.assertEqual(endpoint, 'responses')
            expected = len(compact_json({key: value for key, value in payload.items()
                       if key not in ('max_output_tokens', 'parallel_tool_calls', 'store', 'truncation')}).encode('utf-8')) + 4096 + 2048
            self.assertEqual(budget.used, 13786 + expected)
            old = len(json.dumps({key: value for key, value in payload.items()
                      if key not in ('max_output_tokens', 'parallel_tool_calls', 'store', 'truncation')}).encode()) + 4096 + 2048
            self.assertGreater(old, 25000 - 13786)
            requests.append(payload)
            return completed(usage={'input_tokens': 700, 'output_tokens': 100, 'total_tokens': 800})

        provider._post = post
        provider.call('policy', context, [], budget)
        self.assertEqual(len(requests), 1)
        self.assertEqual(budget.used, 14586)
        # The actual wire transport also preserves literal UTF-8.
        provider.opener = Mock()
        provider.opener.open.return_value = io.BytesIO(b'{}')
        ResponsesProvider._post(provider, 'responses', {'text': 'سلام'})
        request = provider.opener.open.call_args.args[0]
        self.assertEqual(request.data, '{"text":"سلام"}'.encode('utf-8'))

    def test_usage_formats_and_reasoning_are_not_double_counted(self):
        for usage in [
            {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120,
             'output_tokens_details': {'reasoning_tokens': 15}},
            {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120},
            {'total_tokens': 120},
        ]:
            with self.subTest(usage=usage):
                budget = Budget()
                reserved = budget.reserve(500, 2048)
                budget.settle(reserved, usage)
                self.assertEqual((budget.used, budget.reported), (120, 120))

    def test_missing_invalid_or_conflicting_usage_keeps_the_reservation(self):
        for usage in [None, {}, {'input_tokens': 100}, {'total_tokens': True},
                      {'input_tokens': True, 'output_tokens': 20},
                      {'prompt_tokens': -1, 'completion_tokens': 2},
                      {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 1000}]:
            with self.subTest(usage=usage):
                budget = Budget()
                reserved = budget.reserve(500, 2048)
                budget.settle(reserved, usage)
                self.assertEqual(budget.used, reserved)
                self.assertEqual(budget.reported, 0)

    def test_reservation_stop_explains_remaining_and_required_without_sending(self):
        budget = Budget()
        budget.used = 13786
        with self.assertRaisesRegex(BudgetExceeded, '11214 tokens remaining; 12048 required'):
            budget.reserve(10000, 2048)
        self.assertEqual(budget.used, 13786)
        self.assertEqual(budget.calls, 0)
        self.assertEqual(budget.next_required, 12048)
        with self.assertRaises(RuntimeError):
            Budget().reserve(1, True)

    def test_directory_summary_is_bounded_and_marks_omitted_entries(self):
        listing = {'entries': [{'name': 'پوشه-' + str(i), 'directory': True} for i in range(200)], 'truncated': False}
        summary = compact_listing(listing)
        self.assertTrue(summary['truncated'])
        self.assertLessEqual(len(summary['names']), 40)
        self.assertLessEqual(len(compact_json(summary['names']).encode('utf-8')), 1600)
        self.assertTrue(all(name.endswith('/') for name in summary['names']))
        explicit = compact_listing(listing, 200, 4000)
        self.assertEqual(len(explicit['names']), 200)
        self.assertFalse(explicit['truncated'])

    def test_persian_hello_world_real_file_and_shell_with_actual_provider_budget(self):
        # Uses the actual Responses adapter/preflight/settlement and graph, but a scripted
        # transport instead of a paid API. File worker and Python command execute in Docker.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(100):
                (root / ('پوشه-' + str(i))).mkdir()

            class Gateway(LocalGateway):
                def terminal(self, project_id, text, cwd):
                    self.commands.append((text, cwd))
                    return process_run(['/bin/sh', '-c', 'cd "$1" && ' + text, 'fixture', str(root)], timeout=10)

            gateway = Gateway(root)
            provider = ResponsesProvider('gpt-test', 'fixture-key', AVALAI_URL)
            script = [
                ('set_plan', {'steps': ['ساخت فایل و اجرای آزمون خروجی']}),
                ('create_file', {'path': 'hello.py', 'content': 'print("Hello, World!")\n'}),
                ('run_command', {'command': 'python3 -B hello.py', 'cwd': '.'}),
                ('finish_step', {'summary': 'Hello, World! verified.', 'acceptance_met': True}),
            ]
            contexts = []

            def post(endpoint, payload):
                self.assertEqual(endpoint, 'responses')
                context = json.loads(payload['input'][0]['content'])
                contexts.append(context)
                name, args = script.pop(0)
                if name == 'set_plan':
                    self.assertEqual([tool['name'] for tool in payload['tools']], ['set_plan'])
                    self.assertEqual(context['phase'], 'planning')
                    self.assertFalse(context['plan_recorded'])
                else:
                    self.assertEqual(context['phase'], 'execution')
                    self.assertTrue(context['plan_recorded'])
                    replanner = next(tool for tool in payload['tools'] if tool['name'] == 'set_plan')
                    self.assertIn('Never repeat an existing plan', replanner['description'])
                self.assertFalse(any(result['tool'] == 'set_plan' for result in context['recent_results']))
                self.assertLessEqual(manager.current.budget.used, 25000)
                return completed(name, args, {'input_tokens': 1300, 'output_tokens': 80, 'total_tokens': 1380})

            provider._post = post
            manager = TaskManager(ToolService(gateway), lambda: provider)
            manager.start('project', 'یک فایل پایتون بساز که Hello, World! چاپ کند و اجرا کن.')
            state = wait(manager.current)
            self.assertEqual(state['status'], 'awaiting_approval', state)
            self.assertEqual(gateway.commands, [])
            manager.current.decide(state['approval']['decision_id'], True)
            state = wait(manager.current)
            self.assertEqual(state['status'], 'completed', state)
            self.assertEqual(state['model_calls'], 4)
            self.assertEqual(state['tokens_used'], 5520)
            self.assertEqual(state['tokens_reported'], 5520)
            self.assertEqual(state['tokens_reserved'], 0)
            self.assertEqual(state['commands'][0]['stdout'].strip(), 'Hello, World!')
            self.assertEqual(state['commands'][0]['exit_code'], 0)
            self.assertEqual((root / 'hello.py').read_text(), 'print("Hello, World!")\n')
            self.assertEqual(state['correction_cycles'], 0)
            self.assertTrue(contexts[0]['recent_results'][0]['result']['truncated'])

    def test_secret_redaction_in_structured_results_preserves_valid_context(self):
        from backend.tasks import redacted_data
        raw = {'tool': 'read_file', 'result': {'content': 'token=fixture-secret\nordinary text'}}
        safe = redacted_data(raw)
        self.assertNotIn('fixture-secret', compact_json(safe))
        self.assertEqual(json.loads(compact_json(safe)), safe)
