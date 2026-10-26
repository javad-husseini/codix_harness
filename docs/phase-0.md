# Phase 0 — MVP implementation decisions

Status: documentation complete; implementation and runtime verification pending.
Decision date: 2026-10-19.
Source of scope: `../spec.md`. Repository rules: `../AGENTS.md`.

## User-approved decisions

| Area | Decision |
| --- | --- |
| Default project environment | Linux Docker image with Node.js 22 and Python 3.12. |
| Sensitive operations | Protect secrets, `.git`, `AGENTS.md`, and project Skills. Dependency installation and building/running a project Dockerfile require explicit approval, in addition to the sensitive actions in the specification. |
| Local API | Bind only to `127.0.0.1`; use a configurable fixed port, a random token per application launch, backend access checks, and keep the token outside the web renderer. |
| Portable distribution | Bundle the Python backend with PyInstaller in directory mode, alongside Electron and its resources. Docker Desktop and WSL2 remain external prerequisites. |

These decisions authorize the implementation approach, not future sensitive operations against a selected project.

## Implementation plan

1. Build the Electron, Next.js/shadcn, Python/LangGraph skeleton and Docker lifecycle.
2. Implement bounded file/terminal tools, path validation, and approval enforcement.
3. Connect the configured OpenAI model and implement plan → execute → inspect → report.
4. Add bounded correction cycles and instruction-only Skills discovery/loading.
5. Validate acceptance scenarios and build the Windows portable folder.

Implement and check one phase at a time. Do not introduce features outside the five capabilities in `spec.md`.

## Runtime and compatibility

- The initial default environment targets Linux-compatible Node.js 22 and Python 3.12 projects. It does not promise Windows-native, GPU, browser automation, or arbitrary system-toolchain compatibility.
- Record exact image tags/digests and dependency versions when creating the build files. Do not silently change the approved language major/minor versions.
- Use the selected project's Dockerfile when present, after approval of the build/run operation. Show the Dockerfile and intended build context, mount and command before approval. Do not silently substitute the default environment after rejection or build failure.
- Reuse one persistent container per canonical project root. Network access is enabled as required by the specification.
- Mount only the selected project root read-write. Project code and commands run inside the container. Missing Docker/WSL2 or incompatible environments produce an actionable error; no host-shell fallback or automatic prerequisite installation.
- A project Dockerfile cannot grant host privileges, additional host mounts, Docker socket access, or relaxed path/approval rules. Requests incompatible with these boundaries stop for a revised approach.

## File and command policy

The following patterns are implementation defaults refining the approved protection categories. Apply them to canonical project-relative paths, at any depth where relevant:

| Category | Protected targets |
| --- | --- |
| Secrets | `.env`, `.env.*`, `*.pem`, `*.key`, `.ssh/**`, `.aws/**`, `.npmrc`, `.pypirc`, `credentials.json`, `secrets.*` |
| Git metadata | `.git` and everything below it, including worktree pointer files |
| Project instructions | `AGENTS.md` files and `.agents/skills/**` |

- Creating, overwriting, editing, renaming or deleting protected targets requires approval of the exact proposed change. All file deletion requires approval, including unprotected files.
- Do not automatically read secret-bearing targets into model context. Approval requests and logs must not reveal secret values. Patterns alone cannot guarantee discovery of every secret; avoid indiscriminate file ingestion.
- Destructive/admin commands, dependency installation, project Dockerfile build/run, outside-root requests, and material plan deviations require a dedicated approval before execution.
- Check terminal operations as well as file tools. A shell command cannot bypass protected-file or deletion checks. Compounds, indirect scripts and uncertain command effects must not be assumed safe; the implementation must reject or require approval rather than rely on model classification alone.
- Bind approval to the specific operation and arguments/proposed change. Changed operations require new approval. Rejection prevents execution and stops or requests a revised plan.
- Resolve traversal, symlinks/junctions and Windows path aliases before enforcing the project boundary. Recheck before execution. Approval for an outside-root request never permits escape from the container mount policy; an inaccessible external target remains blocked.
- Exact command-parser rules and path-resolution mechanics must be specified and tested during phase 2; this document does not claim they already exist.

## Local API and configuration

- Proposed default fixed port: `43121`, configurable through `CODIX_API_PORT`. Accept only valid port numbers. Bind failure or port conflict stops startup with a clear message; do not silently pick another port or connect to an existing listener.
- Electron starts the bundled backend, generates a fresh authentication token for each launch, and retains it in its main process and the backend only. Do not place it in renderer state, URLs, command-line arguments or logs.
- The renderer accesses a narrow Electron bridge. The main process authenticates backend requests; the backend checks authentication on every application endpoint. Do not expose a generic authenticated HTTP proxy to renderer input.
- Keep renderer privileges restricted and validate bridge requests. Loopback binding and CORS alone are not authentication.
- Read the provider key from `OPENAI_API_KEY`; never hard-code it, send it to the renderer, forward it into project containers or log it. Model selection remains configuration-driven.
- Transport of the launch token and lifecycle cleanup must be implemented without secret exposure and verified in phase 1. No remote API listener is in MVP scope.

## Portable packaging

- Package the Python backend using PyInstaller directory mode and include its runtime dependencies. A user-installed Python must not be required.
- Bundle Electron, the Next.js UI resources and backend together in a Windows portable folder; no installer.
- Development/project commands remain container-only. Windows artifact building requires a Windows container/toolchain compatible with PyInstaller and Electron packaging; the Linux project image is not evidence that Windows artifacts can be built.
- Validate the Windows container build route before committing packaging scripts. If unavailable on the target setup, report the blocker and ask for an approved approach; do not run host builds as a fallback.
- Verify the distributed artifact on Windows with Docker Desktop/WSL2 already present, including paths containing spaces and a missing/conflicting API port configuration.

## Acceptance checks for subsequent phases

| Check | Expected outcome |
| --- | --- |
| Startup and API | Electron starts the backend; valid authenticated bridge calls work; unauthenticated calls fail; occupied port produces a clear error. |
| Docker lifecycle | Missing prerequisites stop execution; reopening a project reuses its container; Dockerfile use pauses for approval. |
| Project boundaries | Traversal, external symlink/junction targets and extra host mounts cannot escape the selected root. |
| Approvals | File deletion, protected writes, dependency installation and sensitive commands pause; denial results in no execution. Terminal tools obey the same policy. |
| Task graph | A plan exists before editing; steps execute in order; material deviations require approval. |
| Limits | At most 3 correction cycles; reserve input/output allowance before each model call so total usage cannot exceed 25,000 tokens; stop conservatively when usage is uncertain. |
| Skills | Only relevant instruction files load; invalid Skills are reported when relevant; embedded scripts never execute or grant permissions. |
| Completion | Relevant checks actually run; final report lists changed files, commands/results, skipped checks and unresolved issues. |
| Distribution | Portable Windows folder starts without separately installed Python; Docker prerequisites remain explicit. |

## Phase 0 validation and remaining work

- Compared this document with the four user answers, `spec.md`, `AGENTS.md`, and the instruction-only verification Skill.
- No application code, container configuration or dependency installation is part of phase 0.
- Runtime tests and portable build tests have not run. Their acceptance checks above remain pending.
- Before packaging implementation, resolve the Windows container build route. Before security implementation, turn the policy into explicit, testable enforcement rules. Neither may silently weaken the approved constraints.
