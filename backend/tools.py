"""Model-ready tool service with project/plan-bound, one-use approval tickets."""
import copy
import difflib
import hashlib
import json
from pathlib import Path
import secrets
import time

from backend.policy import (FILE_LIMIT, OUTPUT_LIMIT, category, command, host_boundary,
                            redact, relative_path)

TOOL_SCHEMAS = [
    {'name': 'list_files', 'description': 'List at most 200 entries of a project directory.', 'arguments': ['path']},
    {'name': 'read_file', 'description': 'Read a UTF-8 project file up to 32 KiB; secret targets are blocked.', 'arguments': ['path']},
    {'name': 'create_file', 'description': 'Create a UTF-8 file after a plan exists.', 'arguments': ['path', 'content']},
    {'name': 'edit_file', 'description': 'Replace an existing file after a plan exists.', 'arguments': ['path', 'content']},
    {'name': 'delete_file', 'description': 'Delete one file after specific human approval.', 'arguments': ['path']},
    {'name': 'run_command', 'description': 'Run an exact shell command in Docker after human approval.', 'arguments': ['command', 'cwd']},
    {'name': 'set_plan', 'description': 'Record ordered plan steps. Replacing a plan needs approval.', 'arguments': ['steps']},
]
SCHEMAS = {item['name']: set(item['arguments']) for item in TOOL_SCHEMAS}
for _tool in TOOL_SCHEMAS:
    _tool['parameters'] = {'type': 'object', 'additionalProperties': False,
                           'required': _tool['arguments'], 'properties': {
                               key: ({'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 20}
                                     if key == 'steps' else {'type': 'string'}) for key in _tool['arguments']}}
MUTATING = {'create_file', 'edit_file', 'delete_file', 'run_command'}


class ContainerGateway:
    def __init__(self, projects):
        self.projects = projects
        # Trusted application source, not a project Skill or project-supplied script.
        # Workers target Linux containers; never import their OS-specific code on Windows.
        self.worker = Path(__file__).with_name('container_files.py').read_text(encoding='utf-8')
        self.bootstrap = Path(__file__).with_name('container_terminal.py').read_text(encoding='utf-8')

    def check(self, project_id):
        if project_id not in self.projects.projects:
            raise PermissionError('Prepare the selected project first.')
        root, image = self.projects.projects[project_id]
        result = self.projects.run(['docker', 'container', 'inspect', f'codix-{project_id}'])
        if result.code:
            raise RuntimeError('Project container is unavailable.')
        data = json.loads(result.stdout)[0]
        self.projects.validate_container(data, root, project_id, image)
        if not data.get('State', {}).get('Running'):
            raise RuntimeError('Project container is not running.')
        return root

    def file(self, project_id, request):
        root = self.check(project_id)
        host_boundary(root, request['path'])
        result = self.projects.run(['docker', 'exec', '-i', '--workdir', '/workspace',
                                    f'codix-{project_id}', 'python3', '-I', '-c', self.worker],
                                   input_bytes=json.dumps(request).encode(), limit=250000)
        try:
            response = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError('Container file worker unavailable. Python 3 with Linux no-follow file APIs is required; no host fallback.') from exc
        if result.code or not response.get('ok'):
            raise PermissionError('File operation blocked: invalid path, link, changed file, encoding or size.')
        return response['data']

    def terminal(self, project_id, text, cwd):
        root = self.check(project_id)
        host_boundary(root, cwd)
        # The exact shell program is the approved operation; it never runs in a host shell.
        return self.projects.run(['docker', 'exec', '-i', '--workdir', '/workspace',
                                  f'codix-{project_id}', 'python3', '-I', '-c', self.bootstrap],
                                 input_bytes=json.dumps({'command': text, 'cwd': cwd}).encode(),
                                 timeout=120, limit=OUTPUT_LIMIT)

    def stop(self, project_id):
        # A client timeout does not kill Docker-exec descendants. Stop the task's container explicitly.
        result = self.projects.run(['docker', 'stop', '--timeout', '2', f'codix-{project_id}'])
        if result.code:
            raise RuntimeError('Command timed out and container stop failed. Stop Docker before continuing.')


class ToolService:
    def __init__(self, gateway, clock=time.monotonic):
        self.gateway = gateway
        self.clock = clock
        self.pending = {}
        self.plans = {}
        self.stopped = set()

    def begin_task(self, project_id):
        """A new task must never inherit a prior task's plan or approval."""
        self.gateway.check(project_id)
        self.pending.clear()
        self.plans.pop(project_id, None)
        self.stopped.discard(project_id)

    def _active(self, project_id):
        if project_id not in self.plans or project_id in self.stopped:
            raise PermissionError('An active ordered plan is required before editing or executing commands.')

    def propose(self, project_id, name, arguments):
        if name not in SCHEMAS or not isinstance(arguments, dict) or set(arguments) != SCHEMAS[name]:
            raise ValueError('Unknown tool or invalid arguments.')
        self.gateway.check(project_id)
        args = copy.deepcopy(arguments)
        if name in MUTATING:
            self._active(project_id)
        snapshot = None
        required, reason, detail = False, '', ''
        if name == 'set_plan':
            steps = args['steps']
            if not isinstance(steps, list) or not 1 <= len(steps) <= 20 or any(not isinstance(step, str) or not step.strip() or len(step) > 500 for step in steps):
                raise ValueError('Plan needs 1–20 nonempty steps of at most 500 characters.')
            required = project_id in self.plans
            reason = 'Replace the current plan; all prior pending operations will become invalid.'
            detail = redact('\n'.join(f'{index + 1}. {step}' for index, step in enumerate(steps)))
        elif name == 'run_command':
            args['command'] = command(args['command'])
            args['cwd'] = relative_path(args['cwd'], allow_root=True)
            # Validate the working directory without executing any user command.
            self.gateway.file(project_id, {'op': 'list', 'path': args['cwd']})
            required = True
            reason = ('Every terminal command requires approval. This exact shell program may run scripts, '
                      'install dependencies, delete or change protected files, access container paths and use the network. '
                      'No host paths or additional mounts are authorized. Timeout stops the project container.')
            detail = f"/bin/sh -c {args['command']!r}\nWorking directory: /workspace" + ('' if args['cwd'] == '.' else '/' + args['cwd'])
        else:
            args['path'] = relative_path(args['path'], allow_root=name == 'list_files')
            kind = category(args['path'])
            if name == 'read_file' and kind == 'secret':
                raise PermissionError('Secret files cannot be returned to the model or renderer.')
            if name == 'list_files':
                detail = args['path']
            else:
                snapshot = self.gateway.file(project_id, {'op': 'inspect', 'path': args['path']})
                if name in ('read_file', 'edit_file', 'delete_file') and not snapshot['exists']:
                    raise ValueError('File does not exist.')
                if name == 'create_file' and snapshot['exists']:
                    raise ValueError('File already exists; use edit_file.')
                if name in ('create_file', 'edit_file'):
                    if not isinstance(args['content'], str) or len(args['content'].encode()) > FILE_LIMIT:
                        raise ValueError('Content must be UTF-8 text of at most 32 KiB.')
                    if kind == 'secret':
                        detail = f"{args['path']}: replace content; {len(args['content'].encode())} bytes; SHA256 {hashlib.sha256(args['content'].encode()).hexdigest()}; values hidden."
                    else:
                        diff = ''.join(difflib.unified_diff(snapshot.get('content', '').splitlines(True), args['content'].splitlines(True),
                                                            fromfile=args['path'], tofile=args['path']))
                        # Never ask approval for an incomplete proposed patch.
                        if len(diff.encode()) > 49152:
                            raise ValueError('Proposed diff too large; split it into smaller edits.')
                        detail = redact(diff)
                else:
                    detail = args['path']
                required = name == 'delete_file' or name in MUTATING and kind != 'normal'
                reason = 'Delete a file.' if name == 'delete_file' else 'Modify a protected project file.'
        # Bound pending state. A new operation supersedes older unexecuted proposals.
        self.pending.clear()
        ticket = secrets.token_urlsafe(32)
        version = self.plans.get(project_id, {}).get('version', 0)
        self.pending[ticket] = {'project_id': project_id, 'name': name, 'args': args, 'snapshot': snapshot,
                                'required': required, 'version': version, 'expires': self.clock() + 300}
        return {'ticket': ticket, 'approval_required': required, 'tool': name,
                'reason': reason if required else '', 'detail': detail}

    def execute(self, project_id, ticket, approved=False):
        proposal = self.pending.pop(ticket, None)
        if proposal is None or proposal['project_id'] != project_id or proposal['expires'] < self.clock():
            raise PermissionError('Approval is missing, expired, consumed or belongs to another project.')
        name, args = proposal['name'], proposal['args']
        if self.plans.get(project_id, {}).get('version', 0) != proposal['version']:
            raise PermissionError('Plan changed; request a new operation.')
        if proposal['required'] and approved is not True:
            self.stopped.add(project_id)
            raise PermissionError('Operation denied. Task stopped; a revised plan is required.')
        self.gateway.check(project_id)
        if name in MUTATING:
            self._active(project_id)
        if name == 'set_plan':
            self.plans[project_id] = {'version': proposal['version'] + 1, 'steps': args['steps']}
            self.stopped.discard(project_id)
            return {'plan': redact('\n'.join(args['steps'])), 'version': proposal['version'] + 1}
        if name == 'run_command':
            result = self.gateway.terminal(project_id, args['command'], args['cwd'])
            if result.code == 124:
                self.stopped.add(project_id)
                self.gateway.stop(project_id)
            return {'exit_code': result.code, 'stdout': redact(result.stdout), 'stderr': redact(result.stderr),
                    'timed_out': result.code == 124}
        if name == 'list_files':
            return self.gateway.file(project_id, {'op': 'list', 'path': args['path']})
        current = self.gateway.file(project_id, {'op': 'inspect', 'path': args['path']})
        if (current['exists'], current['sha256']) != (proposal['snapshot']['exists'], proposal['snapshot']['sha256']):
            raise PermissionError('File changed since preview; request fresh approval.')
        if name == 'read_file':
            return {'content': redact(current['content']), 'sha256': current['sha256']}
        request = {'op': 'delete' if name == 'delete_file' else 'write', 'path': args['path'],
                   'expected': current['sha256'], 'exists': current['exists']}
        if name != 'delete_file':
            request['content'] = args['content']
        return self.gateway.file(project_id, request)
