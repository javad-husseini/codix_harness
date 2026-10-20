"""Trusted Linux file worker, supplied to Python inside the selected project container.

This module is also exercised directly in Docker tests. No host execution fallback exists.
"""
import hashlib
import json
import os
import secrets
import stat
import sys

LIMIT = 32768
NOFOLLOW = os.O_NOFOLLOW
DIRECTORY = os.O_DIRECTORY


def snapshot(fd, leaf):
    try:
        target = os.open(leaf, os.O_RDONLY | NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return {'exists': False, 'sha256': None}
    try:
        info = os.fstat(target)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Only ordinary, single-link files are supported.')
        if info.st_size > LIMIT:
            raise ValueError('File exceeds the 32 KiB tool limit.')
        data = os.read(target, LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('File grew beyond the tool limit.')
        return {'exists': True, 'sha256': hashlib.sha256(data).hexdigest(),
                'content': data.decode('utf-8'), 'mode': stat.S_IMODE(info.st_mode)}
    finally:
        os.close(target)


def perform(request, root='/workspace'):
    op, path = request['op'], request['path']
    # Independently validate even if a caller bypasses the host policy.
    if not isinstance(path, str) or (path != '.' and (path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')))) or '\\' in path or ':' in path:
        raise ValueError('Unsafe path.')
    fd = os.open(root, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    try:
        parts = [] if path == '.' else path.split('/')
        parents = parts if op == 'list' else parts[:-1]
        if op != 'list' and not parts:
            raise ValueError('A file path is required.')
        for part in parents:
            next_fd = os.open(part, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if op == 'list':
            # Bound enumeration, including repositories with millions of files.
            items = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    if len(items) >= 200:
                        return {'entries': sorted(items, key=lambda item: item['name']), 'truncated': True}
                    if entry.is_symlink():
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                        continue
                    items.append({'name': entry.name, 'directory': entry.is_dir(follow_symlinks=False)})
            return {'entries': sorted(items, key=lambda item: item['name']), 'truncated': False}
        leaf = parts[-1]
        current = snapshot(fd, leaf)
        if op == 'inspect':
            return current
        if current['sha256'] != request.get('expected') or current['exists'] != request.get('exists'):
            raise ValueError('File changed after preview. Request a new operation.')
        if op == 'delete':
            if not current['exists']:
                raise ValueError('File does not exist.')
            os.unlink(leaf, dir_fd=fd)
            return {'deleted': True}
        if op != 'write':
            raise ValueError('Unknown file operation.')
        content = request['content'].encode('utf-8')
        if len(content) > LIMIT:
            raise ValueError('Content exceeds the 32 KiB tool limit.')
        temporary = '.codix-write-' + secrets.token_hex(16)
        output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(output, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), current.get('mode', 0o644))
            # Recheck after writing temporary content, immediately before replacement.
            latest = snapshot(fd, leaf)
            if latest['sha256'] != current['sha256'] or latest['exists'] != current['exists']:
                raise ValueError('File changed during write.')
            if current['exists']:
                os.replace(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd)
            else:
                # Hardlink creation is atomic and fails if another file appeared at the target.
                os.link(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            return {'written': True, 'sha256': hashlib.sha256(content).hexdigest()}
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(70000)
        result = perform(json.loads(raw))
        print(json.dumps({'ok': True, 'data': result}))
    except Exception:
        # No raw path/content/error text can leak from the container worker.
        print(json.dumps({'ok': False, 'error': 'File operation failed: invalid path, link, changed file, unsupported encoding or size.'}))
        raise SystemExit(1)
