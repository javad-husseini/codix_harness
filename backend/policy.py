"""Conservative MVP policy. Decisions are enforced outside model prompts."""
import fnmatch
import os
from pathlib import Path
import re
import stat
import unicodedata

FILE_LIMIT = 32768
OUTPUT_LIMIT = 16384
MAX_COMMAND = 4096
RESERVED = re.compile(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$', re.I)
SECRET_PATTERNS = ('.env', '.env.*', '*.pem', '*.key', '*.dpapi', '.npmrc', '.pypirc', 'credentials.json', 'secrets.*')


def relative_path(value, allow_root=False):
    if allow_root and value == '.':
        return value
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError('Invalid project-relative path.')
    if unicodedata.normalize('NFC', value) != value:
        raise ValueError('Path must use canonical Unicode.')
    parts = value.split('/')
    if len(parts) > 32 or any(not part or part in ('.', '..') for part in parts):
        raise PermissionError('Path traversal or absolute paths are blocked; approval cannot expand the mount.')
    for part in parts:
        if (part.endswith((' ', '.')) or RESERVED.fullmatch(part)
                or any(ord(char) < 32 or char in '\\:<>"|?*~' for char in part)):
            raise PermissionError('Ambiguous Windows paths and device names are blocked.')
    return value


def category(path):
    parts = path.casefold().split('/')
    if any(part in ('.ssh', '.aws') or any(fnmatch.fnmatchcase(part, pattern) for pattern in SECRET_PATTERNS) for part in parts):
        return 'secret'
    if '.git' in parts or 'agents.md' in parts:
        return 'protected'
    if any(parts[index:index + 2] == ['.agents', 'skills'] for index in range(len(parts) - 1)):
        return 'protected'
    return 'normal'


def host_boundary(root, relative):
    """Reject host symlinks/junctions/reparse points, aliases and hardlinks before Docker exec."""
    root = Path(root).resolve(strict=True)
    cursor = root
    for part in ([] if relative == '.' else relative.split('/')):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, 'st_file_attributes', 0) & 0x400
                or stat.S_ISREG(info.st_mode) and info.st_nlink > 1):
            raise PermissionError('Links, junctions, reparse points and hardlinked files are blocked.')
        try:
            cursor.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise PermissionError('Target is outside the project root.') from exc


def redact(value):
    """Defense in depth for recognizable credentials; secret file tools are blocked separately."""
    value = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 6 and re.search(r'key|token|secret|password|credential', name, re.I):
            value = value.replace(secret, '[REDACTED]')
    value = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value)
    value = re.sub(r'(?im)((?:api[_-]?key|password|secret|token|authorization)\s*[:=]\s*)([^\r\n]+)', r'\1[REDACTED]', value)
    value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[REDACTED PRIVATE KEY]', value)
    return value


def command(value):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_COMMAND or '\x00' in value:
        raise ValueError('Command must contain 1–4096 characters without NUL.')
    # Never present a transformed command as if it were the exact approved command.
    if redact(value) != value:
        raise PermissionError('Command appears to contain credentials. Use project-local references instead.')
    return value
