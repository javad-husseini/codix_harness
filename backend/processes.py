"""Bounded subprocess capture for trusted control-plane commands only."""
import subprocess
import threading
import os
from pathlib import Path
import shutil
from dataclasses import dataclass


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str


def run(argv: list[str], timeout: int = 30, limit: int = 65536, input_bytes: bytes | None = None) -> Result:
    if argv[0] == "docker" and os.name == "nt" and not shutil.which("docker"):
        installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe"
        if installed.is_file():
            argv = [str(installed), *argv[1:]]
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise RuntimeError("Required executable is missing. Install Docker Desktop with WSL2.") from exc
    buffers = [bytearray(), bytearray()]
    truncated = [False, False]

    def drain(stream, index):
        while chunk := stream.read(4096):
            remaining = max(0, limit - len(buffers[index]))
            buffers[index].extend(chunk[:remaining])
            truncated[index] |= len(chunk) > remaining
        stream.close()

    threads = [threading.Thread(target=drain, args=(stream, index), daemon=True)
               for index, stream in enumerate((process.stdout, process.stderr))]
    for thread in threads:
        thread.start()
    if input_bytes is not None:
        def feed():
            try:
                process.stdin.write(input_bytes)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()
        threading.Thread(target=feed, daemon=True).start()
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        code = 124
    for thread in threads:
        thread.join(timeout=2)
    values = [bytes(value).decode("utf-8", errors="replace") +
              ("\n[output truncated]" if truncated[i] else "")
              for i, value in enumerate(buffers)]
    return Result(code, *values)
