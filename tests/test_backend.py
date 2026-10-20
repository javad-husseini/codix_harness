import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from backend.projects import ProjectManager
from backend.processes import Result, run
from backend.server import make_server, parse_port


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.token = 'a' * 64
        self.server = make_server(self.token, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path='/health', headers=None, method='GET', body=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        client.request(method, path, body=body, headers=headers or {})
        response = client.getresponse()
        value = json.loads(response.read())
        status = response.status
        client.close()
        return status, value

    def test_missing_wrong_and_valid_auth(self):
        self.assertEqual(self.request()[0], 401)
        self.assertEqual(self.request(headers={'Authorization': 'Bearer wrong'})[0], 401)
        self.assertEqual(self.request(headers={'Authorization': f'Bearer {self.token}'})[0], 200)

    def test_browser_origin_and_host_rejected(self):
        auth = {'Authorization': f'Bearer {self.token}'}
        self.assertEqual(self.request(headers={**auth, 'Origin': 'https://example.com'})[0], 401)
        self.assertEqual(self.request(headers={**auth, 'Host': 'attacker.invalid'})[0], 401)

    def test_invalid_payload_and_no_arbitrary_shell_route(self):
        headers = {'Authorization': f'Bearer {self.token}'}
        self.assertEqual(self.request('/exec', headers, 'POST', '{}')[0], 400)
        self.assertEqual(self.request('/projects/prepare', headers, 'POST', '[]')[0], 400)

    def test_occupied_port_not_reused(self):
        with self.assertRaises(OSError):
            make_server('b' * 64, self.server.server_port)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.calls = []

        def runner(argv, **kwargs):
            self.calls.append(argv)
            if argv[:2] == ['docker', 'info']:
                return Result(0, 'linux\n', '')
            return Result(0, '', '')
        self.manager = ProjectManager(runner)

    def tearDown(self):
        self.directory.cleanup()

    def test_rejection_never_builds_or_starts(self):
        (self.root / 'Dockerfile').write_text('FROM python:3.12-slim-bookworm')
        preview = self.manager.preview(str(self.root))
        with self.assertRaises(PermissionError):
            self.manager.prepare(preview['ticket'], False)
        self.assertFalse(any(call[1] in ('build', 'start', 'create') for call in self.calls))
        with self.assertRaises(ValueError):
            self.manager.prepare(preview['ticket'], True)

    def test_changed_dockerfile_invalidates_approval(self):
        dockerfile = self.root / 'Dockerfile'
        dockerfile.write_text('FROM python:3.12-slim-bookworm')
        preview = self.manager.preview(str(self.root))
        dockerfile.write_text('FROM node:22-bookworm-slim')
        with self.assertRaises(ValueError):
            self.manager.prepare(preview['ticket'], True)

    def test_missing_docker_stops_selection(self):
        def unavailable(*args, **kwargs):
            raise RuntimeError('Required executable is missing')
        with self.assertRaises(RuntimeError):
            ProjectManager(unavailable).preview(str(self.root))

    def container(self):
        path, key, digest = self.manager.describe(str(self.root))
        image = 'codix-project:node22-python312'
        data = {
            'Mounts': [{'Type': 'bind', 'Source': str(path), 'Destination': '/workspace', 'RW': True}],
            'Config': {'Labels': {'codix.project': key, 'codix.managed': '1'}, 'Image': image,
                       'User': '1000:1000', 'WorkingDir': '/workspace', 'Entrypoint': ['/bin/sh'],
                       'Cmd': ['-c', 'while :; do sleep 3600; done'], 'Healthcheck': {'Test': ['NONE']}},
            'HostConfig': {'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges:true'],
                           'NetworkMode': 'bridge', 'IpcMode': 'private', 'PidsLimit': 256, 'Memory': 2147483648,
                           'NanoCpus': 2000000000},
        }
        return path, key, image, data

    def test_reuse_checks_mount_and_privileges(self):
        path, key, image, data = self.container()
        self.manager.validate_container(data, path, key, image)
        data['HostConfig']['Privileged'] = True
        with self.assertRaises(PermissionError):
            self.manager.validate_container(data, path, key, image)
        data['HostConfig']['Privileged'] = False
        data['Mounts'].append({'Type': 'bind', 'Source': '/', 'Destination': '/host', 'RW': True})
        with self.assertRaises(PermissionError):
            self.manager.validate_container(data, path, key, image)

    def test_valid_existing_container_is_reused_without_build(self):
        path, key, image, data = self.container()
        base_runner = self.manager.run
        def runner(argv, **kwargs):
            if argv[:3] == ['docker', 'container', 'inspect']:
                self.calls.append(argv)
                return Result(0, json.dumps([data]), '')
            return base_runner(argv, **kwargs)
        self.manager.run = runner
        preview = self.manager.preview(str(self.root))
        result = self.manager.prepare(preview['ticket'])
        self.assertEqual(result['project_id'], key)
        self.assertTrue(any(call[:2] == ['docker', 'start'] for call in self.calls))
        self.assertFalse(any(call[1] in ('build', 'create') for call in self.calls))


class BoundsTests(unittest.TestCase):
    def test_output_is_drained_but_bounded(self):
        import sys
        result = run([sys.executable, '-c', "print('x' * 100000)"], limit=128)
        self.assertEqual(result.code, 0)
        self.assertLess(len(result.stdout), 160)
        self.assertIn('[output truncated]', result.stdout)

    def test_port_validation(self):
        self.assertEqual(parse_port('43121'), 43121)
        for value in ('0', '80', '65536', '-1', 'abc', '43121/path'):
            with self.assertRaises(ValueError):
                parse_port(value)


if __name__ == '__main__':
    unittest.main()
