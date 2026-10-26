# Windows portable build

Current credential setup: fill `.env` next to `Codix.exe`, then restart. The
build creates an empty template there and preserves existing local settings.
The repository `.env` is never copied into the artifact. The previous DPAPI
setup described in historical build notes below has been retired. See
[current setup](git-and-provider.md) and [verification](env-configuration.md).

Current release: `dist/Codix-MVP-win32-x64`, built with `--mvp`. Phase 4 Skills and
correction and the phase 5 local/native acceptance checks are now implemented;
see `phase-4.md` and `phase-5.md`. The historical phase 3 build results below
remain a record of the initial artifact. The latest native AvalAI Hello World
acceptance passed in four calls/3,353 reported tokens; see [current results](token-budget-fix.md).

The user approved building with Wine inside Linux Docker on 2026-10-20 because
this Windows Home machine cannot run Windows containers. This changes the phase
0 build route, not the runtime project-container isolation policy. No host
Python/npm compilation is used. Native execution of the resulting product is
the approved acceptance test.

## Build (PowerShell at the repository root)

These commands invoke all build tools inside Docker. Dependency installation and
this project Dockerfile's execution were approved for this setup.

```powershell
docker exec codix-development npm run build
docker build -f docker/windows-build.Dockerfile -t codix-windows-builder:local .
$repo = (Get-Location).Path
docker run --rm --cap-drop ALL --security-opt no-new-privileges:true --mount "type=bind,source=$repo,target=/workspace" codix-windows-builder:local /bin/sh packaging/build-backend.sh
docker run --rm --cap-drop ALL --security-opt no-new-privileges:true --mount "type=bind,source=$repo,target=/workspace" codix-windows-builder:local node packaging/build-portable.cjs
```

Keep the entire `dist/Codix-win32-x64` folder together. Launch `Codix.exe` on
Windows with Docker Desktop's Linux engine running. Python and Node.js do not
need to be installed separately for the distributed application.

The existing default project image `codix-project:node22-python312` must be
available in Docker. The portable folder includes the pinned default Dockerfile
under `docker/`. On another computer its build is a separate prerequisite,
requiring approval for dependency installation/building that Dockerfile.

## Credentials and model

The application reads the current Windows user's encrypted key from
`%LOCALAPPDATA%\Codix\secrets\avalai-key.dpapi`. It is not copied to the builder,
portable folder or selected project container. See `git-and-provider.md`.
Set `CODIX_MODEL` in the launch environment; this machine's user setting is
`gpt-5.4-nano`. A PowerShell already open before that setting was saved may need:

```powershell
$env:CODIX_MODEL = [Environment]::GetEnvironmentVariable('CODIX_MODEL', 'User')
Start-Process -FilePath '.\dist\Codix-win32-x64\Codix.exe'
```

No key or other secret belongs in these commands.

## Implementation and constraints

Windows Python 3.12.10 and PyInstaller 6.22.3 run under Wine 10 in the builder.
Python's optional WMI module is disabled in that builder because its machine
discovery triggers an unimplemented Wine API. Windows wheels are downloaded
using Linux pip, then installed offline under Wine to avoid Wine TLS limitations.
Trusted container-worker Python source files are explicitly bundled because
the runtime sends their source to isolated project containers. The backend reads
these files without importing them: their Linux-only `os.O_NOFOLLOW` and related
operations must never execute in the Windows backend process.

Electron 44.9.1's official win32-x64 archive is verified against that release's
SHA256 manifest. The packager uses an allowlist: desktop code, static UI,
minimal app package metadata, the frozen backend, default Dockerfile and Python
license. It does not copy the whole repository, node_modules, Git metadata or
credentials. Electron's archive retains its license files.

The folder has no installer or code-signing certificate. Wine build success is
not evidence of native Windows correctness; native smoke results must be checked
separately. This is the phase 3 implementation packaged for testing, not a claim
that pending phase 4 Skills/correction or all phase 5 acceptance work is complete.

See `manual-testing.md` for the small coding task and approval-denial scenario.

## Verified results (2026-10-20)

- `npm run build` succeeded in `codix-development`.
- The Wine 10 builder image, native-wheel/LangGraph import check, onedir backend
  freeze and portable assembly succeeded inside Docker.
- The 57-test backend suite, desktop syntax and portable-script syntax checks
  passed after correcting Windows worker loading.
- `python3 packaging/audit-portable.py` passed inside Docker: both executables
  are Windows x64, the final backend matches the frozen output, worker/UI files
  are present and Git/development/credential files are excluded. `git diff
  --check` also passed.
- `packaging/windows-smoke.ps1` ran the built backend on this Windows machine:
  authenticated startup/catalog, bundled workers/LangGraph, Docker/WSL, a path
  containing spaces, real isolated Node/Python smoke and parent-EOF shutdown all
  passed. The disposable test container was removed; its empty ignored directory
  may remain under `.verification/`.
- `packaging/windows-ui-smoke.ps1` launched the final portable executable and
  confirmed its window and connected-backend status through native accessibility,
  then closed it. Accessibility is forced only for that test instance. The test
  clears inherited `ELECTRON_RUN_AS_NODE` from the coding-tool environment;
  ordinary Explorer launches do not need a development command.

Initial attempts exposed an incompatible older Wine, a manifest parser mismatch,
slow collection over the Windows bind mount, and Linux-worker imports on Windows.
The final build uses Wine 10, handles both standard SHA256 manifest formats,
collects on the container disk before copying and reads workers as data.
PyInstaller still reports missing optional timezone data and Windows system-DLL
resolution warnings under Wine; the native startup and container smoke checks
passed on this machine. Broader Windows-version compatibility is unverified.

No live paid AvalAI request, native end-to-end model task or full phase 5
acceptance run was performed. No signing step, installer, commit or push was
performed for these changes. The package does not implement pending phase 4.

Changed source/document files: `backend/tools.py`, `README.md`,
`docs/manual-testing.md`, `docs/windows-portable.md`,
`docker/windows-build.Dockerfile`, and the build/audit/native-test files in
`packaging/`. Generated binaries and download cache remain ignored in `runtime/`
and `dist/`.
