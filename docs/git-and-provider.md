# Git and AvalAI configuration

## Repository and phase commits

The local repository uses branch `main` and origin
`https://github.com/javad-husseini/codix_harness.git`.
After each phase, implement and test its approved scope, report changes and test
results, then wait for explicit user approval before committing. Starting another
phase does not approve a commit. Push requires a separate explicit instruction.
Phases 0–3 already coexist in the initial working tree; do not invent historical
phase commits. No commit or push was performed during this setup.

## Private Windows key

The native Windows backend reads:
`%LOCALAPPDATA%\Codix\secrets\avalai-key.dpapi`.
The directory was created outside the repository and Docker project mount with
inherited access removed and access granted to the current Windows account and
SYSTEM. Save your actual key from a Windows PowerShell window using masked input:

```powershell
$k = Read-Host 'AvalAI API key' -AsSecureString
$k | ConvertFrom-SecureString | Set-Content -LiteralPath "$env:LOCALAPPDATA\Codix\secrets\avalai-key.dpapi" -Encoding ascii -NoNewline
Remove-Variable k
```

Do not paste the key into chat, project files, `.env`, command arguments or Git.
This creates ciphertext protected by the current user's Windows DPAPI, without
a separate encryption password. Other processes running as the same Windows user
and administrators remain within the trust boundary; this is not protection
against a compromised Windows account. See [Microsoft's secure-string guidance](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/convertfrom-securestring).
The backend rejects credential-store links/reparse points, limits file size and
clears the native decrypted buffer after copying the key. Python still holds the
key in backend memory to authenticate requests. It is never sent to the model,
renderer or selected project container.

For explicitly configured backend development, `AVALAI_API_KEY` takes precedence
over compatible `OPENAI_API_KEY`, followed by the native Windows store. Linux
containers do not read that store; do not mount it into a project container.
Electron removes both key variables before starting renderers. `.env*`, `*.dpapi`
and `.secrets/` are ignored by Git/build context; tool policy blocks DPAPI files.

## Endpoint, model and budget

Default endpoint: `https://api.avalai.ir/v1`. `OPENAI_BASE_URL` can select that exact
URL or `https://api.openai.com/v1`; other destinations and redirects are blocked.
Set `CODIX_MODEL` to an OpenAI model identifier available on your AvalAI account
before launching the desktop app. No model or real key has been selected for you.
The app uses `/responses` with function calling; choose a model supporting both.
See [AvalAI API introduction](https://docs.avalai.ir/en/api-reference/introduction).

AvalAI's [token-counting documentation](https://docs.avalai.org/en/guides/token-counting)
currently marks `/responses/input_tokens` as not implemented. The adapter therefore
supports conservative budgeting for text/function calls on `gpt-`, `o1`, `o3` and
`o4` model routes: serialized request bytes plus 4,096 input allowance, and 2,048
reserved output tokens. It reconciles valid response usage and retains the full
reservation if usage is absent. This may stop earlier than exact counting; other
model routes are refused. Official OpenAI continues to require its exact count
endpoint. The task limit remains 25,000 tokens; ambiguous failures are not retried.

Native Windows packaging remains pending, so the DPAPI store is ready for the
native backend but is deliberately unavailable to Linux GUI fixtures. No real API
request or native Windows decryption has been performed. Tests use fake credentials
and mocked DPAPI calls; they cannot verify account access or Windows interoperability.

## Verification

Changed files: `AGENTS.md`, `spec.md`, `.gitignore`, `.dockerignore`,
`docker/development.Dockerfile`, `backend/credentials.py`, `backend/provider.py`,
`backend/policy.py`, `desktop/main.cjs`, `tests/test_credentials.py`,
`tests/test_tasks.py`, `tests/task-smoke.cjs`, `tests/desktop_task_backend.py`,
`README.md`, and this document. Git metadata and the private Windows directory
were also created. Docker verification passed: `python3 -m unittest discover -s
tests -v` (57 tests), `npm run check:desktop`, `npm run test:desktop`,
`npm run test:approvals`, and `npm run test:task`. The task GUI check confirms both
key variables reach only the backend and are absent from the renderer environment.
`git check-ignore` confirms `.env`, `.env.local`, `example.dpapi` and `.secrets/key`
are excluded. `git ls-remote origin` succeeded with no advertised refs (empty
remote). `git diff --check` returned success, but the new repository has only
untracked source files, so it does not provide a tracked-diff whitespace check.
No UI build or development-image rebuild was needed/run for this configuration
change; Git was installed in the existing development container and added to its
Dockerfile for future builds. GUI fixtures emitted environment DBus/GPU warnings
but all exited successfully.
