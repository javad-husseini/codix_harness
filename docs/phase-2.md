# Phase 2 — bounded tools, project boundaries and approvals

Status: implemented and verified in Docker on 2026-10-20. Model/task-graph integration is phase 3; native Windows desktop verification remains pending packaging.

## Implementation plan and delivered scope

1. Add a conservative, explicit file/command policy.
2. Execute file operations through trusted standalone workers inside the selected project container.
3. Add plan-presence gates and project/plan-bound approval tickets.
4. Connect the authenticated API and native Electron approval dialog.
5. Test boundary escapes, stale approvals, denial side effects and real Docker workers.

No dependency installation, new npm dependencies or model API calls were needed. Skill contents are not executed and no Skill tools were added.

## Tools and policy

The authenticated catalog at GET /tools/catalog describes list_files, read_file, create_file, edit_file, delete_file, run_command and set_plan. Each has an object argument schema with explicit required fields and no extra properties. These are harness definitions; the model-provider adapter belongs to phase 3.

- All paths are project-relative. Reject absolute paths, traversal, backslashes, drive/UNC/alternate-stream forms, Windows device names, trailing spaces/dots, control characters and noncanonical Unicode. Tildes are conservatively unsupported to block Windows 8.3 short-name aliases from bypassing protected-name checks.
- The host preflight rejects symlinks, junctions/reparse points and hardlinked regular files. It checks canonical containment in the selected root.
- The Linux worker independently opens the root and each parent with directory file descriptors and O_NOFOLLOW. It rejects links, nonregular files and multiple hardlinks. There is no host file-operation fallback.
- Files must be UTF-8 and at most 32 KiB. Directory listing is bounded to 200 entries. Creating parent directories and recursive deletion are not tools in this MVP phase.
- Reads of secret-pattern files are blocked. Known credential patterns and secret-valued environment variables are redacted from file/command results. Secret-file changes use a content digest and byte count in the approval dialog without displaying values.
- Protected targets match the phase 0 categories, case-insensitively and at nested locations: AGENTS.md, .git, .agents/skills, .env variants, key files, .ssh/.aws and documented credential files.
- Unprotected create/edit operations require an active ordered plan. Protected changes and every deletion additionally require approval.
- Every terminal command requires explicit approval. There is no supposedly safe shell/script allowlist; dependency installation, compound commands, interpreters, destructive/admin commands and indirect scripts all pause.
- The approval shows the exact shell program and working directory and explains that its indirect effects may include protected writes, deletion, dependency installation and container/network access. Approval covers that program, not arbitrary later tool requests.
- Outside-root file requests are blocked. Approval cannot authorize new host mounts or an escape from the project boundary.

## Approval and plan lifecycle

POST /tools/propose accepts project_id, name and arguments. It validates the prepared/running container, policy and plan, and returns a proposal with a five-minute ticket.

POST /tools/execute accepts project_id, ticket and a boolean approved flag. The ticket is one-use, scoped to the project and plan version, and refers to backend-owned copies of the arguments. A new proposal invalidates older pending proposals. Forged, expired, cross-project and consumed tickets do not execute.

Electron exposes setPlan and runTool through named preload methods. It fixes project_id from its selected project, validates the method/argument shape, requests the proposal, displays the native dialog when required, and sends the decision itself. The renderer does not receive tickets or an API token and cannot supply an approval flag through the bridge.

The first ordered plan is recorded without a file edit. Replacing any existing plan requires approval. Denial stops subsequent writes/commands until a revised plan is approved. Reads remain available for reporting. Semantic step scheduling and task lifecycle are phase 3; this phase enforces plan presence/version rather than inferring natural-language plan compliance.

File previews bind existence and a content hash. Execution rechecks them and the worker rechecks immediately before replacement. A changed file requires a new operation/approval. The worker stages content in the same opened directory, fsyncs it, and atomically replaces an existing file; creation uses a no-overwrite link operation followed by removal of the temporary name.

## Docker execution and limits

- ContainerGateway revalidates the actual project's mount/isolation settings and running state before tools run.
- File-worker source comes from the trusted backend package, not from a selected-project script or Skill. Docker exec runs python3 -I -c with the request on stdin.
- The terminal bootstrap opens its cwd without following links, fchdir's to it and execs the approved /bin/sh program. Neither command text nor file contents are interpolated into a host shell.
- stdout/stderr capture is capped at 16 KiB per stream for terminal calls, with truncation markers. Input is fed over a pipe. HTTP request size is bounded at 256 KiB.
- Terminal calls have a 120-second timeout. A timed-out call stops the task and explicitly stops the project container, since killing the Docker CLI alone does not stop exec descendants. The persistent container is retained; reprepare/replan is needed to continue.

## Verification performed

All project commands ran inside Docker. No project Python/npm execution occurred on the Windows host.

| Command/check | Actual outcome |
| --- | --- |
| docker exec codix-development python3 -m unittest discover -s tests -v | 34 tests passed in the final run |
| docker exec codix-development python3 -m unittest tests.test_tools.BoundaryTests -v | 7 targeted checks passed after adding the Windows 8.3 alias restriction |
| docker exec codix-development npm run check:desktop | Passed |
| Electron tests/approval-smoke.cjs in the restricted GUI-check container | Passed |
| docker exec codix-phase1-runtime python3 -m tests.container_workers_smoke | Passed on the actual Windows project bind mount |
| npm run test:desktop in the restricted GUI-check container | Passed; phase 1 bridge/startup regression plus invalid/unprepared tool calls |

Backend checks include portable path aliases, traversal, symlink parents/targets, hardlinks, simulated Windows reparse attributes, protected/secret patterns, stale hashes, one-use/expired/forged/cross-project tickets, immutable proposed arguments, plan gates/replacement, rejection stopping work, output bounds/redaction, command timeout stopping its container, schema checks and Docker-exec argument construction. Existing authentication/startup/lifetime tests also pass.

The approval GUI test uses the real Electron main/preload and real authenticated backend HTTP/ToolService. Its backend fixture replaces Docker preparation and uses a temporary test filesystem inside the test container. The native dialogs are automated with explicit approve/reject responses. It verifies that:

- approving a protected-file diff changes that file;
- rejecting deletion leaves the file unchanged;
- rejection stops a subsequent edit;
- approving a revised plan resumes the workflow;
- rejecting a command means its gateway is never called.

This fixture can only be launched by the test harness's child-process substitution; production has no environment/configuration switch enabling it.

The separate real-worker check executes the production standalone workers in codix-phase1-runtime. It creates/reads/edits/deletes only .verification/phase2-worker-check.txt, refuses to overwrite a preexisting target, rejects a stale hash and traversal, and runs printf phase2-command. The test file was removed successfully.

GUI tests use the previously approved phase 1 setup: --init, network none, all capabilities dropped, no-new-privileges, read-only project/dependency/root mounts, bounded temporary filesystems, and seccomp=unconfined for Chromium user namespaces. The renderer sandbox stays enabled. No Docker socket is mounted. Product project-container isolation is unchanged. D-Bus/GPU diagnostics occurred on stderr; assertions exited successfully.

## Skipped checks and remaining limits

- Native Windows execution and real NTFS junction races are not tested here. Reparse-point rejection has a simulated attribute test; file-worker operations were tested on a real Windows bind mount.
- No new Next.js build was run: page/layout/style/dependencies did not change, the phase 1 export was reused, and both GUI tests passed against it.
- Model calls, task progress/step execution and self-correction are not implemented by this phase. There is no added manual terminal/file-editor UI; the controlled bridge is ready for phase 3 task execution.
- Custom project images need Linux Python 3 and the required no-follow/directory-descriptor APIs. Missing support fails closed; there is no host fallback.
- Files larger than 32 KiB, binary files, directory creation/deletion and symlink/hardlink operations are unsupported by these file tools. An approved shell command is a separate sensitive operation.
- Approval for an arbitrary program authorizes its indirect effects inside the existing container policy. This is not a static proof of script behavior or a per-file sandbox inside an approved program. There is no automatic shell execution without approval.
- Credential redaction is defense in depth for known values/patterns, not a universal detector for arbitrary credentials, encodings or script/network exfiltration. Do not treat a command approval as an assurance that the program is safe.
- The host preflight and Linux no-follow worker reduce path races; an adversarial external host process concurrently renaming/replacing directories is not a supported concurrency model. Exclusive ownership/snapshot isolation would need a separately approved runtime design before claiming that stronger guarantee.
- The previous project-Dockerfile build-context snapshot limitation remains. Phase 2 does not change that phase 1 lifecycle.

## Changed files

- Added backend/policy.py, backend/container_files.py, backend/container_terminal.py and backend/tools.py.
- Updated backend/processes.py and backend/server.py.
- Updated desktop/main.cjs and desktop/preload.cjs.
- Added tests/test_tools.py, tests/desktop_backend.py, tests/approval-smoke.cjs and tests/container_workers_smoke.py.
- Updated tests/desktop-smoke.cjs and package.json.
- Updated README.md; added docs/phase-2.md.

spec.md, AGENTS.md, Skills and the phase 0 decisions were not modified. No additional dependencies were added.
