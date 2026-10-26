# Premature token-budget stop: correction and verification

The user reported that a Persian Hello World task stopped at 13,786/25,000
before creating a file. The local adapter reserved ASCII-escaped, whitespace-heavy
JSON bytes plus 4,096 input allowance and 2,048 output tokens before every call.
A new reservation could exceed the remaining budget even when accounted usage
was below 25,000. The old UI incorrectly described this as reaching the ceiling.

## Changes

- `backend/provider.py`: compact UTF-8 serialization is used both for the actual
  transport and the byte estimate. The existing 4,096 allowance, 2,048 output cap
  and 25,000 task ceiling are preserved. There is no characters/4 heuristic or
  extra model request after a failed reservation.
- Valid usage in Responses form, compatibility prompt/completion form, or an
  aggregate total is reconciled. Partial/negative/boolean/conflicting usage
  retains the reservation. Reasoning breakdowns are not added a second time.
- Budget snapshots distinguish provider-reported tokens from unreported reserved
  tokens. A refusal supplies the remaining budget and the next-call requirement.
- `backend/tasks.py`: planning sends only the forced planning tool. The initial
  directory summary is limited to 40 names/1,600 UTF-8 bytes with an explicit
  truncation flag; an explicit directory tool call allows 200 names/4,000 bytes.
  Model observations stay structured and bounded, without re-encoding JSON
  strings or repeating the plan as tool output. File paths remain in observations.
- Simple file tasks are directed to one step covering creation and actual
  execution. An explicit phase/plan-recorded marker and execution-stage tool
  description tell the model to continue the existing plan. Replacing a plan
  still requires approval; command/deletion/secret boundaries are unchanged.
- `app/page.jsx`: the status says the next call cannot fit the budget; it shows
  reported usage, outstanding reservations and the required/remaining amounts.
- `tests/test_token_budget.py`: seven regression tests, including a Persian task,
  large Unicode root directory, real file creation/Python execution inside Docker,
  actual adapter reservation logic and mocked provider responses. That test
  completes in four model calls with 5,520 synthetic reported tokens; this number
  is a fixture, not measured AvalAI usage.
- GUI fixtures test both successful correction and a subsequent stop at 20,040
  reported tokens with 4,960 remaining and 12,048 needed. Fixtures wait for the
  initial backend connection to avoid racing the UI startup health request.
- `packaging/windows-hello-smoke.ps1`: native built-backend acceptance using the
  local `.env`, a disposable project and guarded approval of only a literal
  Hello World print file and `python3 -B hello.py`. No real key is printed or sent
  to a project container. Other sensitive proposals are rejected.
- `packaging/audit-portable.py --local-config` audits installed application
  resources without reading a user's runtime `.env`. Default distribution audit
  continues refusing a filled `.env`; the empty example is always checked.

## Source and remaining limits

AvalAI currently marks exact preflight counting unavailable and recommends local
conservative estimates plus usage reconciliation:
[AvalAI token-counting guide](https://docs.avalai.org/en/guides/token-counting).
The official OpenAI route uses its full-input counting endpoint:
[OpenAI counting guide](https://developers.openai.com/api/docs/guides/token-counting).
No claim of exact local tokenization is made. A large context/Skill or missing
usage can still legitimately exhaust the conservative budget. Provider adherence
to its output cap/count/usage contract remains required.

## Checks

- Docker `python3 -m unittest discover -s tests -v`: 79 passed.
- Docker `npm run check:desktop`, `npm run test:config`: passed (two config tests).
- Docker `npm run build`: passed; static UI rebuilt.
- Docker `npm run test:desktop`, `npm run test:approvals`, `npm run test:task`:
  passed after fixing a test startup race; includes the displayed budget amounts.
- After the execution-phase clarification, the relevant graph/correction/budget
  tests passed again (33 tests), and the final listing bounds passed (seven tests).

Early native live probes reached AvalAI with valid usage, but asked to replace an
already recorded plan before writing the file. The acceptance helper rejected
those proposals. The execution-phase clarification addresses this observation.
Final artifact/native acceptance:

- Wine/PyInstaller Windows backend build passed inside Docker, using the final
  stable source. `node packaging/build-portable.cjs --mvp` assembled the UI/app;
  the final frozen backend was refreshed into the same portable folder inside
  Docker. The existing local `.env` was preserved.
- Docker `python3 packaging/audit-portable.py --mvp --local-config`: passed.
  The local runtime secret file was excluded without reading its contents;
  packaged app resources, empty example and final backend identity were checked.
- Native `packaging/windows-ui-smoke.ps1 -ApplicationExecutable <MVP Codix.exe>`:
  passed; the window rendered and connected to the final backend.
- Native `packaging/windows-hello-smoke.ps1 -BackendExecutable <MVP backend>`:
  **passed against real AvalAI with the user's local configuration**. The Persian
  request created only `hello.py`, obtained one guarded approval, ran
  `python3 -B hello.py` in the actual Docker project container, and verified
  `Hello, World!` with exit code 0. Status `completed`, four model calls,
  **3,353 provider-reported tokens**, zero unreported reservations, zero correction
  cycles, limit unchanged at 25,000. The helper stopped/removed only its disposable
  container; test files remain under ignored `.verification/`.

No dependency installation, commit or push was performed. Tests of other provider
accounts/models or large real projects were not performed. Their usage can vary;
the conservative reservation may still stop before the displayed ceiling if the
next call cannot fit. Previous full phase 5 negative-startup/container-reuse checks
were not repeated because those code paths did not change.
