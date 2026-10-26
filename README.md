# Codix

The latest repaired Windows artifact is `dist/Codix-win32-x64-updated/Codix.exe`.
AvalAI uses the approved direct HTTPS route with full TLS verification; global
Windows proxy settings are unchanged. The live probe now reaches AvalAI but the
current saved key is rejected with HTTP 401. See [connection diagnosis](docs/provider-diagnostics.md).

Windows portable coding harness: Electron + Next.js/shadcn UI, Python backend and isolated Docker project execution. `spec.md` is the source of truth for MVP scope.

Phase 3 adds the Responses adapter, bounded LangGraph task execution, task input/progress/report UI and native task approvals. The current backend suite has 57 passing tests. Desktop/approval/task GUI checks passed inside Docker with a scripted provider. The Windows portable folder now passes native startup, connected UI and real Docker smoke checks on this machine; live AvalAI inference remains unverified. See [Windows build and results](docs/windows-portable.md), [phase 3 results](docs/phase-3.md), [phase 2 policy](docs/phase-2.md) and [approved decisions](docs/phase-0.md).

## Development rules

- Docker Desktop and WSL2 must be installed and the Linux engine must be running.
- Execute project commands, dependency installation, tests and builds inside a container only. Do not fall back to host Python or npm.
- Dependency installation and project Dockerfile execution require separate approval of the actual operation.
- The default environment Dockerfile is `docker/default.Dockerfile`; its intended image tag is `codix-project:node22-python312`.
- The backend uses `CODIX_API_PORT` (default 43121) and receives its per-launch authentication token privately from Electron.
- Task execution defaults to AvalAI (`https://api.avalai.ir/v1`) and requires an account-supported `CODIX_MODEL`. Save the key in the private Windows DPAPI store outside the repository; see [Git, key setup and provider limitations](docs/git-and-provider.md). Explicit backend development also supports `AVALAI_API_KEY` / `OPENAI_API_KEY`. Keys are removed before renderer creation and are not forwarded to project containers.
- After implementing and testing each phase, report the results and wait for explicit user approval before committing. Push requires a separate instruction. The configured origin is `https://github.com/javad-husseini/codix_harness.git`.

## Check commands (inside the approved development container)

See [key checks and manual acceptance steps](docs/manual-testing.md) and
[Windows portable build and launch](docs/windows-portable.md).

```text
python3 -m unittest discover -s tests -v
npm run check:desktop
npm run build
```

Dependencies were installed inside Docker and `package-lock.json` is present. Use `npm ci` inside the development container for a fresh locked installation after approval; the recorded verification used `npm install` to generate the initial lockfile.

The GUI development image is defined in `docker/development.Dockerfile`. The successful `npm run test:desktop` check requires the separately approved, restricted GUI container described in the phase 1 report, including `--init` and its namespace setup. Ordinary project-container isolation is unchanged. Windows packaging uses the separately approved Wine build route inside Docker; launch `dist/Codix-win32-x64/Codix.exe` with its entire folder intact.

Docker data was relocated with user approval to `D:\CodixDockerData\wsl`. An NTFS junction preserves Docker/WSL's original registration path. Dependencies and build cache use named Docker volumes on D:.

## Source map

| Path | Responsibility |
| --- | --- |
| `desktop/main.cjs` | Backend lifecycle, restricted IPC, native project selection/approval and local UI protocol |
| `desktop/preload.cjs` | Narrow renderer bridge without tokens or generic IPC |
| `app/`, `components/ui/`, `lib/` | Static Next.js UI and local Button component |
| `backend/server.py` | Authenticated loopback API |
| `backend/projects.py` | Docker prerequisites, approval tickets, project container lifecycle and fixed smoke check |
| `backend/processes.py` | Bounded process capture for trusted control-plane commands |
| `backend/provider.py`, `backend/tasks.py` | Responses API/token budget and bounded LangGraph task lifecycle |
| `backend/policy.py`, `backend/tools.py` | Path/secret/protection policy, tool definitions, plan gates and approval tickets |
| `backend/container_files.py`, `backend/container_terminal.py` | Trusted standalone workers executed inside the selected project container |
| `tests/test_backend.py` | Authentication, approval, isolation/reuse and output-bound checks |

The controlled tool API is available at `/tools/catalog`, `/tools/propose` and `/tools/execute`. Task lifecycle uses `/tasks/start`, `/tasks/status` and `/tasks/decide`. Electron keeps tokens/decisions private and routes sensitive proposals through a native dialog. Every terminal command needs separate approval. The UI now submits tasks and displays plans, results and token accounting; failures stop until phase 4 adds bounded correction.

Install the Python lockfile inside the development/backend container when rebuilding the environment. The phase 3 GUI image is `codix-development:phase3`; its restricted GUI test setup is recorded in the phase report. Live API acceptance remains pending configuration of a real key and an account-supported model.
