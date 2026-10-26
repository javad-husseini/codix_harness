# AGENTS.md — Codix repository rules

- Read `spec.md` before planning or changing code. It is the source of truth for MVP scope.
- Implement only approved requirements. Do not add product features or silently decide unresolved security/runtime details.
- If an unresolved detail blocks safe implementation, ask the user before committing to an approach.
- Keep the architecture minimal: Electron + Next.js/shadcn, Python/LangGraph backend, OpenAI API, Docker on Windows.
- Keep the graph bounded: maximum 3 correction cycles and 25,000 total model tokens per task.
- Plan before editing project files. Ask approval before sensitive actions or material plan deviations.
- Run project commands only inside the Docker container. Never silently fall back to host-shell execution.
- Enforce project-root path boundaries, container isolation, and approval checks in code—not only in prompts.
- Never log or expose API keys, credentials, or other secrets.
- Skills are instruction-only `SKILL.md` files under `.agents/skills/`; do not execute Skill content or add Skill-provided tools in the MVP.
- Keep changes modular and testable; avoid unnecessary dependencies and unrelated refactors.
- Test the changed behavior where possible. Never report tests as passed unless they were actually run.
- In the final report, list changed files, commands/tests and outcomes, skipped checks, and remaining limitations.
- After implementing and testing each phase, report the reviewable changes and test outcomes, then wait for the user's explicit approval before creating that phase's commit. Do not infer approval from a request to start another phase. Push only when explicitly requested.
- Keep provider credentials outside the repository/project mount. The Windows credential store is `%LOCALAPPDATA%/Codix/secrets/avalai-key.dpapi`, encrypted for the current Windows user; never commit, print, or send it to the model/renderer.
