# Phase 4 — instruction-only Skills and bounded correction

Implementation and deterministic verification: 2026-10-26. No commit is created
until explicit user approval. The scope is sections 6–10 of `spec.md`.

## Behavior

Skill discovery runs before model planning through the existing ToolService and
Docker file worker, never by reading arbitrary host paths. Only
`.agents/skills/<folder>/SKILL.md` is considered. Existing secret, link, reparse,
hardlink, root-boundary, file-size and encoding checks still apply.

The minimal frontmatter parser accepts single-line `name` and `description`,
optionally quoted. Names are lowercase letters/digits/hyphens, up to 64 characters.
Descriptions are at most 1,000 characters; bodies at most 4,000. Folded/multiline
YAML descriptions are not supported and are reported/skipped when relevant.
Unknown metadata never registers tools or executable hooks. Code fences and
instructions are passed as text, never evaluated by the loader.

Selection uses explicit Skill names or metadata keyword overlap, with simple
English normalization and a few Persian check/test aliases. It is deterministic,
not a semantic model selector. Discovery considers at most 32 folders, selects
at most three Skills and includes at most 8,000 combined instruction/description
characters. Directory enumeration is capped by the file worker; truncation and
context limits are reported. Unreadable/invalid Skills with relevant folder names
are reported without publishing their contents. Unrelated bodies stay out of the
model context. Loaded names/paths and warnings appear in task state/report/UI;
automatically loaded instruction bodies are not serialized into Skill metadata
or its UI. Explicit file-tool reads retain the existing tool-output visibility.
No Skill can expand the fixed
tool catalog or authorize an operation.

Every failed command enters inspection. Unless it timed out, the graph can start
at most three correction cycles for the entire task. It preserves the failed
command and working directory as the required recheck. Diagnostic failures do not
replace that target. Successful unrelated commands and changed plans cannot
bypass the required passing recheck. A correction can inspect output, edit within
the current plan and propose a new check. Every shell invocation receives a
fresh one-use approval; rejecting it stops the task and preserves current files.

The fourth consecutive failed check (initial failure plus three unsuccessful
correction attempts) stops automatic work. A timeout stops the container and task
immediately. Provider, policy, path and approval errors are not automatically
retried. The existing 40-model-call, graph-transition, context/output and shared
25,000-token limits apply to planning, Skills context and all correction calls.
New tasks reset correction and Skill state; plan replacement does not reset the
task-wide correction allowance. Final acceptance remains a model judgment backed
by recorded command results, not a mathematical correctness guarantee.

## Verification

- `python3 -m unittest tests.test_phase4 tests.test_tasks -q`: 24 tests passed in
  the initial run; the final phase 4 module adds two more regression cases.
- `python3 -m unittest tests.test_phase4 -q`: all 10 phase 4 tests passed.
- Full backend suite initially passed 71 tests; final suite results are recorded
  in the phase 5 report after all added checks.
- `npm run check:desktop` and `npm run build` passed inside Docker.
- The three restricted, networkless GUI suites passed sequentially. The updated
  task suite uses a scripted provider with the real UI, graph, Skill loader,
  file worker and shell: it creates a wrong value, observes a real assertion
  failure, edits the file, obtains a second native approval for the exact same
  command, passes the recheck and displays completion, Skill name and cycle count.
  It also checks both fixture API keys are absent from the renderer environment.

Coverage includes Skill relevance/no code execution, invalid/oversized/linked
files, selection limits, correction success, third-cycle exhaustion, fresh
approvals and replay rejection, denial preserving files, replanning/unrelated
success blocking, original recheck retention, timeout stop, shared token budget
and fresh-task isolation. No new dependency was added.

Changed files: `backend/skills.py`, `backend/tasks.py`, `backend/server.py`,
`app/page.jsx`, `tests/test_phase4.py`, `tests/test_tasks.py`,
`tests/desktop_task_backend.py`, `tests/task-smoke.cjs`, and this report.
