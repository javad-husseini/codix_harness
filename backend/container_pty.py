"""Trusted Linux-only PTY supervisor. Transport is private NDJSON over docker exec.

Never imported/executed on the Windows host. Only approved input reaches its stdin.
"""
import base64
import ctypes
import fcntl
import json
import os
import pty
import selectors
import signal
import struct
import sys
import termios
import time


def emit(kind, **values):
    print(json.dumps({'type': kind, **values}), flush=True)


def descendants():
    """Subreaper ownership includes double-forked children, never sibling sessions."""
    records = {}
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        try:
            with open('/proc/' + name + '/stat') as stream:
                fields = stream.read().rsplit(') ', 1)[1].split()
            records[int(name)] = (int(fields[1]), fields[19])  # ppid, starttime
        except (OSError, ValueError, IndexError):
            continue
    owned, parents = {}, {os.getpid()}
    while True:
        found = {pid: start for pid, (parent, start) in records.items() if parent in parents and pid not in owned}
        if not found:
            break
        owned.update(found)
        parents.update(found)
    return owned


def cleanup():
    for sig in (signal.SIGTERM, signal.SIGKILL, signal.SIGKILL):
        for pid, start in descendants().items():
            try:
                with open(f'/proc/{pid}/stat') as stream:
                    current = stream.read().rsplit(') ', 1)[1].split()[19]
                if current == start:
                    os.kill(pid, sig)
            except (OSError, ValueError, IndexError):
                pass
        time.sleep(.08)
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break


def main():
    boot = json.loads(sys.stdin.buffer.readline(16384))
    if boot.get('op') != 'open' or not 20 <= boot.get('cols', 0) <= 300 or not 5 <= boot.get('rows', 0) <= 120:
        raise ValueError('Invalid terminal geometry')
    # Prevent orphaned/background jobs from escaping cleanup when this tab closes.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise RuntimeError('Subreaper unavailable')
    root = boot.get('root', '/workspace')
    # root is supplied by trusted control-plane code (production always /workspace).
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.fchdir(fd)
    os.close(fd)
    pid, master = pty.fork()
    if pid == 0:
        env = {key: value for key, value in os.environ.items()
               if not any(part in key.upper() for part in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL'))
               and key not in ('ENV', 'BASH_ENV', 'PROMPT_COMMAND', 'PS1', 'PS2', 'SHELLOPTS', 'BASHOPTS', 'CDPATH')}
        env.update(TERM='xterm-256color', PS1='codix$ ', PS2='> ')
        os.execve('/bin/sh', ['/bin/sh', '-i'], env)
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', boot['rows'], boot['cols'], 0, 0))
    os.set_blocking(master, False)
    selector = selectors.DefaultSelector()
    selector.register(master, selectors.EVENT_READ)
    selector.register(0, selectors.EVENT_READ)
    buffer, outgoing, closed, code = b'', b'', False, None
    emit('ready')
    def terminate(_number, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    try:
        while not closed:
            for key, events in selector.select(.1):
                if key.fd == master:
                    if events & selectors.EVENT_WRITE and outgoing:
                        try:
                            outgoing = outgoing[os.write(master, outgoing):]
                        except BlockingIOError:
                            pass
                        selector.modify(master, selectors.EVENT_READ | (selectors.EVENT_WRITE if outgoing else 0))
                    if not events & selectors.EVENT_READ:
                        continue
                    try:
                        data = os.read(master, 4096)
                    except BlockingIOError:
                        continue
                    except OSError:
                        data = b''
                    if not data:
                        closed = True
                        break
                    emit('output', data=base64.b64encode(data).decode('ascii'))
                else:
                    data = os.read(0, 8192)
                    if not data:
                        closed = True
                        break
                    buffer += data
                    if len(buffer) > 32768:
                        raise ValueError('Oversized control frame')
                    while b'\n' in buffer:
                        raw, buffer = buffer.split(b'\n', 1)
                        request = json.loads(raw)
                        operation = request.get('op')
                        if operation == 'input':
                            text = request.get('text')
                            if (not isinstance(text, str) or len(text.encode('utf-8')) > 4096
                                    or any(ord(char) < 32 and char not in '\n\t' for char in text)):
                                raise ValueError('Invalid input')
                            outgoing += (text + '\n').encode('utf-8')
                            if len(outgoing) > 16384:
                                raise ValueError('Input queue full')
                            selector.modify(master, selectors.EVENT_READ | selectors.EVENT_WRITE)
                        elif operation == 'interrupt':
                            outgoing = b'\x03'
                            selector.modify(master, selectors.EVENT_READ | selectors.EVENT_WRITE)
                        elif operation == 'resize':
                            cols, rows = request.get('cols'), request.get('rows')
                            if type(cols) is not int or type(rows) is not int or not 20 <= cols <= 300 or not 5 <= rows <= 120:
                                raise ValueError('Invalid resize')
                            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
                        elif operation == 'close':
                            closed = True
                        else:
                            raise ValueError('Invalid control operation')
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                code, closed = os.waitstatus_to_exitcode(status), True
    finally:
        selector.close()
        cleanup()
        # Drain output that was already written before shell exit/cleanup.
        for _ in range(64):
            try:
                remaining = os.read(master, 4096)
            except OSError:
                break
            if not remaining:
                break
            emit('output', data=base64.b64encode(remaining).decode('ascii'))
        os.close(master)
        emit('exit', code=code)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # No paths, user input, environment or raw errors enter the protocol.
        emit('error')
        raise SystemExit(1)
