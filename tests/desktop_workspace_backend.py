"""Test-only real PTY/file backend; never selectable in the packaged product."""
from pathlib import Path
import tempfile
from backend import server
from backend.tools import ToolService
from tests.test_tools import LocalGateway
from tests.test_workspace import LocalTerminals

directory = tempfile.TemporaryDirectory()
root = Path(directory.name)
(root / 'src').mkdir()
(root / 'hello.py').write_text('print("سلام، Codix")\n')
(root / 'src/second.py').write_text('answer = 42\n')
(root / 'binary.dat').write_bytes(b'\0\xff')
(root / 'large.txt').write_bytes(b'x' * 32769)
(root / '.env').write_text('SECRET=value-hidden')

class Manager:
    def preview(self, selected):
        return {'ticket': 'selection', 'root': str(root), 'dockerfile': False}

    def prepare(self, ticket, approved):
        return {'project_id': 'project', 'root': str(root), 'status': 'ready'}

original = server.make_server
server.make_server = lambda token, port: original(token, port, Manager(), ToolService(LocalGateway(root)),
                                                terminal_service=LocalTerminals(root))
try:
    raise SystemExit(server.main())
finally:
    directory.cleanup()
