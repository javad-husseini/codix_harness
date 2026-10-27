"""File boundaries and real PTY acceptance; these tests run only inside Docker."""
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.container_files import perform
from backend.file_viewer import FileViewer
from backend.policy import FILE_LIMIT
from backend.server import make_server
from backend.terminals import PtySession, StreamRedactor, TerminalService
from backend.tools import ToolService
from tests.test_tools import LocalGateway


class FileViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tools = ToolService(LocalGateway(self.root))
        self.viewer = FileViewer(self.tools.gateway)

    def tearDown(self):
        self.temp.cleanup()

    def test_text_bom_empty_binary_and_size(self):
        for name, content, status in [('hello.py', 'print("سلام")\n'.encode(), 'text'),
                                      ('bom.txt', b'\xef\xbb\xbfhello', 'text'), ('empty', b'', 'text'),
                                      ('binary.dat', b'hello\0world', 'binary'), ('image', b'\xff\xfe', 'binary'),
                                      ('large', b'x' * (FILE_LIMIT + 1), 'too_large')]:
            (self.root / name).write_bytes(content)
            value = self.viewer.read('project', name)
            self.assertEqual(value['status'], status)
            self.assertEqual(value['size'], len(content))
            self.assertEqual('content' in value, status == 'text')
        self.assertEqual(self.viewer.read('project', 'bom.txt')['content'], 'hello')

    def test_secret_redaction_and_no_approval_invalidation(self):
        (self.root / 'hello').write_text('api_key=private-value\nnormal\n')
        self.tools.execute('project', self.tools.propose('project', 'set_plan', {'steps': ['Review']})['ticket'])
        proposal = self.tools.propose('project', 'run_command', {'command': 'pwd', 'cwd': '.'})
        self.assertNotIn('private-value', self.viewer.read('project', 'hello')['content'])
        self.assertIn(proposal['ticket'], self.tools.pending)
        self.tools.execute('project', proposal['ticket'], True)

    def test_missing_secret_traversal_symlink_and_hardlink(self):
        (self.root / 'normal').write_text('text')
        (self.root / '.env').write_text('secret')
        (self.root / 'link').symlink_to(self.root / 'normal')
        os.link(self.root / 'normal', self.root / 'hard')
        for path in ['../outside', '/etc/passwd', 'missing', '.env', 'link', 'hard']:
            with self.subTest(path=path), self.assertRaises((PermissionError, ValueError, OSError)):
                self.viewer.read('project', path)
        # Independent worker boundary, even if the host check were bypassed.
        with self.assertRaises(OSError):
            perform({'op': 'view', 'path': 'link'}, str(self.root))


class LocalTerminals(TerminalService):
    """Explicit test injection: real PTYs in the Docker test container only."""
    def __init__(self, root, clock=time.monotonic):
        self.target = 'a' * 64
        self.launch_count = 0
        def launch(_target, worker):
            self.launch_count += 1
            return (subprocess.Popen([sys.executable, '-I', '-u', '-c', worker],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE), str(root))
        super().__init__(LocalGateway(root), launch, clock)

    def _target(self, project_id):
        self.gateway.check(project_id)
        return self.target


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'sub').mkdir()
        self.now = 0
        self.service = LocalTerminals(self.root, lambda: self.now)

    def tearDown(self):
        self.service.close_all()
        self.temp.cleanup()

    def open(self):
        proposal = self.service.propose('project', 'open', '', '')
        return self.service.execute('project', proposal['ticket'], True)['session_id']

    def send(self, sid, text):
        proposal = self.service.propose('project', 'input', sid, text)
        return self.service.execute('project', proposal['ticket'], True)

    def output(self, sid):
        return self.service.control('project', sid, 'poll', cursor=0)['output']

    def until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.03)
        self.fail('Real PTY acceptance condition timed out')

    def test_native_approval_deny_expiry_replay_and_container_binding(self):
        proposal = self.service.propose('project', 'open', '', '')
        self.assertEqual(self.service.launch_count, 0)
        with self.assertRaises(PermissionError):
            self.service.execute('project', proposal['ticket'], False)
        with self.assertRaises(PermissionError):
            self.service.execute('project', proposal['ticket'], True)
        sid = self.open()
        proposal = self.service.propose('project', 'input', sid, 'touch unapproved')
        time.sleep(.1)
        self.assertFalse((self.root / 'unapproved').exists())
        with self.assertRaises(PermissionError):
            self.service.execute('project', proposal['ticket'], False)
        proposal = self.service.propose('project', 'input', sid, 'touch expired')
        self.now = 301
        with self.assertRaises(PermissionError):
            self.service.execute('project', proposal['ticket'], True)
        proposal = self.service.propose('project', 'input', sid, 'touch replaced')
        self.service.target = 'b' * 64
        with self.assertRaises(PermissionError):
            self.service.execute('project', proposal['ticket'], True)
        self.assertFalse((self.root / 'expired').exists())
        self.assertFalse((self.root / 'replaced').exists())
        with self.assertRaises(PermissionError):
            self.service.control('other', sid, 'poll', cursor=0)
        for bad in ['echo x\rhidden', '\x1b[2Jrm x', 'x\x7f', '\x03', '\u202edanger', 'é' * 3000]:
            with self.assertRaises((ValueError, PermissionError)):
                self.service.propose('project', 'input', sid, bad)

    def test_independent_shell_cwd_live_output_interrupt_resize_and_cleanup(self):
        a, b = self.open(), self.open()
        self.send(a, 'cd sub; export OWN_STATE=alpha')
        self.send(b, 'printf "B_CWD:%s B_STATE:%s\\n" "$PWD" "${OWN_STATE-unset}"')
        self.send(a, 'printf "A_CWD:%s A_STATE:%s\\n" "$PWD" "$OWN_STATE"')
        self.until(lambda: f'A_CWD:{self.root}/sub A_STATE:alpha' in self.output(a))
        self.until(lambda: f'B_CWD:{self.root} B_STATE:unset' in self.output(b))
        self.send(a, 'printf "LIVE_MARK\\n"; sleep 20; touch should-not-exist')
        self.until(lambda: '\r\nLIVE_MARK\r\n' in self.output(a))
        self.assertFalse((self.root / 'sub/should-not-exist').exists())
        prompts = self.output(a).count('codix$ ')
        self.service.control('project', a, 'interrupt')
        self.until(lambda: self.output(a).count('codix$ ') > prompts)
        self.send(a, 'printf "AFTER_INTERRUPT\\n"')
        self.until(lambda: '\r\nAFTER_INTERRUPT\r\n' in self.output(a))
        self.service.control('project', a, 'resize', cols=91, rows=17)
        self.send(a, 'stty size')
        self.until(lambda: '17 91' in self.output(a))
        self.send(a, 'sleep 60 & echo CHILD_PID:$!')
        self.until(lambda: re.search(r'CHILD_PID:(\d+)', self.output(a)))
        child = int(re.search(r'CHILD_PID:(\d+)', self.output(a))[1])
        self.service.control('project', a, 'close')
        self.assertFalse(Path(f'/proc/{child}').exists(), 'Closing must reap background descendants')
        self.send(b, 'printf "SIBLING_ALIVE\\n"')
        self.until(lambda: '\r\nSIBLING_ALIVE\r\n' in self.output(b))
        self.assertEqual(self.service.gateway.stop_count, 0)
        self.service.close_project('project')
        self.assertEqual(self.service.sessions, {})

    def test_output_bounded_and_eof_cleanup(self):
        sid = self.open()
        session = self.service.sessions[sid]['session']
        self.send(sid, 'head -c 240000 /dev/zero | tr "\\0" x; printf "\\nBOUND_DONE\\n"')
        self.until(lambda: 'BOUND_DONE\r\n' in self.output(sid) or session.sequence > 45)
        self.until(lambda: session.sequence > 45)
        self.assertLessEqual(session.size, session.LIMIT)
        self.assertTrue(session.poll(0)['dropped'])
        # Parent transport EOF is also a close, not an orphaned shell.
        session.process.stdin.close()
        session.process.wait(timeout=5)
        self.until(lambda: session.state == 'exited')

    def test_stream_redaction_across_frames(self):
        with patch.dict(os.environ, {'TEST_API_KEY': 'split-private-value'}):
            for pieces in [('before split-pri', 'vate-value after\n'), ('api_', 'key=hidden', '-tail', '\nOK'), ('sk-', 'private', '\nOK')]:
                redactor = StreamRedactor()
                result = ''.join(redactor.feed(piece) for piece in pieces) + redactor.feed('', final=True)
                self.assertNotIn('split-private-value', result)
                self.assertNotIn('hidden', result)
                self.assertNotIn('private', result)
        redactor = StreamRedactor()
        for _ in range(20):
            redactor.feed('token' + ' ' * 4096)
        self.assertLess(len(redactor.pending), 129)

    def test_interactive_program_input_and_empty_enter(self):
        sid = self.open()
        self.send(sid, 'printf "INPUT_PROMPT\\n"; read -r VALUE; printf "READ_VALUE:<%s>\\n" "$VALUE"')
        self.until(lambda: 'INPUT_PROMPT\r\n' in self.output(sid))
        self.send(sid, '')
        self.until(lambda: 'READ_VALUE:<>\r\n' in self.output(sid))


class WorkspaceApiTests(unittest.TestCase):
    def test_poll_resize_and_view_do_not_conflict_with_an_input_proposal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'hello').write_text('real text')
            terminals = LocalTerminals(root)
            sid = terminals.execute('project', terminals.propose('project', 'open', '', '')['ticket'], True)['session_id']
            entered, release = threading.Event(), threading.Event()
            original = terminals._target
            def slow_target(project_id):
                entered.set()
                release.wait(4)
                return original(project_id)
            terminals._target = slow_target
            server = make_server('a' * 64, 0, tool_service=ToolService(LocalGateway(root)), terminal_service=terminals)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def post(path, body):
                client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=8)
                client.request('POST', path, json.dumps(body), {'Authorization': 'Bearer ' + 'a' * 64})
                response = client.getresponse()
                result = response.status, json.loads(response.read())
                client.close()
                return result
            base = {'project_id': 'project', 'session_id': sid}
            proposals = []
            proposer = threading.Thread(target=lambda: proposals.append(post('/terminals/propose', {**base, 'action': 'input', 'text': 'touch unapproved'})))
            try:
                proposer.start()
                self.assertTrue(entered.wait(3))
                self.assertEqual(post('/terminals/poll', {**base, 'cursor': 0})[0], 200)
                self.assertEqual(post('/terminals/resize', {**base, 'cols': 90, 'rows': 20})[0], 200)
                self.assertEqual(post('/files/view', {'project_id': 'project', 'path': 'hello'})[1]['content'], 'real text')
                self.assertFalse((root / 'unapproved').exists())
                release.set()
                proposer.join(5)
                self.assertEqual(proposals[0][0], 200)
            finally:
                release.set()
                proposer.join(5)
                server.shutdown()
                server.server_close()
                thread.join()

    def test_read_and_controls_during_hitl_input_blocked_and_shutdown_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'hello').write_text('hello')
            terminals = LocalTerminals(root)
            ticket = terminals.propose('project', 'open', '', '')['ticket']
            sid = terminals.execute('project', ticket, True)['session_id']
            class Tasks:
                def active(self):
                    return True
            server = make_server('a' * 64, 0, tool_service=ToolService(LocalGateway(root)), task_manager=Tasks(), terminal_service=terminals)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def post(path, body):
                client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                client.request('POST', path, json.dumps(body), {'Authorization': 'Bearer ' + 'a' * 64})
                response = client.getresponse()
                result = response.status, json.loads(response.read())
                client.close()
                return result
            try:
                base = {'project_id': 'project', 'session_id': sid}
                self.assertEqual(post('/files/view', {'project_id': 'project', 'path': 'hello'})[1]['content'], 'hello')
                self.assertEqual(post('/terminals/propose', {**base, 'action': 'input', 'text': 'touch bypass'})[0], 403)
                self.assertEqual(post('/terminals/poll', {**base, 'cursor': 0})[0], 200)
                self.assertEqual(post('/terminals/interrupt', base)[0], 200)
                self.assertEqual(post('/terminals/resize', {**base, 'cols': 80, 'rows': 20})[0], 200)
                self.assertFalse((root / 'bypass').exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            self.assertEqual(terminals.sessions, {})
