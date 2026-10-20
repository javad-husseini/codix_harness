"""Check the real Docker inspection captured by the host control plane.

Run inside the development container; never mount a Docker socket just to test.
"""
import json
from pathlib import Path
from backend.projects import ProjectManager

data = json.loads(Path('.verification/runtime-inspect.json').read_text(encoding='utf-8-sig'))[0]
source = data['Mounts'][0]['Source']
ProjectManager().validate_container(data, source, 'phase1-runtime', 'codix-project:node22-python312')
assert data['State']['Running'] is True
print('PASS actual Docker container isolation contract and running state')
