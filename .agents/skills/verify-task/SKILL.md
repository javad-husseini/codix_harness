---
name: verify-task
description: Use when checking whether a coding task is complete; review relevant changes and run the smallest relevant available checks.
---

# Verify a coding task

1. Compare the implementation with the task requirements and current plan.
2. Inspect the changed files and diffs; do not read unrelated files without a reason.
3. Identify the smallest relevant existing tests or validation commands.
4. Run checks only inside the approved project container.
5. If a check fails, report the relevant error and use the harness correction workflow; never exceed its 3-cycle or token budget.
6. If no suitable tests exist, state that verification is incomplete.
7. Summarize changed files, checks run, outcomes, and unresolved issues.

This Skill is instructional only. It does not grant new tools or permissions and must not contain or execute scripts.
