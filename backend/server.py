"""Authenticated loopback API with project-bound tool and approval endpoints."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sys
import threading
import socket

from backend.projects import ProjectManager
from backend.tools import ContainerGateway, ToolService, TOOL_SCHEMAS
from backend.policy import redact


def parse_port(value):
    if not re.fullmatch(r"[0-9]{1,5}", str(value)) or not 1024 <= int(value) <= 65535:
        raise ValueError("CODIX_API_PORT must be an integer between 1024 and 65535.")
    return int(value)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Unix SO_REUSEADDR permits restart after TIME_WAIT, but not a second live listener.
    # Windows SO_REUSEADDR can permit address hijacking; use exclusive binding there.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(token, port, manager=None, tool_service=None, task_manager=None):
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A per-launch authentication token is required.")
    projects = manager or ProjectManager()
    tools = tool_service or ToolService(ContainerGateway(projects))
    # Lazy construction keeps health/project setup usable before model configuration exists.
    from backend.tasks import TaskManager
    tasks = task_manager or TaskManager(tools)
    operation_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Codix"

        def log_message(self, *_args):
            pass  # Never log request headers, bodies or secret-bearing process output.

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def reply(self, status, payload):
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

        def authenticated(self):
            expected_host = f"127.0.0.1:{self.server.server_port}"
            auth = self.headers.get("Authorization", "")
            if (self.headers.get("Host") != expected_host
                    or self.headers.get("Origin") is not None
                    or len(auth) > 256
                    or not hmac.compare_digest(auth.encode(), f"Bearer {token}".encode())):
                self.reply(401, {"error": "Unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self.authenticated():
                return
            if self.path == "/health":
                self.reply(200, {"status": "ready", "phase": 4})
            elif self.path == '/tools/catalog':
                self.reply(200, {'tools': TOOL_SCHEMAS})
            else:
                self.reply(404, {"error": "Unknown endpoint"})

        def do_POST(self):
            if not self.authenticated():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 < length <= 262144:
                    raise ValueError("Request body must be between 1 and 262144 bytes.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected an object.")
                if not operation_lock.acquire(blocking=False):
                    self.reply(409, {"error": "Another project operation is in progress."})
                    return
                try:
                    if self.path == '/tasks/start' and set(body) == {'project_id', 'request'} and isinstance(body['project_id'], str):
                        result = tasks.start(body['project_id'], body['request'])
                    elif self.path == '/tasks/status' and set(body) == {'task_id'} and isinstance(body['task_id'], str):
                        result = tasks.get(body['task_id']).snapshot()
                    elif (self.path == '/tasks/decide' and set(body) == {'task_id', 'decision_id', 'approved'}
                          and isinstance(body['task_id'], str) and isinstance(body['decision_id'], str) and type(body['approved']) is bool):
                        task = tasks.get(body['task_id'])
                        task.decide(body['decision_id'], body['approved'])
                        result = {'accepted': True}
                    elif tasks.active():
                        raise PermissionError('Project/manual tools are locked while a task is active or awaiting approval.')
                    elif self.path == "/prerequisites" and not body:
                        result = projects.prerequisites()
                    elif self.path == "/projects/preview" and set(body) == {"root"} and isinstance(body["root"], str):
                        result = projects.preview(body["root"])
                    elif self.path == "/projects/prepare" and set(body) == {"ticket", "approved"} and isinstance(body["ticket"], str) and isinstance(body["approved"], bool):
                        result = projects.prepare(body["ticket"], body["approved"])
                    elif self.path == "/projects/smoke" and set(body) == {"project_id"} and isinstance(body["project_id"], str):
                        result = projects.smoke(body["project_id"])
                    elif (self.path == '/tools/propose' and set(body) == {'project_id', 'name', 'arguments'}
                          and isinstance(body['project_id'], str) and isinstance(body['name'], str)):
                        result = tools.propose(body['project_id'], body['name'], body['arguments'])
                    elif (self.path == '/tools/execute' and set(body) == {'project_id', 'ticket', 'approved'}
                          and isinstance(body['project_id'], str) and isinstance(body['ticket'], str)
                          and isinstance(body['approved'], bool)):
                        result = tools.execute(body['project_id'], body['ticket'], body['approved'])
                    else:
                        raise ValueError("Unknown endpoint or invalid request fields.")
                finally:
                    operation_lock.release()
                self.reply(200, result)
            except PermissionError as exc:
                self.reply(403, {"error": redact(str(exc))})
            except (ValueError, FileNotFoundError, NotADirectoryError):
                self.reply(400, {"error": "Invalid request, plan, tool arguments or project path."})
            except RuntimeError as exc:
                self.reply(503, {"error": str(exc)})
            except Exception:
                self.reply(500, {"error": "Operation failed. No host fallback was used."})

    return Server(("127.0.0.1", port), Handler)


def main():
    # Parent writes the token over stdin, never argv/env/logs. EOF owns backend lifetime.
    try:
        token = sys.stdin.buffer.readline(257).decode("ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise ValueError("Missing launch token")
        server = make_server(token, parse_port(os.getenv("CODIX_API_PORT", "43121")))
    except (ValueError, OSError):
        print("Backend startup failed: invalid configuration or port unavailable.", file=sys.stderr)
        return 1

    def watch_parent():
        sys.stdin.buffer.read()
        server.shutdown()

    threading.Thread(target=watch_parent, daemon=True).start()
    print("CODIX_READY", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
