"""GUI-test backend fixture. Never selected by production configuration."""
from pathlib import Path
import tempfile

from backend import server
from backend.tools import ToolService
from tests.test_tools import LocalGateway

directory = tempfile.TemporaryDirectory()
root = Path(directory.name)
(root / 'AGENTS.md').write_text('old instruction\n')
(root / 'note.txt').write_text('keep this file\n')


class FixtureManager:
    def prerequisites(self):
        return {'docker': 'fixture-ready'}

    def preview(self, selected):
        return {'ticket': 'fixture-selection', 'root': str(root), 'dockerfile': False}

    def prepare(self, ticket, approved):
        if ticket != 'fixture-selection':
            raise ValueError('Invalid fixture selection')
        return {'project_id': 'project', 'root': str(root), 'container': 'test-fixture', 'status': 'ready'}


class FixtureGateway(LocalGateway):
    def terminal(self, *args):
        (self.root / 'UNEXPECTED_COMMAND').write_text('command executed')
        return super().terminal(*args)


original_factory = server.make_server


def factory(token, port):
    return original_factory(token, port, FixtureManager(), ToolService(FixtureGateway(root)))


server.make_server = factory
try:
    raise SystemExit(server.main())
finally:
    directory.cleanup()
