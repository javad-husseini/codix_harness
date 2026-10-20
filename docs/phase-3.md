# Phase 3 — Responses API, LangGraph and the task UI

Status: implementation and deterministic Docker verification complete on 2026-10-20. Live OpenAI acceptance is pending user configuration; no real API inference call was made.

## Delivered behavior

- User selects/prepares a project, enters a task and acceptance criteria, and starts it from the desktop UI.
- A LangGraph StateGraph executes Plan → Act → Apply → Inspect. Only one task runs at a time. Steps advance in order; failed commands or incomplete step acceptance stop later work.
- Planning can only return set_plan. An invalid planner cannot edit. A new task clears the previous plan/pending approvals instead of inheriting authorization.
- Actual file/terminal operations use the phase 2 ToolService and Docker gateway. There is no host execution fallback.
- Protected changes, every shell command, deletion and plan replacement suspend before execution. Native Electron dialogs submit the decision; rejection stops the task without another model call.
- The UI polls task state and displays plan/step status, bounded progress/tool output, token accounting and a final report with changed files, actual command results, skipped validation and unresolved issues.
- OpenAI model selection is configuration-driven. REST requests use the standard Python library and a fixed HTTPS OpenAI origin; no custom provider endpoint or additional OpenAI SDK dependency was introduced.

Automatic self-correction and Skills discovery/loading remain phase 4. Phase 3 performs zero correction cycles and never retries a failed inference request automatically.

## Configuration

Set OPENAI_API_KEY and CODIX_MODEL in the process environment used to launch the desktop app. CODIX_MODEL must name a model available to the account that supports Responses function calling. There is deliberately no silently chosen model.

- Do not paste an API key into chat or the task input; do not commit it to the repository.
- Electron captures/removes the provider key before app readiness, passes it only to the backend environment, and does not forward it to project containers. The launch authentication token still travels privately over stdin.
- The final GUI test used the literal, nonsecret value fixture-not-real-key: the backend asserted receipt, and the main-process test inspected the renderer process environment to verify OPENAI_API_KEY was absent.
- Missing key/model fails task start with a setup message; project selection and health checks remain usable.
- CODIX_API_PORT remains fixed/configurable, default 43121.
- LangGraph's optional third-party tracing is explicitly disabled. Requests and raw provider errors/headers/bodies are not logged or sent to the renderer.

The current host environment was checked by boolean presence only: neither OPENAI_API_KEY nor CODIX_MODEL was configured. No real key was read into tool output and no live inference was attempted.

## Token and execution bounds

Before each model request, the provider sends the same model, input, instructions, tool schemas and tool choice to POST /v1/responses/input_tokens. The returned exact input count plus a 2048-token output allowance must fit the remaining 25,000-token task budget before generation is sent. Input-count failure stops without inference.

Generation uses max_output_tokens=2048, parallel_tool_calls=false, store=false and truncation=disabled. Only one completed, bounded function call is accepted. No previous_response_id or server conversation adds hidden history.

Provider-reported input/output usage reconciles the reservation after a successful response. Missing/unusable usage retains the entire reserved upper bound. An ambiguous network failure also retains the reservation and stops, without retry. An over-reservation usage result stops further automatic work.

This relies on the provider honoring the exact preflight count and output cap. The cap includes non-visible generated tokens according to the [official OpenAI token-counting guidance](https://developers.openai.com/api/docs/guides/token-counting). Account-specific availability and live response compatibility are not established by mocked tests.

Additional bounds: at most 40 model calls, 260 graph transitions per invocation, a 4000-character task, 20 plan steps, four recent tool observations (6000 characters each), 50 progress entries, bounded command report output and existing phase 2 file/terminal limits. On budget exhaustion no further tool action from a new model response executes; existing files/report evidence are preserved.

## API and approval lifecycle

- POST /tasks/start: prepared project_id and request; starts a daemon worker after configuration/project validation.
- POST /tasks/status: current task_id; returns an immutable public snapshot while the worker runs or waits.
- POST /tasks/decide: task_id, one-use decision_id and boolean decision. A forged/stale decision cannot resume the graph.
- Manual project/tool mutations are locked while a task is active or awaiting approval. This prevents an independent proposal from invalidating/replacing the task's pending operation.
- Electron exposes only startTask(text) and taskStatus() for this flow. It retains task identity, consumes pending native approvals itself and strips approval details/decision IDs before returning task state to the renderer. The renderer supplies neither an approval flag nor a free-form HTTP request.
- Task state is in memory; no restart recovery or additional persistence system was added.

The graph pauses by ending the current invocation with an awaiting-approval state, then resumes at Apply with the existing proposal after the decision. Resume does not repeat the preceding model call or completed actions.

## Completion semantics

Completion requires all planned steps to be finished with model-assessed acceptance and at least one actual successful command/check. A failed command stops without correction; no executed check produces incomplete validation. A model's finish-step summary never fabricates command/test records.

Acceptance assessment remains a model judgment; a zero exit code by itself does not mathematically establish requirements or test relevance. The prompt requires relevant existing checks, and the report retains actual commands/output for review. The UI does not claim verified success when no command was run.

## Dependencies and environment

- backend/requirements.txt pins LangGraph 1.2.16.
- backend/requirements.lock.txt records the full resolved Python package versions generated inside Docker.
- docker/development.Dockerfile installs that lockfile; codix-development:phase3 was built successfully. Existing codix-development also received these packages inside its container for backend checks.
- No npm dependencies were added. package.json adds test:task.
- Development checks ran in Docker only. The project execution image remains Node.js 22/Python 3.12; backend graph libraries belong to the backend/development environment, not arbitrary user projects.

## Commands and results actually observed

| Command/check | Outcome |
| --- | --- |
| docker exec --user root codix-development python3 -m pip install -r backend/requirements.txt --disable-pip-version-check | Passed; installation only inside container |
| pip freeze inside codix-development → backend/requirements.lock.txt | Recorded resolved versions |
| docker build --file docker/development.Dockerfile --tag codix-development:phase3 . | Passed |
| docker exec codix-development npm run build | Passed; updated static UI export |
| docker exec codix-development npm run check:desktop | Passed |
| docker exec codix-development python3 -m unittest discover -s tests -v | 50 tests passed in final run |
| npm run test:desktop, then test:approvals, then test:task in one restricted GUI-check container | All three passed sequentially after the restart fix |
| npm run test:task with the nonsecret fixture key in a fresh restricted container | Passed, including renderer-environment key isolation |

The GUI environment retains the separately approved phase 1/2 constraints: --init, no network, all capabilities dropped, no-new-privileges, read-only application/dependency/root mounts, bounded tmpfs and seccomp=unconfined for Chromium's user-namespace sandbox. Renderer sandbox remains enabled; product project-container policy is unchanged. No Docker socket is mounted. D-Bus/GPU diagnostics on stderr did not fail assertions.

The task GUI fixture uses the real UI, IPC, authenticated HTTP API, LangGraph, ToolService, file worker and an actual shell check inside the temporary Docker container. Only the provider and project-preparation/gateway transport are fixtures. Its harness sets a fixed nonsecret fixture key, so it never uses a user's real credential. The task creates created.py in a temporary test root, then runs python3 -c with an import/value assertion after the native approval stub approves that exact command. It verifies ordered completion and the visible report. It is not a real OpenAI or native Windows end-to-end test.

Backend coverage includes plan-before-edit, ordered steps, one active task, manual-tool locking, approval denial/replay/forgery, revised plans, fresh task authorization, actual/conservative token accounting, count failure, no retry after ambiguous inference, malformed/parallel/incomplete responses, budget stop preserving changed files, action limits, failure stopping without correction, and missing checks producing incomplete status. Prior phase tests also pass.

## Restart issue found and fixed

The initial sequential GUI regression passed the first app but the second could not start its backend. Waiting for child exit alone was insufficient: the Unix HTTP socket's no-reuse setting prevented immediate rebinding after the prior connection. The server now permits Unix restart after TIME_WAIT while retaining active-listener rejection, and uses exclusive address binding on Windows. Electron waits for backend exit on normal shutdown, with a three-second kill fallback.

A dedicated immediate-restart test and existing occupied-port tests passed. All three GUI suites then passed in one container. Windows exclusivity follows [Microsoft's socket-option guidance](https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse); native Windows behavior is still untested.

## Skipped checks and remaining limitations

- Live OpenAI task execution is unverified because key/model are absent. Deterministic provider tests and a fully exercised local task flow do not establish model/account/network compatibility or real coding quality.
- No paid model request was sent. Do not interpret the GUI fixture's success as a real-model success.
- Native Windows desktop execution, Windows socket behavior and the portable PyInstaller artifact remain packaging work.
- Automatic correction cycles and instruction-only Skills loading remain phase 4. Failures stop immediately in phase 3.
- No task persistence/resume across application restart, task cancellation feature, or parallel task execution was added.
- Context is intentionally small; oversized/truncated file results may require a smaller task. No automatic repository-wide ingestion occurs.
- Prior phase 2 limits on arbitrary approved shell programs, credential redaction, adversarial host-directory races and Dockerfile build-context snapshots remain. The graph does not bypass those policies or solve those stronger threat models.

## Changed files

- Added backend/provider.py and backend/tasks.py.
- Added backend/requirements.txt and backend/requirements.lock.txt.
- Updated backend/server.py and backend/tools.py.
- Updated desktop/main.cjs and desktop/preload.cjs.
- Updated app/page.jsx and docker/development.Dockerfile.
- Added tests/test_tasks.py, tests/desktop_task_backend.py and tests/task-smoke.cjs.
- Updated tests/desktop-smoke.cjs and tests/test_lifecycle.py.
- Updated package.json and README.md; added docs/phase-3.md.

spec.md, AGENTS.md, project Skills and phase 0 decisions were not changed.
