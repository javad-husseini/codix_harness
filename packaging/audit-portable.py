"""Check the final artifact layout, target architecture and secret-file exclusions."""
import hashlib
import json
from pathlib import Path
import struct
import sys

repo = Path(__file__).resolve().parent.parent
product = repo / 'dist' / ('Codix-win32-x64-updated' if '--updated' in sys.argv else 'Codix-win32-x64')
app = product / 'resources' / 'app'
backend = product / 'resources' / 'backend'
for file in [product / 'Codix.exe', backend / 'codix-backend.exe']:
    with file.open('rb') as stream:
        assert stream.read(2) == b'MZ', 'Missing Windows executable header'
        stream.seek(0x3C)
        offset = struct.unpack('<I', stream.read(4))[0]
        stream.seek(offset)
        assert stream.read(4) == b'PE\0\0'
        assert struct.unpack('<H', stream.read(2))[0] == 0x8664, 'Expected Windows x64'
assert {item.name for item in app.iterdir()} == {'desktop', 'out', 'package.json'}
assert json.loads((app / 'package.json').read_text())['main'] == 'desktop/main.cjs'
for relative in ['desktop/main.cjs', 'desktop/preload.cjs', 'out/index.html']:
    assert (app / relative).is_file()
for worker in ['container_files.py', 'container_terminal.py']:
    assert (backend / '_internal' / 'backend' / worker).read_bytes() == (repo / 'backend' / worker).read_bytes()
assert (backend / '_internal' / 'python312.dll').is_file()
assert (product / 'docker' / 'default.Dockerfile').is_file()
for item in product.rglob('*'):
    name = item.name.lower()
    assert not (name in {'.git', '.agents', '.secrets', 'node_modules', '.env'}
                or name.startswith('.env.') or name.endswith('.dpapi')), 'Forbidden artifact file'
digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
assert digest(backend / 'codix-backend.exe') == digest(repo / 'runtime' / 'codix-backend' / 'codix-backend.exe')
print('PASS portable audit: Windows x64 binaries, final backend identity, bundled workers/UI and no credential files.')
