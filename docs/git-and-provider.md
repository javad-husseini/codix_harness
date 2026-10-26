# Git and AvalAI configuration

## Repository and phase commits

The repository uses `main` and origin
`https://github.com/javad-husseini/codix_harness.git`.
Implement and test each phase, report results, then wait for explicit approval
before committing. Starting another phase does not approve a commit. Push needs
an explicit request.

## Local .env configuration (current)

The user approved replacing DPAPI with a local `.env` file. It is plain text and
ignored by Git; `.gitignore` is not encryption. Keep the filled file private.
Only the empty `.env.example` belongs in version control.

- Development: edit `.env` at the repository root.
- Portable Windows: edit `.env` beside `Codix.exe`, currently
  `dist/Codix-MVP-win32-x64/.env`. The root development file is not read in this mode.
- Fill `AVALAI_API_KEY`, save and restart Codix. For the default AvalAI endpoint,
  leave `OPENAI_API_KEY` empty. These are alternatives, not two required keys.
- Defaults in the template: `OPENAI_BASE_URL=https://api.avalai.ir/v1` and
  `CODIX_MODEL=gpt-5.4-nano`. The model must be available on your account and
  support Responses/function calling; the template is not a claim of availability.

Electron reads only `AVALAI_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` and
`CODIX_MODEL` from that exact file, without executing shell expansions. File
values override inherited variables, including empty values; a missing file
retains explicit environment-based development compatibility. `CODIX_API_PORT`
remains a process environment setting, defaulting to 43121.

Keys are passed to the backend child only. They are not added to Electron's
process environment, renderer or project-container environment. The file tools
already block reads of `.env` files. As with any plaintext secret in a selected
project, an explicitly approved arbitrary shell command can read mounted files;
do not approve commands that expose it. Development container mounts can include
the local file, while normal project execution receives no key environment.

The previous `%LOCALAPPDATA%/Codix/secrets/avalai-key.dpapi` is no longer read,
modified or deleted. An empty `.env` does not fall back to that old key.
The backend still accepts explicit `AVALAI_API_KEY` or `OPENAI_API_KEY` when
launched directly in an approved backend/development environment.

The build never copies the repository `.env`. It copies `.env.example` with
empty key fields and creates the portable `.env` only if absent. Rebuilding
preserves an existing portable `.env`; do not distribute a filled file.
The artifact audit rejects a filled `.env` in a distributable folder.

## Endpoint and budget

Only `https://api.avalai.ir/v1` and `https://api.openai.com/v1` are accepted;
redirects remain blocked. Direct HTTPS is scoped to the exact AvalAI origin;
TLS verification stays enabled and Windows proxy settings are unchanged.

Task budget remains 25,000 total tokens. AvalAI text/function routes beginning
`gpt-`, `o1`, `o3` or `o4` reserve compact UTF-8 request bytes plus the existing
4,096-token input allowance and 2,048-token output cap. JSON ASCII escapes and
whitespace no longer inflate that estimate. It remains an upper estimate, not
an exact tokenizer. Actual valid provider usage releases unused reservations;
missing, partial or inconsistent usage keeps them. The UI separates reported
usage from unreported reservations and explains the next-call requirement.
Other model routes are refused. The official OpenAI route continues using its
input-count endpoint. There is no automatic retry after authentication or
transport failure. See [budget regression results](token-budget-fix.md).

See [verification and changed files](env-configuration.md) and
[manual acceptance](manual-testing.md). A filled key and supported model are
required for live acceptance. No real key is included in the templates.
