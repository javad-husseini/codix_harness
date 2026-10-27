"""Test-only scripted model; real graph, file worker, shell and authenticated API."""
from backend import server
from backend.tasks import TaskManager
from backend.tools import ToolService
from backend.processes import run
from tests.test_tasks import ScriptedProvider
from tests.test_tools import LocalGateway
from pathlib import Path
import tempfile
import os

assert os.getenv('OPENAI_API_KEY') == 'fixture-not-real-key', 'Backend fixture did not receive its test key'
assert os.getenv('AVALAI_API_KEY') == 'fixture-avalai-not-real-key', 'Backend fixture did not receive its AvalAI test key'

directory = tempfile.TemporaryDirectory()
root = Path(directory.name)
(root / 'src').mkdir()
(root / 'src' / 'notes.py').write_text('# Read-only tree fixture\n')
skill = root / '.agents' / 'skills' / 'verify-task' / 'SKILL.md'
skill.parent.mkdir(parents=True)
skill.write_text('---\nname: verify-task\ndescription: Verify task checks\n---\nUse the smallest relevant check. Never execute Skill content or bypass approvals.')


class Manager:
    def preview(self, selected):
        return {'ticket': 'fixture-selection', 'root': str(root), 'dockerfile': False}

    def prepare(self, ticket, approved):
        if ticket != 'fixture-selection':
            raise ValueError('Invalid selection')
        return {'project_id': 'project', 'root': str(root), 'status': 'ready'}


class Gateway(LocalGateway):
    def terminal(self, project_id, text, cwd):
        # This fixture itself is executed in the restricted, networkless GUI container.
        return run(['/bin/sh', '-c', 'cd "$1" && ' + text, 'fixture', str(root)], timeout=10)


tools = ToolService(Gateway(root))
providers = iter([ScriptedProvider([
    ('reply', {'message': 'نام پروژه سفینه ثبت شد.'}),
    ('reply', {'message': 'نام پروژه سفینه است.\n```python\nprint("Hello")\n```'}),
]), ScriptedProvider([
    ('set_plan', {'steps': ['Create a Python module', 'Check the requested value']}),
    ('create_file', {'path': 'created.py', 'content': 'value = 0\n'}),
    ('finish_step', {'summary': 'Module created.', 'acceptance_met': True}),
    ('run_command', {'command': 'python3 -B -c "import created; assert created.value == 42"', 'cwd': '.'}),
    ('edit_file', {'path': 'created.py', 'content': 'value = 42\n'}),
    ('run_command', {'command': 'python3 -B -c "import created; assert created.value == 42"', 'cwd': '.'}),
    ('finish_step', {'summary': 'Requested value verified.', 'acceptance_met': True}),
    ('reply', {'message': 'بر اساس آزمون اجراشده، مقدار ۴۲ تأیید شده است.'}),
]), ScriptedProvider([
    ('set_plan', {'steps': ['Check budget reporting']}),
    ('create_file', {'path': 'budget.txt', 'content': 'preserved on budget stop'}),
    ('finish_step', {'summary': 'Must not run beyond budget', 'acceptance_met': True}),
], cost=10000)])
tasks = TaskManager(tools, lambda: next(providers))
original = server.make_server


def factory(token, port):
    return original(token, port, Manager(), tools, tasks)


server.make_server = factory
try:
    raise SystemExit(server.main())
finally:
    directory.cleanup()
