"""Project-bound PTYs; only one-use, native-approved input reaches a shell."""
import base64
import codecs
from collections import deque
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
import time

from backend.policy import command, redact


class StreamRedactor:
    """Keep incomplete secret prefixes across transport frames; never log raw frames."""
    def __init__(self):
        self.pending = ''
        self.hidden = False
        self.prefixes = ['api_key', 'apikey', 'password', 'secret', 'token', 'authorization', 'sk-', 'aa-', '-----BEGIN']
        self.values = [v for k, v in os.environ.items() if len(v) >= 6 and
                       any(part in k.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))]

    def feed(self, text, final=False):
        text = self.pending + text
        self.pending = ''
        for value in sorted(self.values, key=len, reverse=True):
            text = text.replace(value, '[REDACTED]')
        result = ''
        while text:
            if self.hidden:
                end = text.find('\n')
                if end < 0:
                    return result
                text, self.hidden = text[end:], False
            # A labelled value is suppressed to EOL, including subsequent frames.
            match = re.search(r'(?:api_?key|password|secret|token|authorization)\s*[:=]|(?:sk-|aa-)|-----BEGIN', text, re.I)
            if match:
                prefix, text = text[:match.start()], text[match.end():]
                result += redact(prefix) + '[REDACTED]'
                self.hidden = True
                continue
            keep = 0
            if not final:
                for candidate in self.values + self.prefixes:
                    for length in range(1, min(len(candidate), len(text) + 1)):
                        if text[-length:].lower() == candidate[:length].lower():
                            keep = max(keep, length)
                # A complete label followed by whitespace may acquire ':' in the next frame.
                partial = re.search(r'(?:api_?key|password|secret|token|authorization)\s*$', text, re.I)
                if partial:
                    if len(text) - partial.start() > 128:
                        self.hidden = True
                        return result + redact(text[:partial.start()]) + '[REDACTED]'
                    keep = max(keep, len(text) - partial.start())
            if keep:
                self.pending, text = text[-keep:], text[:-keep]
            result += redact(text)
            break
        return result


class PtySession:
    LIMIT = 131072

    def __init__(self, process, root='/workspace'):
        self.process = process
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.chunks = deque()
        self.size = self.sequence = 0
        self.state, self.code = 'starting', None
        self.cols, self.rows = 80, 24
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.redactor = StreamRedactor()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._discard_errors, daemon=True).start()
        self.send({'op': 'open', 'cols': 80, 'rows': 24, 'root': root})
        if not self.ready.wait(8) or self.state != 'running':
            self.close()
            raise RuntimeError('Container PTY could not start; no host fallback.')

    def _append(self, text):
        if not text:
            return
        with self.lock:
            self.sequence += 1
            self.chunks.append((self.sequence, text))
            self.size += len(text)
            while self.size > self.LIMIT and self.chunks:
                self.size -= len(self.chunks.popleft()[1])

    def _read(self):
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            while raw := self.process.stdout.readline(65537):
                if len(raw) > 65536 or not raw.endswith(b'\n'):
                    raise ValueError('Invalid worker frame')
                item = json.loads(raw)
                if item['type'] == 'ready':
                    self.state = 'running'
                    self.ready.set()
                elif item['type'] == 'output':
                    data = base64.b64decode(item['data'], validate=True)
                    if len(data) > 4096:
                        raise ValueError('Invalid output frame')
                    self._append(self.redactor.feed(decoder.decode(data)))
                elif item['type'] == 'exit':
                    self.code, self.state = item.get('code'), 'exited'
                else:
                    raise ValueError('Worker error')
            self._append(self.redactor.feed(decoder.decode(b'', final=True), final=True))
            if self.state != 'exited':
                self.state = 'error'
        except Exception:
            self.state = 'error'
        finally:
            self.ready.set()
            self.finished.set()
            self.process.stdout.close()

    def _discard_errors(self):
        # Docker/worker stderr may contain environment-derived data; never forward/log it.
        while self.process.stderr.read(4096):
            pass
        self.process.stderr.close()

    def send(self, frame):
        with self.write_lock:
            try:
                self.process.stdin.write((json.dumps(frame) + '\n').encode())
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise RuntimeError('Terminal session is no longer available.') from None

    def poll(self, cursor):
        with self.lock:
            chunks = [(n, t) for n, t in self.chunks if n > cursor]
            # Each poll is bounded; cursor advances only through delivered output.
            batch, size = [], 0
            for n, text in chunks:
                if size + len(text) > 32768 and batch:
                    break
                batch.append((n, text))
                size += len(text)
            return {'output': ''.join(t for _, t in batch),
                    'cursor': batch[-1][0] if batch else max(cursor, self.sequence),
                    'dropped': bool(self.chunks and cursor < self.chunks[0][0] - 1),
                    'state': self.state, 'exit_code': self.code, 'cols': self.cols, 'rows': self.rows}

    def close(self):
        if self.process.poll() is None:
            try:
                self.send({'op': 'close'})
            except RuntimeError:
                pass
            with self.write_lock:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                # Never stop a container or a sibling session to close a tab.
                raise RuntimeError('Terminal cleanup was not confirmed. Keep this tab and retry closing it.') from None
        self.finished.wait(1)
        if self.state != 'exited':
            raise RuntimeError('Terminal cleanup was not confirmed by its supervisor.')


class TerminalService:
    def __init__(self, gateway, launcher=None, clock=time.monotonic):
        self.gateway, self.launcher, self.clock = gateway, launcher, clock
        self.sessions, self.pending = {}, {}
        self.worker = Path(__file__).with_name('container_pty.py').read_text(encoding='utf-8')

    def _target(self, project_id):
        self.gateway.check(project_id)
        result = self.gateway.projects.run(['docker', 'container', 'inspect', f'codix-{project_id}'])
        if result.code:
            raise RuntimeError('Project container is unavailable.')
        data = json.loads(result.stdout)[0]
        root, image = self.gateway.projects.projects[project_id]
        self.gateway.projects.validate_container(data, root, project_id, image)
        if not data.get('State', {}).get('Running') or not re.fullmatch('[a-f0-9]{64}', data.get('Id', '')):
            raise PermissionError('Invalid running project container.')
        return data['Id']

    def _get(self, project_id, session_id):
        entry = self.sessions.get(session_id)
        if not entry or entry['project_id'] != project_id:
            raise PermissionError('Terminal does not belong to this project.')
        return entry

    def propose(self, project_id, action, session_id, text):
        if action not in ('open', 'input') or not isinstance(session_id, str) or not isinstance(text, str):
            raise ValueError('Invalid terminal operation.')
        target = self._target(project_id)
        if action == 'open':
            if session_id or text or len(self.sessions) >= 4:
                raise ValueError('Close a terminal before opening another (maximum four).')
            detail = 'Start /bin/sh -i in /workspace. Each complete input will require a separate native approval.'
        else:
            entry = self._get(project_id, session_id)
            if entry['target'] != target or entry['session'].state != 'running':
                raise PermissionError('Terminal container changed or session ended.')
            if text.strip():
                command(text)
            if (len(text.encode('utf-8')) > 4096 or any(ord(c) < 32 and c not in '\n\t' for c in text)
                    or any(c in text for c in '\x7f\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')):
                raise ValueError('Input must be at most 4096 UTF-8 bytes without control characters.')
            detail = ('Send this exact input followed by Enter to this persistent shell/program. '
                      'It can change/delete protected files, install dependencies and use the network inside the container. '
                      'Shell state and current directory may differ from the initial /workspace. '
                      'No additional host mounts are authorized.\n\n' + (text if text else '[empty line followed by Enter]'))
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if v['expires'] > now}
        if len(self.pending) >= 8:
            raise PermissionError('Too many pending terminal approvals.')
        ticket = secrets.token_urlsafe(32)
        self.pending[ticket] = dict(project_id=project_id, action=action, session_id=session_id,
                                    text=text, target=target, expires=now + 300)
        return {'ticket': ticket, 'detail': detail, 'approval_required': True}

    def execute(self, project_id, ticket, approved):
        proposal = self.pending.pop(ticket, None)
        if not proposal or proposal['project_id'] != project_id or proposal['expires'] <= self.clock() or approved is not True:
            raise PermissionError('Terminal operation denied, expired or already consumed.')
        if self._target(project_id) != proposal['target']:
            raise PermissionError('Project container changed after approval.')
        if proposal['action'] == 'input':
            entry = self._get(project_id, proposal['session_id'])
            if entry['target'] != proposal['target'] or entry['session'].state != 'running':
                raise PermissionError('Terminal session ended.')
            entry['session'].send({'op': 'input', 'text': proposal['text']})
            return {'accepted': True}
        if len(self.sessions) >= 4:
            raise ValueError('Maximum four terminals.')
        if self.launcher:
            process, root = self.launcher(proposal['target'], self.worker)
        else:
            executable = shutil.which('docker')
            if not executable and os.name == 'nt':
                executable = str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Docker/Docker/resources/bin/docker.exe')
            if not executable:
                raise RuntimeError('Docker is required. No host shell fallback.')
            process = subprocess.Popen([executable, 'exec', '-i', '--workdir', '/workspace', proposal['target'],
                                        'python3', '-I', '-u', '-c', self.worker],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            root = '/workspace'
        session = PtySession(process, root)
        session_id = secrets.token_hex(16)
        self.sessions[session_id] = dict(project_id=project_id, target=proposal['target'], session=session)
        return {'session_id': session_id, 'state': session.state}

    def control(self, project_id, session_id, action, **args):
        entry = self._get(project_id, session_id)
        session = entry['session']
        if action == 'poll':
            cursor = args.get('cursor')
            if type(cursor) is not int or cursor < 0 or cursor > session.sequence:
                raise ValueError('Invalid output cursor.')
            return session.poll(cursor)
        if action == 'close':
            session.close()
            self.sessions.pop(session_id, None)
            return {'closed': True}
        if session.state != 'running':
            raise PermissionError('Terminal session ended.')
        if action == 'resize':
            cols, rows = args.get('cols'), args.get('rows')
            if type(cols) is not int or type(rows) is not int or not 20 <= cols <= 300 or not 5 <= rows <= 120:
                raise ValueError('Invalid terminal dimensions.')
            session.send({'op': 'resize', 'cols': cols, 'rows': rows})
            session.cols, session.rows = cols, rows
        elif action == 'interrupt':
            session.send({'op': 'interrupt'})
        else:
            raise ValueError('Unknown terminal control.')
        return {'accepted': True}

    def close_project(self, project_id):
        for session_id, entry in list(self.sessions.items()):
            if entry['project_id'] == project_id:
                self.control(project_id, session_id, 'close')
        self.pending = {k: v for k, v in self.pending.items() if v['project_id'] != project_id}
        return {'closed': True}

    def close_all(self):
        failures = []
        for session_id, entry in list(self.sessions.items()):
            try:
                self.control(entry['project_id'], session_id, 'close')
            except RuntimeError:
                failures.append(session_id)
        if failures:
            raise RuntimeError('Some terminal cleanup could not be confirmed.')
