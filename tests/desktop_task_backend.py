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
tasks = TaskManager(tools, lambda: ScriptedProvider([
    ('set_plan', {'steps': ['Create a Python module', 'Check the requested value']}),
    ('create_file', {'path': 'created.py', 'content': 'value = 42\n'}),
    ('finish_step', {'summary': 'Module created.', 'acceptance_met': True}),
    ('run_command', {'command': 'python3 -c "import created; assert created.value == 42"', 'cwd': '.'}),
    ('finish_step', {'summary': 'Requested value verified.', 'acceptance_met': True}),
]))
original = server.make_server


def factory(token, port):
    return original(token, port, Manager(), tools, tasks)


server.make_server = factory
try:
    raise SystemExit(server.main())
finally:
    directory.cleanup()
