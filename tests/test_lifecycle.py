"""Actual backend process startup, occupied-port rejection and parent EOF."""
import http.client
import os
import queue
import socket
import subprocess
import sys
import threading
import unittest

# Match Electron's supported backend startup deadline; heavy Docker I/O can exceed 5s.
STARTUP_TIMEOUT = 15


class LifecycleTests(unittest.TestCase):
    def test_immediate_restart_after_authenticated_connection(self):
        from backend.server import make_server
        first = make_server('f' * 64, 0)
        port = first.server_port
        thread = threading.Thread(target=first.serve_forever, daemon=True)
        thread.start()
        client = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        client.request('GET', '/health', headers={'Authorization': 'Bearer ' + 'f' * 64})
        response = client.getresponse()
        response.read()
        client.close()
        first.shutdown()
        first.server_close()
        thread.join()
        second = make_server('e' * 64, port)
        second.server_close()

    def test_authenticated_startup_and_parent_eof(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        token = 'c' * 64
        child = subprocess.Popen([sys.executable, '-m', 'backend.server'],
                                 env={**os.environ, 'CODIX_API_PORT': str(port)},
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            child.stdin.write(token + '\n')
            child.stdin.flush()
            ready = queue.Queue()
            threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
            self.assertEqual(ready.get(timeout=STARTUP_TIMEOUT).strip(), 'CODIX_READY')
            client = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            client.request('GET', '/health', headers={'Authorization': f'Bearer {token}'})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            client.close()
            child.stdin.close()
            self.assertEqual(child.wait(timeout=5), 0)
            self.assertNotIn(token, child.stderr.read())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    def test_occupied_port_never_announces_readiness(self):
        token = 'd' * 64
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            result = subprocess.run([sys.executable, '-m', 'backend.server'],
                                    env={**os.environ, 'CODIX_API_PORT': str(listener.getsockname()[1])},
                                    input=token + '\n', capture_output=True, text=True, timeout=STARTUP_TIMEOUT)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('CODIX_READY', result.stdout)
        self.assertNotIn(token, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
