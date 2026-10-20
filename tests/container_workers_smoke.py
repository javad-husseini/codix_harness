"""Execute real standalone workers in the default project container/Windows bind mount."""
import json
from pathlib import Path
import subprocess
import sys

from backend import container_files, container_terminal

target = '.verification/phase2-worker-check.txt'
if Path(target).exists():
    raise SystemExit('Existing smoke-test target found; refusing to overwrite it.')
file_source = Path(container_files.__file__).read_text()


def file_request(request, success=True):
    result = subprocess.run([sys.executable, '-I', '-c', file_source], input=json.dumps(request),
                            text=True, capture_output=True, timeout=10)
    response = json.loads(result.stdout)
    assert response['ok'] is success, response.get('error')
    return response.get('data')


file_request({'op': 'write', 'path': target, 'content': 'created\n', 'exists': False, 'expected': None})
current = file_request({'op': 'inspect', 'path': target})
assert current['content'] == 'created\n'
file_request({'op': 'write', 'path': target, 'content': 'wrong', 'exists': True, 'expected': 'forged'}, False)
assert Path(target).read_text() == 'created\n'
file_request({'op': 'write', 'path': target, 'content': 'edited\n', 'exists': True, 'expected': current['sha256']})
current = file_request({'op': 'inspect', 'path': target})
assert current['content'] == 'edited\n'
file_request({'op': 'inspect', 'path': '../outside'}, False)
file_request({'op': 'delete', 'path': target, 'exists': True, 'expected': current['sha256']})
assert not Path(target).exists()
bootstrap = Path(container_terminal.__file__).read_text()
result = subprocess.run([sys.executable, '-I', '-c', bootstrap],
                        input=json.dumps({'cwd': '.', 'command': 'printf phase2-command'}),
                        text=True, capture_output=True, timeout=10)
assert result.returncode == 0 and result.stdout == 'phase2-command', result.stderr
print('PASS real project-container workers: Windows bind create/read/edit/delete, stale hash, traversal rejection, exact command bootstrap')
