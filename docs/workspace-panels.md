# Readonly files, resizable workspace and approved Docker PTYs

The approved extension is recorded in `spec.md` section 13. It leaves agent graph,
chat/provider, model budgets, correction cycles and agent HITL behavior unchanged.

## Implementation

- `file-viewer.jsx` opens actual content in multiple readonly center tabs, with
  refresh, paths and loading/error/empty states. `file-tree.jsx` opens files.
  `backend/file_viewer.py` and `container_files.py` provide `/files/view`, independent
  of agent approval tickets. Secret targets are blocked, other known credentials
  redacted. Host boundary and Linux descriptor-relative no-follow checks reject
  traversal, symlinks/junctions and hardlinks. UTF-8/BOM text up to 32 KiB is shown;
  binary/non-UTF-8 and larger files return explicit statuses without file content.
- `components/ui/resizable.jsx` wraps shadcn's underlying
  [react-resizable-panels](https://github.com/bvaughn/react-resizable-panels) v4
  Group/Panel/Separator API. Nested groups in `workbench.jsx` start at explorer
  240px, chat 360px and bottom terminal 240px. Minimums are explorer 180px,
  files 220px, chat 280px, top area 280px, terminal 190px. Header controls collapse
  either side; explorer auto-collapses below 1050px (chat below 780px). No saved
  layout/history, editor or extra workspace mode is introduced.
- `public/fonts/Vazirmatn.woff2` is the official
  [Vazirmatn v33.003 variable webfont](https://github.com/rastikerdar/vazirmatn/tree/v33.003/fonts/webfonts),
  with the upstream `OFL.txt`. SHA256:
  `4e3fa217d38fdafc1fea4414ceb58ca5e662cf0ab5fa735a8c8c20e8b42cad92`.
  CSS loads it from packaged `/fonts/`, never a CDN; code/terminal remain monospace.
- `terminal-panel.jsx` uses [xterm.js](https://xtermjs.org/docs/guides/using-addons/)
  and FitAddon for actual PTY output, tabs, resizing and independent session inputs.
  No link/clipboard add-on, OSC 8 navigation, OSC 52 clipboard writes or raw keyboard
  forwarding. `CommandPanel` still renders the actual agent command/stdout/stderr.
- `backend/terminals.py` owns at most four manual sessions. It revalidates the
  existing container configuration/identity before approval and execution, pins
  Docker exec to its exact container ID, and starts the trusted Linux-only
  `container_pty.py` supervisor. No host shell or Docker socket is added. Shells
  start at `/workspace`; persistent directory/environment/job state is per PTY.
  Provider credentials are not passed to the container or renderer. Output is
  redacted across chunk boundaries, bounded to 131,072 retained characters per
  session (32,768 per poll), with a visible dropped-output notice. xterm scrollback
  is bounded to 2,000 lines. PTY stdout/stderr are merged by design.
- New authenticated `/terminals/propose` and `/terminals/execute` use separate
  expiring 300-second one-use tickets, bound to project/container/session/exact
  input. The Electron main process keeps tickets, token and approval flags private.
  A native default-reject dialog reviews shell opening and each complete input
  before any bytes reach the PTY. Input is at most 4,096 UTF-8 bytes; invisible
  control/bidi commands and known credential values are rejected. An empty input
  can deliver an approved Enter to a program prompt. A reviewed multiline batch
  is a single approved operation, matching the existing shell-program policy.
- Poll/resize/interrupt/close have narrow endpoints/IPC and remain available while
  a native dialog or agent task waits. Opening/sending input is blocked during an
  active agent task. Closing a session sends control/EOF, waits for supervisor
  confirmation, and reaps its process subtree with Linux subreaper semantics,
  including background descendants; it never stops the shared project container.
  Project changes and backend shutdown close all manual sessions. A shutdown gate
  prevents a queued request from creating a session after cleanup.

## Checks

Final results: **100 backend tests**, **2 configuration tests**, and **all four
GUI suites passed**. Desktop syntax checks, Next.js static build, Windows backend
freeze, final portable assembly/audit, native Windows UI startup and native real
Docker workspace acceptance passed. Screenshot `.verification/codix-panels.png`
was captured and visually reviewed, including actual manual PTY output. The GUI
test also verified the local Vazirmatn FontFace was loaded, not merely a fallback.
A concurrent-input/output regression test protects against the API lock contention
found during GUI acceptance. No commit or push was made.

Development/build/unit/GUI commands run inside Docker; Windows scripts accept
built application artifacts and execute project commands only in disposable Docker
containers. Test fixtures are not selectable in the shipped application.

- `python3 -m unittest discover -s tests`: backend regression plus real PTY tests
  for readonly file limits/boundaries, approval tickets, input denial, container
  replacement, independent cwd/env, live output, interrupt, actual geometry,
  descendant cleanup, EOF/shutdown, bounds, redaction, program input and HITL locks.
- `npm run check:desktop`, `npm run test:config`, `npm run build`.
- Networkless GUI: `npm run test:workspace` tests real file tabs, binary/size/secret
  handling, all three mouse drag handles, initial sizes, collapse/overflow, local
  font, real PTY rendering, native rejection and independent tab cleanup.
  Existing `test:desktop`, `test:approvals`, `test:task` cover bridge restrictions,
  chat/context, shared budget, agent correction and native HITL regressions.
- `packaging/windows-workspace-smoke.ps1`: built Windows backend plus real Docker
  exec sessions, readonly files, independent state, resize, live output, Ctrl+C,
  background cleanup, sibling survival, rejection and container continuity.
- Wine/PyInstaller includes the new standalone worker; portable audit checks worker
  and offline font identity. The installed user's `.env` is preserved/excluded.

## Limits

This intentionally uses approved complete input, not raw per-keystroke forwarding:
arbitrary full-screen/raw-key applications are not supported. Every program input
requires review; Ctrl+C is direct and selected text can still be copied normally.
There is no terminal-issued agent approval, model call, history persistence or
terminal session restoration. Existing directory listing caps (200 entries) and
agent output-after-completion behavior remain. If a supervisor loses transport
without confirming cleanup, closing reports an error and retains the tab; it does
not claim success or stop the entire container. These checks are not exhaustive
certification of arbitrary project Dockerfiles/shell programs or accessibility.
The paid live AvalAI acceptance was not repeated for this extension; chat/context,
HITL and unchanged model-budget behavior were covered by the existing scripted
graph/GUI tests. Previous live-provider evidence is in `workspace-redesign.md`.

## Files changed in this extension

- UI: `components/workspace/workbench.jsx`, `file-tree.jsx`, new `file-viewer.jsx`
  and `terminal-panel.jsx`; new `components/ui/resizable.jsx`; `app/globals.css`.
- Backend: `backend/container_files.py`, `server.py`; new `file_viewer.py`,
  `terminals.py`, `container_pty.py`. No changes to agent graph/provider/budget files.
- Bridge/assets/dependencies: `desktop/main.cjs`, `desktop/preload.cjs`,
  `public/fonts/Vazirmatn.woff2`, `public/fonts/OFL.txt`, `package.json`, `package-lock.json`.
- Verification/packaging: `tests/desktop-smoke.cjs`; new `tests/test_workspace.py`,
  `tests/desktop_workspace_backend.py`, `tests/workspace-smoke.cjs`;
  `packaging/build-backend.sh`, `packaging/audit-portable.py`, new
  `packaging/windows-workspace-smoke.ps1`.
- Documentation: `README.md`, `spec.md`, `docs/manual-testing.md`,
  `docs/workspace-redesign.md`, this file. Existing unrelated working changes were retained.
