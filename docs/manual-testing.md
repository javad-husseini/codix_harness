# Testing the current implementation

## Configure the local environment file

For the portable app, edit `.env` next to `Codix.exe`; for development edit the
repository-root `.env`. Fill `AVALAI_API_KEY`, save, and restart Codix. The model
and endpoint are already set to `gpt-5.4-nano` and `https://api.avalai.ir/v1`.
Do not print or share the filled file. To check existence only in PowerShell:

```powershell
$p = Join-Path (Get-Location) 'dist\Codix-MVP-win32-x64\.env'
Test-Path -LiteralPath $p
Get-Item -LiteralPath $p | Select-Object FullName,Length,LastWriteTime
```

Expect `True`; existence does not establish that the key is filled or valid.
Only `.env.example` may be committed. The old DPAPI store is no longer read.
See [provider setup](git-and-provider.md).

## Checks available now

From the repository folder in PowerShell, with Docker Desktop running:

```powershell
docker exec codix-development python3 -m unittest discover -s tests -v
docker exec codix-development npm run check:desktop
docker exec codix-development npm run test:config
```

Expect 90 backend tests, two configuration tests and a successful syntax check. The existing
`codix-development` container must be running. These are development checks,
not a Windows desktop launch or live provider test. The restricted GUI fixture
commands and their sandbox requirements are recorded in `phase-3.md`.

## Manual desktop acceptance

The latest portable folder is `dist/Codix-MVP-win32-x64`; launch `Codix.exe`
from that folder after completing the build in `windows-portable.md`. Keep the
entire folder together. Do not run project development commands on the host.
GUI fixtures substitute fake configuration and never read your real `.env`.

To test the portable artifact:

1. Start Docker Desktop and wait for its Linux engine to be ready.
2. Fill `AVALAI_API_KEY` and configure `CODIX_MODEL` in the `.env` beside
   `Codix.exe`, using a Responses/function-calling model supported by your
   AvalAI account. Launch the portable executable.
3. Select a disposable empty project directory without a Dockerfile. Prepare it
   using the default Node.js/Python image. Confirm prerequisite and smoke checks.
4. Select **اجرای درخواست** in the composer, then submit: "Create sum.py with add(a, b). Verify add(2, 3) == 5 using Python.
   Do not install dependencies or delete files."
5. Confirm a plan appears before file edits. Review the exact Python command in
   the native approval dialog, then approve it. Expect a file, zero exit code,
   ordered completed steps, token accounting and a final report.
6. Submit a separate task asking to delete that file. Reject the native approval
   and confirm the file remains and the task stops.
7. Close/reopen the app and select the same directory. Confirm its project
   container is reused. Task history is not persisted.

For chat and the redesigned workspace:

- Default **گفتگو** sends a real conversational message without tools. After
  preparing a project, give a harmless session code and ask for it in a second
  message. Expect real user/agent bubbles and the remembered code, with no command.
- Select **اجرای درخواست** explicitly for file changes or checks. After a task,
  return to **گفتگو** to ask about its result; token accounting must continue from
  that same task. Chat is disabled during execution/approval and cannot approve.
- Expand/collapse existing folders in the sidebar. Unread directories are locked
  while busy; prepared project paths remain visible. The tree has no file editor.
- Read actual commands/exit codes/stdout/stderr in the **خروجی ایجنت** bottom tab
  after command completion. Manual terminals use separate tabs with actual live PTY output.
- See [workspace verification and limitations](workspace-redesign.md) for bounds
  on session memory, directory data and real-provider acceptance results.

For readonly files, layout and manual terminals:

1. Click two text files in the tree. Switch center tabs, close one, and refresh
   the other. Confirm real content, LTR paths/code and no editing/saving controls.
   Try a binary file, a file above 32 KiB, a missing file and `.env`; expect clear
   states/errors, with secrets blocked. Symlink/junction/hardlink targets are blocked.
2. Drag the explorer boundary, the file/chat boundary and the terminal's top edge.
   Check minimum sizes and independent scroll. Resize the window, collapse/reopen
   both side panels using the header folder/chat buttons. Check no page overflow.
   Disconnect the network: Persian still uses the packaged local Vazirmatn font.
3. Press **+**, review/approve the native shell-open request. Type `pwd` in the
   dedicated input box and send; review the exact input before approving. Expect
   `/workspace`. The PTY view itself never forwards unapproved keystrokes.
4. Open a second terminal. In the first approve `cd sub` (use an existing folder)
   and `export SAMPLE=first`; approve `pwd; echo "${SAMPLE-unset}"` in both. Each
   session should retain its own directory/environment. Switch tabs without losing output.
5. Approve `sleep 60`, then press **Ctrl+C** in the terminal/input (without a text
   selection) or click **Ctrl+C**. Wait for the shell prompt, then send the next
   input. Resize the panel and approve `stty size` to inspect its actual geometry.
6. Reject an input such as `touch denied.txt`; confirm it never runs. Close one
   terminal tab and keep using the other. Closing the app/project closes manual
   sessions and their background descendants without stopping the shared container.
7. Run an agent task and leave its native approval pending. Previously approved
   terminal output/control/close remain usable, but new manual input/open and chat
   cannot bypass that approval. The agent output tab retains separate stdout/stderr.

See [implementation, limits and acceptance](workspace-panels.md). Manual terminal
input is approved a complete line/batch at a time; full-screen raw-key applications
such as interactive editors are not supported by this approval-preserving mode.

Live tasks use paid API calls and need a valid key. The latest native AvalAI
Hello World acceptance passed; see [measured results](token-budget-fix.md).
For the token-budget regression, use an empty disposable project and request
`Create hello.py with print("Hello, World!") and execute python3 -B hello.py to verify it.`
Approve the exact execution command after reviewing the created file. Confirm
the plan completes and reported token usage is distinguished from any remaining
unreported reservation. A blocked next call now shows its required reserve and
the remaining task budget; it does not claim the entire 25,000 was consumed.
Skills and bounded correction are implemented; see `phase-4.md` for the accepted
metadata format and limits. In a disposable project, add a relevant Skill under
`.agents/skills/<name>/SKILL.md` and mention its name in the task. Confirm its name
appears in the UI. With a valid provider, a failed check may trigger correction;
each command still requires approval and the original failed check must pass
before successful completion. Passing scripted GUI tests does not establish live
model quality or account access; see `phase-5.md` for observed acceptance evidence.
