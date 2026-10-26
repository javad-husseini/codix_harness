# Codix

The latest Windows artifact is `dist/Codix-MVP-win32-x64/Codix.exe`.
Native live AvalAI acceptance now passes: a Persian Hello World task created and
executed `hello.py` in Docker in four model calls and 3,353 reported tokens, with
zero outstanding reservations and the unchanged 25,000-token task limit. The
portable UI also passes native startup. See [budget fix and verification](docs/token-budget-fix.md)
and [local .env setup](docs/git-and-provider.md). The approved direct HTTPS route
keeps TLS verification enabled and Windows proxy settings unchanged.

Windows portable coding harness: Electron + Next.js/shadcn UI, Python backend and isolated Docker project execution. `spec.md` is the source of truth for MVP scope.

Phase 4 adds instruction-only project Skills and at most three correction cycles within the shared 25,000-token budget. The current suite has 79 backend tests, two configuration tests and three Docker GUI suites, including failed-check correction, fresh approvals and clear budget reporting. Phase 5 verified native Windows UI, Docker/file-tool, container-reuse, missing-Docker and port-conflict behavior. See [phase 4](docs/phase-4.md), [phase 5 results](docs/phase-5.md), [configuration verification](docs/env-configuration.md), [Windows build](docs/windows-portable.md) and [approved decisions](docs/phase-0.md).

## Development rules

- Docker Desktop and WSL2 must be installed and the Linux engine must be running.
- Execute project commands, dependency installation, tests and builds inside a container only. Do not fall back to host Python or npm.
- Dependency installation and project Dockerfile execution require separate approval of the actual operation.
- The default environment Dockerfile is `docker/default.Dockerfile`; its intended image tag is `codix-project:node22-python312`.
- The backend uses `CODIX_API_PORT` (default 43121) and receives its per-launch authentication token privately from Electron.
- Fill `AVALAI_API_KEY` in the local Git-ignored `.env`: repository root for development, or next to `Codix.exe` for portable Windows. The empty `.env.example` sets AvalAI (`https://api.avalai.ir/v1`) and `CODIX_MODEL=gpt-5.4-nano`; the model must be supported by your account. Restart after edits. The legacy DPAPI store is no longer read. Keys reach only the backend, never the renderer or project-container environment; see [provider setup](docs/git-and-provider.md).
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

The GUI development image is defined in `docker/development.Dockerfile`. The successful `npm run test:desktop` check requires the separately approved, restricted GUI container described in the phase 1 report, including `--init` and its namespace setup. Ordinary project-container isolation is unchanged. Windows packaging uses the separately approved Wine build route inside Docker; launch `dist/Codix-MVP-win32-x64/Codix.exe` with its entire folder intact.

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

The controlled tool API is available at `/tools/catalog`, `/tools/propose` and `/tools/execute`. Task lifecycle uses `/tasks/start`, `/tasks/status` and `/tasks/decide`. Electron keeps tokens/decisions private and routes sensitive proposals through a native dialog. Every terminal command needs separate approval, including corrective rechecks. The UI displays plans, relevant Skill names, correction count, results and token accounting. Provider/policy/approval errors stop; failed commands can enter at most three correction cycles.

Install the Python lockfile inside the development/backend container when rebuilding the environment. The phase 3 GUI image is `codix-development:phase3`; its restricted GUI test setup is recorded in the phase report. Live tasks require a valid local key and an account-supported model; current live acceptance is recorded in `docs/token-budget-fix.md`.
