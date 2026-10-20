import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from backend.container_files import perform
from backend.policy import FILE_LIMIT, category, host_boundary, relative_path
from backend.processes import Result
from backend.tools import ToolService, ContainerGateway
from backend.container_terminal import enter


class LocalGateway:
    """Test dependency only. These tests themselves run inside Docker."""
    def __init__(self, root):
        self.root = root
        self.commands = []
        self.stop_count = 0
        self.command_result = Result(0, 'ok', '')

    def check(self, project_id):
        if project_id != 'project':
            raise PermissionError('Unknown project')
        return self.root

    def file(self, project_id, request):
        self.check(project_id)
        host_boundary(self.root, request['path'])
        return perform(request, str(self.root))

    def terminal(self, project_id, text, cwd):
        self.commands.append((text, cwd))
        return self.command_result

    def stop(self, project_id):
        self.stop_count += 1


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.gateway = LocalGateway(self.root)
        self.now = 0
        self.tools = ToolService(self.gateway, clock=lambda: self.now)

    def tearDown(self):
        self.temporary.cleanup()

    def propose(self, name, **args):
        return self.tools.propose('project', name, args)

    def execute(self, proposal, approved=False):
        return self.tools.execute('project', proposal['ticket'], approved)

    def plan(self):
        proposal = self.propose('set_plan', steps=['Make a targeted edit', 'Run relevant checks'])
        self.execute(proposal, approved=proposal['approval_required'])

    def test_no_edit_or_command_before_plan(self):
        for name, args in [('create_file', {'path': 'a.txt', 'content': 'x'}),
                           ('run_command', {'command': 'true', 'cwd': '.'})]:
            with self.subTest(name=name), self.assertRaises(PermissionError):
                self.propose(name, **args)
        self.assertFalse((self.root / 'a.txt').exists())
        self.assertEqual(self.gateway.commands, [])

    def test_regular_file_lifecycle_and_output(self):
        self.plan()
        proposal = self.propose('create_file', path='a.txt', content='one\n')
        self.assertFalse(proposal['approval_required'])
        self.execute(proposal)
        result = self.execute(self.propose('read_file', path='a.txt'))
        self.assertEqual(result['content'], 'one\n')
        self.execute(self.propose('edit_file', path='a.txt', content='two\n'))
        self.assertEqual((self.root / 'a.txt').read_text(), 'two\n')
        self.assertEqual(self.execute(self.propose('list_files', path='.'))['entries'], [{'name': 'a.txt', 'directory': False}])
        deletion = self.propose('delete_file', path='a.txt')
        self.assertTrue(deletion['approval_required'])
        self.execute(deletion, True)
        self.assertFalse((self.root / 'a.txt').exists())

    def test_rejection_stops_task_and_does_not_delete(self):
        self.plan()
        (self.root / 'a.txt').write_text('keep')
        deletion = self.propose('delete_file', path='a.txt')
        with self.assertRaises(PermissionError):
            self.execute(deletion, False)
        self.assertEqual((self.root / 'a.txt').read_text(), 'keep')
        with self.assertRaises(PermissionError):
            self.propose('edit_file', path='a.txt', content='changed')
        self.plan()
        self.execute(self.propose('edit_file', path='a.txt', content='replanned'))

    def test_protected_write_needs_exact_one_use_approval(self):
        self.plan()
        (self.root / 'AGENTS.md').write_text('old\n')
        proposal = self.propose('edit_file', path='AGENTS.md', content='new\n')
        self.assertTrue(proposal['approval_required'])
        self.assertIn('-old', proposal['detail'])
        self.assertIn('+new', proposal['detail'])
        self.assertEqual((self.root / 'AGENTS.md').read_text(), 'old\n')
        self.execute(proposal, True)
        with self.assertRaises(PermissionError):
            self.execute(proposal, True)

    def test_approval_cannot_be_reused_for_changed_content(self):
        self.plan()
        target = self.root / 'AGENTS.md'
        target.write_text('old')
        proposal = self.propose('edit_file', path='AGENTS.md', content='approved')
        target.write_text('concurrent change')
        with self.assertRaises(PermissionError):
            self.execute(proposal, True)
        self.assertEqual(target.read_text(), 'concurrent change')

    def test_forged_expired_and_cross_project_ticket(self):
        self.plan()
        with self.assertRaises(PermissionError):
            self.tools.execute('project', 'forged', True)
        proposal = self.propose('create_file', path='a.txt', content='x')
        self.now = 301
        with self.assertRaises(PermissionError):
            self.execute(proposal, True)
        self.assertFalse((self.root / 'a.txt').exists())
        proposal = self.propose('create_file', path='a.txt', content='x')
        with self.assertRaises(PermissionError):
            self.tools.execute('other-project', proposal['ticket'], True)

    def test_mutating_arguments_after_preview_has_no_effect(self):
        self.plan()
        args = {'path': 'a.txt', 'content': 'original'}
        proposal = self.tools.propose('project', 'create_file', args)
        args['content'] = 'changed'
        self.execute(proposal)
        self.assertEqual((self.root / 'a.txt').read_text(), 'original')

    def test_new_proposal_invalidates_old_and_plan_replacement_is_sensitive(self):
        self.plan()
        old = self.propose('create_file', path='a.txt', content='x')
        replacement = self.propose('set_plan', steps=['Different approach'])
        self.assertTrue(replacement['approval_required'])
        self.execute(replacement, True)
        with self.assertRaises(PermissionError):
            self.execute(old, True)

    def test_commands_always_pause_and_no_script_allowlist_bypass(self):
        self.plan()
        for text in ['echo hello', 'npm install', 'python3 script.py', 'echo x; rm -f file', 'sudo true']:
            with self.subTest(command=text):
                proposal = self.propose('run_command', command=text, cwd='.')
                self.assertTrue(proposal['approval_required'])
                self.assertIn(repr(text), proposal['detail'])
                self.assertEqual(len(self.gateway.commands), 0)
                with self.assertRaises(PermissionError):
                    self.execute(proposal, False)
                self.plan()

    def test_approved_command_output_redaction_and_timeout_stop(self):
        self.plan()
        self.gateway.command_result = Result(0, 'API_KEY=private-value\nsk-example12345678', '')
        result = self.execute(self.propose('run_command', command='python3 check.py', cwd='.'), True)
        self.assertNotIn('private-value', result['stdout'])
        self.assertNotIn('sk-example12345678', result['stdout'])
        self.gateway.command_result = Result(124, '', '')
        result = self.execute(self.propose('run_command', command='sleep 999', cwd='.'), True)
        self.assertTrue(result['timed_out'])
        self.assertEqual(self.gateway.stop_count, 1)
        with self.assertRaises(PermissionError):
            self.propose('create_file', path='a.txt', content='x')

    def test_secret_reads_blocked_and_secret_changes_do_not_echo_values(self):
        self.plan()
        (self.root / '.env').write_text('API_KEY=old-private-value')
        with self.assertRaises(PermissionError):
            self.propose('read_file', path='.env')
        proposal = self.propose('edit_file', path='.env', content='API_KEY=new-private-value')
        self.assertTrue(proposal['approval_required'])
        self.assertNotIn('old-private-value', json.dumps(proposal))
        self.assertNotIn('new-private-value', json.dumps(proposal))
        self.execute(proposal, True)
        self.assertEqual((self.root / '.env').read_text(), 'API_KEY=new-private-value')

    def test_large_and_non_utf8_files_blocked(self):
        self.plan()
        with self.assertRaises(ValueError):
            self.propose('create_file', path='a.txt', content='x' * (FILE_LIMIT + 1))
        (self.root / 'large').write_bytes(b'x' * (FILE_LIMIT + 1))
        with self.assertRaises(ValueError):
            self.propose('read_file', path='large')
        (self.root / 'binary').write_bytes(b'\xff')
        with self.assertRaises(UnicodeDecodeError):
            self.propose('read_file', path='binary')

    def test_schema_extra_arguments_and_credentials_in_command_rejected(self):
        self.plan()
        with self.assertRaises(ValueError):
            self.propose('read_file', path='a.txt', approved=True)
        with self.assertRaises(PermissionError):
            self.propose('run_command', command='echo sk-secret12345678', cwd='.')


class BoundaryTests(unittest.TestCase):
    def test_portable_path_aliases_and_traversal(self):
        for value in ['../x', '/tmp/x', 'a/../b', 'a//b', 'C:/x', 'C:x', '\\\\server\\x', 'a\\b', 'x:stream',
                      'NUL', 'COM1.txt', 'AGENTS~1.MD', 'a.', 'a ', 'a/./b', 'a\x00', 'e\u0301.txt']:
            with self.subTest(path=repr(value)), self.assertRaises((ValueError, PermissionError)):
                relative_path(value)

    def test_protected_patterns_casefold_and_nested_paths(self):
        for value in ['AGENTS.md', 'nested/agents.MD', '.git/config', 'nested/.git', '.agents/skills/x/SKILL.md']:
            self.assertEqual(category(value), 'protected')
        for value in ['.env', 'x/.ENV.local', 'x/cert.KEY', '.aws/config', '.ssh/id', '.npmrc']:
            self.assertEqual(category(value), 'secret')

    def test_symlink_parent_target_and_hardlink_cannot_escape(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            root = Path(root)
            (Path(outside) / 'secret').write_text('outside')
            (root / 'link').symlink_to(outside, target_is_directory=True)
            (root / 'file').symlink_to(Path(outside) / 'secret')
            (root / 'regular').write_text('inside')
            os.link(root / 'regular', root / 'hard')
            for value in ['link/secret', 'file', 'hard']:
                with self.subTest(path=value), self.assertRaises(PermissionError):
                    host_boundary(root, value)
                with self.assertRaises((ValueError, OSError)):
                    perform({'op': 'inspect', 'path': value}, str(root))

    def test_container_worker_independently_rejects_outside_paths(self):
        with tempfile.TemporaryDirectory() as root:
            for value in ['../outside', '/etc/passwd', 'x/../../etc/passwd', 'C:/x']:
                with self.subTest(path=value), self.assertRaises(ValueError):
                    perform({'op': 'inspect', 'path': value}, root)

    def test_worker_detects_changed_file_and_bounds_listing(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'a'
            path.write_text('new')
            with self.assertRaises(ValueError):
                perform({'op': 'write', 'path': 'a', 'content': 'replacement', 'exists': True,
                         'expected': hashlib.sha256(b'old').hexdigest()}, root)
            self.assertEqual(path.read_text(), 'new')
            for index in range(205):
                (Path(root) / f'f{index}').touch()
            listing = perform({'op': 'list', 'path': '.'}, root)
            self.assertTrue(listing['truncated'])
            self.assertEqual(len(listing['entries']), 200)

    def test_host_reparse_point_is_rejected_even_when_not_a_linux_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            reparse = SimpleNamespace(st_mode=0o040755, st_nlink=1, st_file_attributes=0x400)
            with patch.object(Path, 'lstat', return_value=reparse), self.assertRaises(PermissionError):
                host_boundary(root, 'junction/file')

    def test_command_bootstrap_does_not_follow_linked_cwd(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            (Path(root) / 'link').symlink_to(outside, target_is_directory=True)
            previous = os.open('.', os.O_RDONLY | os.O_DIRECTORY)
            try:
                with self.assertRaises(OSError):
                    enter('link', root)
                enter('.', root)
                self.assertEqual(Path.cwd(), Path(root))
            finally:
                os.fchdir(previous)
                os.close(previous)


class GatewayTests(unittest.TestCase):
    def test_terminal_constructs_docker_exec_and_passes_command_over_stdin(self):
        class Projects:
            def __init__(self):
                self.calls = []

            def run(self, argv, **kwargs):
                self.calls.append((argv, kwargs))
                return Result(0, 'bounded result', '')

        projects = Projects()
        gateway = ContainerGateway(projects)
        with tempfile.TemporaryDirectory() as root:
            with patch.object(gateway, 'check', return_value=Path(root)):
                result = gateway.terminal('project', 'echo hello; printf world', '.')
        argv, kwargs = projects.calls[0]
        self.assertEqual(argv[:3], ['docker', 'exec', '-i'])
        self.assertIn('codix-project', argv)
        self.assertEqual(json.loads(kwargs['input_bytes']), {'command': 'echo hello; printf world', 'cwd': '.'})
        self.assertNotIn('echo hello; printf world', argv)
        self.assertEqual(kwargs['timeout'], 120)
        self.assertEqual(result.stdout, 'bounded result')
