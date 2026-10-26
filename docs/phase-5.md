# Phase 5 — Windows portable build and acceptance

Credential configuration was subsequently changed by user request: the current
build reads a local `.env` beside `Codix.exe`, not DPAPI. This report records the
phase's original tests; see [current setup](git-and-provider.md) and
[configuration change verification](env-configuration.md) for the credential change.
Subsequent [native live acceptance](token-budget-fix.md) now passes: Persian
Hello World creation and actual Docker execution, four calls/3,353 reported tokens.

Date: 2026-10-26. This report distinguishes product implementation/local
acceptance from the external-account requirement for live model acceptance.

## Product and build

The phase 4 backend is frozen with Windows Python 3.12.10/PyInstaller 6.22.3
under Wine 10 inside the previously approved Docker builder. The static Next.js
UI is built inside the development container. No host Python/npm compilation
or new dependency installation was used. Project commands execute in Linux
containers; native host execution is only acceptance of the built product.

The release folder is `dist/Codix-MVP-win32-x64`. Keep its entire contents
together and run `Codix.exe`. It contains Electron, static UI, frozen backend,
default Dockerfile and licenses. It does not need separately installed Python
or Node.js. Docker Desktop's Linux engine, WSL2, the default project image and
a valid AvalAI key/model remain prerequisites. The portable artifact is not signed
by this project and has no installer or updater.

Reproduction from the repository root in PowerShell (tools execute in Docker):

```powershell
docker exec codix-development npm run build
docker run --rm --cap-drop ALL --security-opt no-new-privileges:true --mount "type=bind,source=$((Get-Location).Path),target=/workspace" codix-windows-builder:local /bin/sh packaging/build-backend.sh
docker run --rm --cap-drop ALL --security-opt no-new-privileges:true --mount "type=bind,source=$((Get-Location).Path),target=/workspace" codix-windows-builder:local node packaging/build-portable.cjs --mvp
docker exec codix-development python3 packaging/audit-portable.py --mvp
```

The previously approved builder image must already exist; rebuilding its Dockerfile
installs dependencies and requires authorization for that operation. First-time
setup is documented in `windows-portable.md`.

## Acceptance observed

| Scenario | Evidence |
| --- | --- |
| Plan before writes; ordered task/report | Backend suite and real Docker GUI task flow |
| Skills are relevant instructions only | Phase 4 unit tests and loaded Skill in GUI flow |
| Failed check, fix, renewed approval, passing recheck | Actual Python assertions in Docker GUI test |
| Third-cycle/token/action limits; denied operation | Backend graph/policy suites |
| Startup, protected renderer bridge, missing Docker handling | Restricted desktop GUI and backend tests |
| Dockerfile approval rejection/tampering; container isolation | Backend manager/approval tests; no arbitrary custom Dockerfile was built |
| Native Windows backend and Docker/WSL | Packaged backend smoke passed on this machine |
| Native path containing spaces; persistent container reuse | Native smoke creates/selects/prepares the same disposable project twice |
| Native file create/read and protected-write gate | Real ToolService/Docker file worker, not a model fixture |
| Native rejected deletion preserves file | Actual 403 and successful read after denial |
| Invalid/conflicting Windows API port | Packaged executable rejects invalid port and an exclusive occupied Windows socket |
| Native missing Docker | A child-only minimal environment hides Docker CLI; prerequisites return 503 without host fallback |
| API/model acceptance | Live probe still returns HTTP 401 with the saved key; no successful real-model task is claimed |

The native test's disposable container is removed. Its small test files remain
under ignored `.verification/`; user project files are not deleted. API keys
remain outside the repository and project mounts. The real-key probe prints only
fixed diagnostics and token accounting. The reported reserved tokens after a
provider error are not a verified billable-token total.

Final checks passed: all **73 backend tests**, `packaging/audit-portable.py --mvp`,
packaging-script syntax and `git diff --check`. The MVP Windows UI check passed:
its native window opened and displayed a connected backend, then closed. The
full backend suite ran inside Docker; native acceptance ran only built products.
A native UI check uses the isolated test port 43220 and accessibility
only for the test process, then closes that process. DBus/GPU diagnostics in Linux
GUI tests are environmental warnings; all assertions passed.

The initial missing-Docker simulation inherited executable paths and still found
Docker. Its test-only child environment was made minimal; the rerun passed.
This did not change the user's PATH, Docker installation or system settings.

## Limits and remaining acceptance

The local implementation and portable-build checks cannot establish live model
coding quality or account access. The saved key is rejected with HTTP 401 by
AvalAI. To finish real-model acceptance, save a valid API key under the same
Windows account, close older Codix instances, launch this release and run the
small task from `manual-testing.md`, including command approval and denial checks.
Do not send the key in chat or add it to project files.

Only this Windows x64 machine was tested. Other Windows versions, signing,
arbitrary project toolchains, task persistence/cancellation and stronger isolation
against all behavior inside an explicitly approved shell command are not claimed.
No commit or push is made without explicit user approval.

Packaging/test changes: `packaging/build-portable.cjs`,
`packaging/audit-portable.py`, `packaging/windows-smoke.ps1`,
`packaging/windows-startup-negative.ps1`; documentation changes include this
report, `phase-4.md`, `README.md`, `manual-testing.md`, and `windows-portable.md`.
Generated release files remain ignored in `dist/` and `runtime/`.
