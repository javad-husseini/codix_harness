# Testing the current implementation

## Check the saved key without displaying it

Run in Windows PowerShell under the same Windows account used by Codix:

```powershell
$p = Join-Path $env:LOCALAPPDATA 'Codix\secrets\avalai-key.dpapi'
Test-Path -LiteralPath $p
Get-Item -LiteralPath $p | Select-Object FullName,Length,LastWriteTime
```

Expect `True` and a nonempty file. This verifies storage only, not the key's
validity, decryption or AvalAI access. Do not print the file. If absent, repeat
the masked save instructions in [provider setup](git-and-provider.md). Running
PowerShell under a different account changes LOCALAPPDATA and DPAPI identity.

## Checks available now

From the repository folder in PowerShell, with Docker Desktop running:

```powershell
docker exec codix-development python3 -m unittest discover -s tests -v
docker exec codix-development npm run check:desktop
```

Expect 57 passing tests and a successful syntax check. The existing
`codix-development` container must be running. These are development checks,
not a Windows desktop launch or live provider test. The restricted GUI fixture
commands and their sandbox requirements are recorded in `phase-3.md`.

## Manual desktop acceptance once Windows runtime is available

The current repository does not contain a runnable Windows portable artifact or
`runtime/backend/codix-backend.exe`. Native packaging remains pending. Do not
expect `npm run desktop` on the Windows host to work, and do not run project
commands outside Docker. The encrypted Windows key is deliberately not mounted
into Linux test containers.

When the portable artifact is built and verified:

1. Start Docker Desktop and wait for its Linux engine to be ready.
2. Save the encrypted key under the same Windows account and configure
   `CODIX_MODEL` to a Responses/function-calling OpenAI model supported by your
   AvalAI account. Launch the portable executable from that environment.
3. Select a disposable empty project directory without a Dockerfile. Prepare it
   using the default Node.js/Python image. Confirm prerequisite and smoke checks.
4. Submit: "Create sum.py with add(a, b). Verify add(2, 3) == 5 using Python.
   Do not install dependencies or delete files."
5. Confirm a plan appears before file edits. Review the exact Python command in
   the native approval dialog, then approve it. Expect a file, zero exit code,
   ordered completed steps, token accounting and a final report.
6. Submit a separate task asking to delete that file. Reject the native approval
   and confirm the file remains and the task stops.
7. Close/reopen the app and select the same directory. Confirm its project
   container is reused. Task history is not persisted.

Live tasks use paid API calls. Phase 3 stops on a failed command; automatic
correction and Skill loading are still phase 4 work. Passing scripted GUI tests
does not establish live AvalAI compatibility.
