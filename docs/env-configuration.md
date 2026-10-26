# Local .env configuration change

User request: replace the saved-key structure with an editable, Git-ignored
`.env` and a safe example. No real key was read, copied or populated.

## Behavior and files

- `.env` is created locally with empty key fields, AvalAI URL and `gpt-5.4-nano`.
  `.env.example` is the only committable template; `.gitignore` documents this.
- `desktop/config.cjs` reads only four allowlisted settings from the exact file,
  without shell evaluation or process-environment mutation. Symlinks, hard links,
  nonregular and oversized files are rejected with fixed diagnostics.
- `desktop/main.cjs` reads the repository file in development and the file beside
  `Codix.exe` in portable mode. File values override inherited provider settings;
  keys go only to the backend child, not the renderer.
- `backend/credentials.py` no longer reads DPAPI. Existing environment validation
  remains; `backend/provider.py` points missing-key errors to `.env`.
- `packaging/build-portable.cjs` copies only the empty example and initializes
  a missing portable `.env`, preserving an existing one. It never copies the
  repository `.env`. `packaging/audit-portable.py` refuses a filled distributable.
- `tests/config.test.cjs`, `tests/test_credentials.py`, the three GUI fixtures and
  `package.json` cover parsing, compatibility, file-value precedence, backend-only
  handoff and isolation. GUI fixtures never read a real configuration file.
- `AGENTS.md`, `spec.md`, `README.md`, `git-and-provider.md`, `manual-testing.md`,
  `windows-portable.md` and `phase-5.md` document the approved change.

The plaintext file is not encrypted. Existing secret-file tool policy blocks
reads, but an explicitly approved arbitrary shell command can access mounted
files. Do not distribute a filled `.env`. The old DPAPI file was left untouched.

## Verification

Executed inside Docker:

- `python3 -m unittest discover -s tests -v`: 72 passed (two retired DPAPI-only
  tests removed, one missing-configuration test added).
- `npm run check:desktop`: passed.
- `npm run test:config`: two tests passed.
- `npm run test:desktop`, `npm run test:approvals`, `npm run test:task`: all passed
  in the restricted GUI container. The task fixture proves file-config values
  override inherited fake keys and both key variables remain absent in renderer
  process environment. Container DBus/GPU warnings did not fail the suites.
- `/bin/sh packaging/build-backend.sh`: Windows backend rebuilt successfully
  under Wine/PyInstaller in Docker. System DLL discovery warnings are covered
  by native launch verification.

- `node packaging/build-portable.cjs --mvp` in the Docker Windows builder:
  passed. Updated artifact: `dist/Codix-MVP-win32-x64/Codix.exe`; the local
  `.env` and `.env.example` beside it contain only blank key fields.
- `python3 packaging/audit-portable.py --mvp` in Docker: passed, including exact
  desktop configuration source and backend identity plus blank-template checks.
- Git checks in Docker: `.env`/`.env.local` ignored, `.env.example` not ignored,
  no tracked `.env`/`.env.local`; `git diff --check` and packaging syntax passed.

Native built-product acceptance on Windows:

- `packaging/windows-ui-smoke.ps1 -ApplicationExecutable <current Codix.exe>`:
  passed; the window rendered and connected to the rebuilt backend.

Skipped: no live provider request, since the user will fill the new key. No UI
rebuild is needed because frontend code is unchanged. The full Docker/file-tool
and negative-startup acceptance tests were already run for phase 5 and were not
repeated for this configuration-only change. No commit or push was performed.
