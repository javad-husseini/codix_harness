"""Trusted cwd bootstrap; executed only inside Docker after an approval ticket."""
import json
import os
import sys


def enter(cwd, root='/workspace'):
    if not isinstance(cwd, str) or (cwd != '.' and any(part in ('', '.', '..') for part in cwd.split('/'))) or '\\' in cwd or ':' in cwd:
        raise ValueError('Unsafe working directory')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in ([] if cwd == '.' else cwd.split('/')):
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        os.fchdir(fd)
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        request = json.loads(sys.stdin.buffer.read(32768))
        enter(request['cwd'])
        text = request['command']
        if not isinstance(text, str) or not 0 < len(text) <= 4096 or '\x00' in text:
            raise ValueError('Invalid command')
    except Exception:
        print('Command blocked: invalid or linked working directory.', file=sys.stderr)
        raise SystemExit(125)
    os.execv('/bin/sh', ['/bin/sh', '-c', text])
