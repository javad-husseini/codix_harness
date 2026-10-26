"""Project identity, Dockerfile approval and persistent isolated containers."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading

from backend.processes import run

DEFAULT_IMAGE = "codix-project:node22-python312"
MOUNT = "/workspace"


def same_mount_source(source, path):
    expected = str(path).replace("\\", "/")
    actual = str(source).replace("\\", "/")
    if os.name != "nt":
        return actual == expected
    expected, actual = expected.casefold(), actual.casefold()
    # Docker Desktop may expose a canonical Windows bind as its Linux VM path.
    candidates = {expected}
    if len(expected) > 2 and expected[1:3] == ":/":
        drive_path = expected[0] + expected[2:]
        candidates.update({f"/run/desktop/mnt/host/{drive_path}", f"/host_mnt/{drive_path}"})
    return actual in candidates


class ProjectManager:
    def __init__(self, runner=run):
        self.run = runner
        self.pending = {}
        self.projects = {}
        self.lock = threading.Lock()

    def prerequisites(self):
        result = self.run(["docker", "info", "--format", "{{.OSType}}"])
        if result.code or result.stdout.strip() != "linux":
            raise RuntimeError("Start Docker Desktop with the WSL2 Linux engine. Host execution is disabled.")
        if os.name == "nt":
            wsl = self.run(["wsl.exe", "--status"])
            if wsl.code:
                raise RuntimeError("WSL2 is unavailable. Finish WSL2 setup and restart Windows if requested.")
        return {"docker": "ready", "engine": "linux"}

    def describe(self, root):
        path = Path(root).resolve(strict=True)
        if not path.is_dir() or str(path) == path.anchor:
            raise ValueError("Select a project directory, not a drive root.")
        # Avoid ambiguous bind-mount option parsing.
        if any(character in str(path) for character in (",", "\n", "\r")):
            raise ValueError("Project paths containing commas or line breaks are unsupported.")
        key = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:24]
        dockerfile = path / "Dockerfile"
        digest = None
        if dockerfile.exists():
            if dockerfile.is_symlink() or dockerfile.resolve().parent != path:
                raise ValueError("Dockerfile must be a regular file inside the project root.")
            if not dockerfile.is_file() or dockerfile.stat().st_size > 65536:
                raise ValueError("Dockerfile is invalid or larger than 64 KiB.")
            digest = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
        return path, key, digest

    def preview(self, root):
        path, key, digest = self.describe(root)
        self.prerequisites()
        ticket = secrets.token_urlsafe(32)
        image = f"codix-project-{key}:{digest[:16]}" if digest else DEFAULT_IMAGE
        build = ["docker", "build", "--file", str(path / "Dockerfile"), "--tag", image, str(path)] if digest else None
        with self.lock:
            # One live selection/approval at a time; never accept a renderer-supplied root at prepare.
            self.pending.clear()
            self.pending[ticket] = (str(path), key, digest, image)
        return {"ticket": ticket, "root": str(path), "dockerfile": bool(digest),
                "dockerfile_sha256": digest, "build_command": build,
                "container_command": self.create_command(path, key, image),
                "reason": "Build and run project Dockerfile with network access and a read-write project mount. Build instructions may install dependencies." if digest else None}

    def create_command(self, path, key, image):
        return ["docker", "create", "--name", f"codix-{key}",
                "--label", f"codix.project={key}", "--label", "codix.managed=1",
                "--mount", f"type=bind,source={path},target={MOUNT}",
                "--workdir", MOUNT, "--user", "1000:1000", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--pids-limit", "256",
                "--memory", "2g", "--cpus", "2", "--network", "bridge",
                "--no-healthcheck",
                "--entrypoint", "/bin/sh", image, "-c", "while :; do sleep 3600; done"]

    def prepare(self, ticket, approved=False):
        with self.lock:
            selection = self.pending.pop(ticket, None)
        if selection is None:
            raise ValueError("Selection expired. Select the project again.")
        root, key, digest, image = selection
        path, actual_key, actual_digest = self.describe(root)
        if (key, digest) != (actual_key, actual_digest):
            raise ValueError("Project or Dockerfile changed. Select and approve it again.")
        if digest and approved is not True:
            raise PermissionError("Dockerfile execution denied; nothing was built or started.")
        self.prerequisites()
        # Inspect by deterministic name, but validate the complete isolation contract before reuse.
        name = f"codix-{key}"
        inspected = self.run(["docker", "container", "inspect", name])
        if inspected.code == 0:
            data = json.loads(inspected.stdout)[0]
            self.validate_container(data, path, key, image)
        else:
            if digest:
                built = self.run(["docker", "build", "--file", str(path / "Dockerfile"),
                                  "--tag", image, str(path)], timeout=600)
                if built.code:
                    raise RuntimeError("Project image build failed. No fallback was used; inspect the Docker build locally without sharing secrets.")
            elif self.run(["docker", "image", "inspect", image]).code:
                raise RuntimeError("Default image missing. Build docker/default.Dockerfile as codix-project:node22-python312 first.")
            created = self.run(self.create_command(path, key, image))
            if created.code:
                raise RuntimeError("Cannot create project container. Check Docker permissions and project mount compatibility.")
            created_inspect = self.run(["docker", "container", "inspect", name])
            if created_inspect.code:
                raise RuntimeError("Cannot verify the created container. It was not started.")
            self.validate_container(json.loads(created_inspect.stdout)[0], path, key, image)
        started = self.run(["docker", "start", name])
        if started.code:
            raise RuntimeError("Cannot start container. The selected image must support /bin/sh and sleep. No host fallback is available.")
        self.projects[key] = (path, image)
        return {"project_id": key, "root": str(path), "container": name, "status": "ready"}

    def validate_container(self, data, path, key, image):
        host, config = data["HostConfig"], data["Config"]
        mounts = data.get("Mounts", [])
        valid_mount = (len(mounts) == 1 and mounts[0].get("Type") == "bind"
                       and same_mount_source(mounts[0].get("Source", ""), path)
                       and mounts[0].get("Destination") == MOUNT and mounts[0].get("RW") is True)
        valid = (valid_mount and config.get("Labels", {}).get("codix.project") == key
                 and config.get("Labels", {}).get("codix.managed") == "1"
                 and config.get("Image") == image and config.get("User") == "1000:1000"
                 and config.get("WorkingDir") == MOUNT and config.get("Entrypoint") == ["/bin/sh"]
                 and config.get("Cmd") == ["-c", "while :; do sleep 3600; done"]
                 and not host.get("Privileged") and not host.get("CapAdd")
                 and "ALL" in host.get("CapDrop", [])
                 and "no-new-privileges:true" in host.get("SecurityOpt", [])
                 and host.get("NetworkMode") == "bridge" and not host.get("PortBindings")
                 and not host.get("Devices") and not host.get("VolumesFrom")
                 and not config.get("Volumes") and host.get("PidMode", "") == ""
                 and config.get("Healthcheck", {}).get("Test") == ["NONE"]
                 and host.get("IpcMode") in ("private", "")
                 and host.get("PidsLimit") == 256 and host.get("Memory") == 2147483648
                 and host.get("NanoCpus") == 2000000000)
        if not valid:
            raise PermissionError("Existing container does not match Codix isolation settings. It was not started or modified.")

    def smoke(self, project_id):
        if project_id not in self.projects:
            raise ValueError("Select and prepare the project first.")
        path, image = self.projects[project_id]
        name = f"codix-{project_id}"
        inspected = self.run(["docker", "container", "inspect", name])
        if inspected.code:
            raise RuntimeError("Project container is unavailable.")
        self.validate_container(json.loads(inspected.stdout)[0], path, project_id, image)
        # Fixed read-only checks only. No arbitrary terminal endpoint in phase 1.
        result = self.run(["docker", "exec", "--workdir", MOUNT, name,
                           "/bin/sh", "-c", "node --version && python3 --version"], limit=4096)
        return {"exit_code": result.code, "stdout": result.stdout, "stderr": result.stderr,
                "compatible": result.code == 0}
