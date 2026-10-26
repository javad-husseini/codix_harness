# Codix — MVP Specification

## 1. Goal and scope
Codix is a Windows portable desktop coding harness. It connects an OpenAI model to a selected project in an isolated Docker environment so it can plan a coding task, edit files, run commands/tests, inspect results, and self-correct within strict limits.

Only the five approved capabilities are in scope:
1. Read, create, edit, and delete project files; run terminal commands and read output.
2. Plan before editing and execute the plan step by step.
3. Load project Skills from `SKILL.md` folders.
4. Produce modular, testable code and self-correct after failures.
5. Ask for human approval before sensitive operations.

No unrelated product features are in scope.

## 2. Approved stack and deployment
- Desktop shell: Electron.
- UI: Next.js + shadcn/ui.
- Backend: Python + LangGraph, launched by Electron and exposed through a local HTTP API.
- Model provider: OpenAI-compatible Responses API through the user-approved AvalAI endpoint `https://api.avalai.ir/v1` by default; official OpenAI is an allowlisted alternative. The model is selected through configuration.
- Provider routing: user-approved direct HTTPS only for the exact AvalAI origin; preserve system proxy behavior for official OpenAI. Keep TLS certificate/hostname verification and redirect blocking enabled; do not change Windows proxy settings.
- Target OS: Windows.
- Distribution: portable folder containing the executable and bundled resources; no installer.
- Prerequisite: Docker Desktop and WSL2 must already be installed. If Docker is unavailable, explain the prerequisite and do not silently fall back to host execution.
- API key: use the user-approved local Git-ignored `.env` in the repository root for development or beside `Codix.exe` in portable mode. Electron reads allowlisted settings and passes keys only to the backend, never the renderer or project-container environment. Explicit backend environment variables remain supported. Commit/package only the empty example; never hard-code, log or commit real credentials. The previous DPAPI store is no longer read.

## 3. Approved execution graph
`Receive task → Plan → Execute plan step → Inspect output/tests → Done?`
- If done: report the result.
- If not done: analyze the failure and enter a correction cycle, then continue execution.
- Sensitive operation: pause before execution and request approval.
- If approval is denied: do not execute the operation; stop or request a revised plan from the user.

Planning must happen before the first code modification. Plan changes that materially depart from the approved plan require human approval.

## 4. Project and container handling
- The user selects a project folder.
- Mount that folder read-write into an isolated Docker container.
- Keep one persistent container per project so its environment can be reused between tasks.
- Enable container network access by default.
- Detect a project `Dockerfile` and use it when present. If absent, use the Codix default image.
- All project commands and generated code must run inside the container, not directly in the host shell.
- If the selected project cannot run in the detected/default environment, explain the limitation and ask the user rather than claiming compatibility.
- Do not automatically install Docker Desktop or WSL2.

The exact Codix default image/toolchain, protected-file patterns, and local HTTP API security/port strategy remain implementation details to document explicitly; do not claim universal project compatibility or silently weaken isolation.

## 5. File and terminal tools
The harness must provide model-callable operations to:
- list/read project files;
- create and edit files;
- delete files when allowed by policy;
- execute a command inside the project container;
- return bounded stdout/stderr and exit status.

Validate paths against the selected project root. Requests to access paths outside that root require approval and must not escape the container mount policy. Bound command output and file content sent to the model to control token use.

## 6. Planning and execution
- Convert each user task into a short, ordered plan of small steps.
- Track step status and relevant command/test results.
- Execute steps in order; inspect results before proceeding.
- Do not modify files before a plan exists.
- Ask the user before materially deviating from the plan.
- Keep model context limited to relevant files, diffs, errors, and test output.

## 7. Skills — instructions only
- Discover project Skills under `.agents/skills/<skill-name>/SKILL.md`.
- Each Skill contains instructions and metadata (`name`, `description`).
- Load only Skills relevant to the current task.
- Skills may guide use of existing harness capabilities; they do not add executable scripts, arbitrary tools, or new permissions in this MVP.
- Do not execute code embedded in a Skill.
- An invalid or unreadable Skill must be skipped and reported when relevant.

## 8. Human approval (HITL)
Request approval before:
- destructive or administrator-level commands;
- deleting files;
- modifying files designated as protected;
- accessing paths outside the selected project root;
- executing a material departure from the current plan;
- other operations classified as sensitive by the command/file policy.

Show the exact command or proposed change and a concise reason before asking. Approval must happen before the action. If rejected, do not execute it. Do not treat general task approval as approval for a later sensitive action.

## 9. Self-correction and token limits
- A correction cycle consists of: inspect failure → identify likely cause → make a targeted correction → rerun relevant checks.
- Maximum: 3 correction cycles per task. After 3 unsuccessful cycles, stop automatic attempts and ask the user how to proceed.
- Hard task budget: 25,000 total model tokens (input + output) per task, across planning, execution, and all correction cycles.
- Track provider-reported token usage where available. If usage cannot be measured reliably, use a conservative estimate and stop before exceeding the budget.
- On reaching the budget, stop further model calls, preserve current changes, and report status, tests, and next options. Never continue the loop without a budget.
- Bound tool output and avoid sending unrelated files or full repository contents to the model.

## 10. Completion and reporting
A task is complete only when its stated acceptance criteria are met and relevant tests pass.
- Run relevant existing tests and the smallest appropriate checks for changed code.
- If no relevant tests or acceptance criteria exist, report that validation is incomplete; do not claim verified success.
- Final report: summary of changes, files changed, commands/tests run and their outcomes, any skipped checks, and unresolved issues.
- Do not claim a command or test ran unless it actually ran.

## 11. Acceptance criteria for the MVP
- The desktop app can start the Python backend and communicate with it through the local HTTP API.
- The user can select a project folder and submit a coding task.
- The graph creates a plan before editing and executes steps using file/terminal tools in Docker.
- The app displays progress, tool output, approval requests, and the final report.
- Sensitive actions pause for approval; rejection prevents execution.
- Skills in `.agents/skills/` can be discovered and their instructions loaded; no Skill scripts execute.
- Failed checks trigger at most 3 correction cycles.
- A task cannot exceed the 25,000-token budget by design; reaching the limit stops automatic execution.
- A persistent Docker container is reused per project, using a detected Dockerfile or the Codix default image.
- The app is distributable as a Windows portable folder and clearly checks for Docker Desktop/WSL2.
