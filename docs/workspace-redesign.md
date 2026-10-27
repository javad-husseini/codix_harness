# Codix workspace redesign and bounded session chat

This records the original redesign. The later approved file viewer, resizable
panels, bundled font and interactive Docker sessions supersede its original
file/terminal limitations; see [workspace panels](workspace-panels.md).

## Existing integration and scope

Before this change the frontend only submitted execution tasks; there was no
conversational endpoint or session context. Existing directory listing and command
results already supplied all data needed for the file tree and output panel.
No new file/terminal backend endpoint or interactive terminal was added.

The default composer mode is **گفتگو**. It requests a real model reply without
file/command tools. The explicit **اجرای درخواست** mode uses the existing
`/tasks/start` planning/execution/correction path. No automatic intent classifier
or parallel agent is introduced. Execution/approval blocks new chat submissions.

## Changed files and behavior

- `app/page.jsx` now delegates to modular `components/workspace/`: `workbench.jsx`
  (layout/state/composer/progress), `file-tree.jsx` (lazy directory expansion),
  `message-content.jsx` (escaped text and LTR code blocks), `command-panel.jsx`
  (actual command/stdout/stderr/exit code), and `icon.jsx` (local SVG icons).
- `app/globals.css`: neutral dark panels, violet/blue accents, sidebar/central
  conversation/bottom output layout, system fonts for Persian/English, monospace
  code/paths, focus states, responsive sizing and reduced-motion support.
- `backend/conversation.py`: one memory-only session for the active project,
  capped at 24 stored messages / 16,000 characters. Model context is capped at
  ten prior messages / 8,000 characters; secrets are redacted. No disk history,
  multiple-conversation manager, new model client or new agent implementation.
- `backend/tasks.py`: a tool-free `chat` node in the same `TaskRun` LangGraph and
  same configured Responses provider. Its only allowed response is a validated
  `reply` function result; a returned execution-tool request cannot execute.
  Prior task state, correction count, tool denial and approval state are preserved.
- Related chat reuses the exact task `Budget` after success/failure. Pre-task
  discussion is charged to the first execution task. Standalone chat also has
  a single 25,000-token budget. Only an explicit new execution task starts a new
  task budget; ordinary chat messages never reset one. Maximum three correction
  cycles is unchanged. All model context is included in the existing preflight.
- `backend/server.py`: adds authenticated `POST /chat/send` with only
  `{project_id, message}`. Existing request/response shapes remain compatible;
  `/tasks/status` adds session messages/chat status/accounting. Extra approval
  fields are rejected. Existing root/secret/Docker/tool policies are untouched.
- `desktop/preload.cjs`: adds only `chatSend(text)` to the restricted bridge.
  `desktop/main.cjs` forwards chat to the same backend/current task ID and keeps
  all native approval authority. Task polling returns `awaiting_approval` while
  one native dialog is open, without exposing decision IDs or acceptance flags.
  Default desktop size is 1440x920; renderer sandbox/CSP/key separation remain.
- The tree uses existing `runTool('list_files', {path})` only while execution/chat
  is idle. Cached folders can be opened/collapsed while busy. Completed execution
  refreshes the tree. No file content editor or arbitrary host filesystem access.
- `tests/test_chat.py`: eleven tests for provider/graph context, shared budget,
  pre-task accounting, malformed/tool responses, denied/pending HITL, project
  isolation, memory bounds, secrets, authentication and API compatibility.
- `tests/desktop_task_backend.py`, `tests/task-smoke.cjs`: extend the existing
  restricted GUI suite to two-turn chat, role distinction, file-tree expansion,
  code direction, real Python correction, stdout/stderr, visible approval wait,
  rejected chat bypass, task follow-up accounting and budget-stop display.
  `tests/desktop-smoke.cjs` checks the additive bridge surface.
- `packaging/windows-hello-smoke.ps1 -Chat`: native real-provider chat plus
  existing guarded Docker Hello World acceptance. `packaging/audit-portable.py`
  also checks the final preload and UI identity. `spec.md` section 12 records
  the user-approved scope. README and manual testing are updated.

## Checks actually run

All development/build/test commands ran inside Docker. Native Windows commands
below are acceptance of built application artifacts, with generated code still
executed inside the disposable Docker project container.

- `python3 -m unittest discover -s tests -v`: **90 passed**.
- `npm run check:desktop`: passed; `npm run test:config`: **two passed**.
- `npm run build`: Next.js static build passed.
- Restricted networkless GUI container: `npm run test:desktop`,
  `npm run test:approvals`, `npm run test:task`: **all passed**. A test initially
  matched the user message instead of the arriving assistant reply; the wait
  condition was corrected to inspect assistant messages. No fake provider data
  is present in production; scripted providers exist only in test fixtures.
- Test screenshot `.verification/codix-workspace.png` was captured and visually
  reviewed for the layout, Persian text, file sidebar and separate error output.
- Docker Wine/PyInstaller Windows backend build passed; portable assembly passed:
  `node packaging/build-portable.cjs --mvp`. Existing local `.env` was preserved.
- `python3 packaging/audit-portable.py --mvp --local-config`: passed; runtime
  `.env` excluded without reading/printing it. Packaged resources, final desktop
  bridge/UI/backend and empty example were checked.
- Native `windows-ui-smoke.ps1 -ApplicationExecutable <MVP Codix.exe>`: passed.
- Native `windows-hello-smoke.ps1 -Chat`: **passed with real AvalAI**. Two initial
  conversational replies remembered a session code with **1,207 reported tokens**
  and no file/command/approval action. The first execution task included that
  budget/context, created only `hello.py`, obtained one exact guarded approval,
  and actually printed `Hello, World!` in Docker. Related follow-up chat used
  the same task ID and recorded result, with no additional command. Combined
  consumption was **6,873 provider-reported tokens**, within the unchanged
  25,000-token ceiling; no unreported reservation remained at execution completion.
- `git diff --check`: passed. No commit or push performed.

## Limitations and skipped checks

- Select/prepare a project before chatting, matching the existing project-bound
  agent lifecycle. Chat cannot run concurrently with execution/native approval.
- File data remains bounded to 200 directory entries per existing tool call;
  truncation is shown. No tree reads during active execution/chat; cached entries
  remain available. There is no new search, editor or file-watching backend.
- Command output is received after completion and retains existing truncation;
  there is no streaming output, live process metadata or interactive terminal.
- Context/history is bounded and memory-only. Old context can be omitted to keep
  requests within budget; reopening the application loses the session. A task's
  remaining budget can also prevent a follow-up chat call before the ceiling.
- Real-provider acceptance covers this configured account/model and simple task;
  other models/accounts, large-project live tasks and exhaustive responsive/
  accessibility certification were not run. Previous full Docker negative-startup
  tests were not repeated because their code paths are unchanged.
