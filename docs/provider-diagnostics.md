# Provider stop and Windows TLS diagnosis

The user reported a stopped task with no changed files or command execution and
9,658 reserved tokens. A native read-only file-list check succeeded. A separate
live connectivity probe through the Windows backend reproduced a TLS certificate
verification failure with 9,530 reserved tokens. These are preflight reservations,
not evidence of billed model usage; the failure occurred during TLS setup.

The frozen Python transport now retains the default Windows trust store and adds
the already locked `certifi` public CA bundle. Hostname checking and required TLS
verification remain enabled. `certifi` is now an explicit backend requirement;
its installed/locked version is unchanged. No custom unverified SSL context or
credential-bearing request logging was introduced.

Provider transport failures now use fixed messages for authentication, permission,
model/endpoint not found, rejected requests, quota, rate limits, server/network,
TLS, redirects and malformed responses. A bounded HTTP error body is inspected
only for known quota codes; its text, headers, URL and credentials are never
published. Incomplete or invalid tool responses also get fixed diagnostics.
The task graph preserves these messages and explains reserved versus actual
usage; unknown internal/tool failures report a fixed checkpoint without raw
exception text. No automatic provider retry was added.

An updated artifact is assembled separately at
`dist/Codix-win32-x64-updated/Codix.exe` so a running original app is not overwritten.
Close the original app before launching the update on the default API port.
Build with `node packaging/build-portable.cjs --updated` inside the approved
builder. Run `python3 packaging/audit-portable.py --updated` inside Docker.

Changed files: `backend/provider.py`, `backend/tasks.py`,
`backend/requirements.txt`, `tests/test_credentials.py`, `tests/test_tasks.py`,
`packaging/build-portable.cjs`, `packaging/audit-portable.py`,
`packaging/windows-smoke.ps1`, `packaging/windows-ui-smoke.ps1`, and this document.

Verification: all 62 backend tests passed inside Docker, including fixed
HTTP/TLS/quota diagnostics, secret-bearing error-body suppression, graph report
propagation and a verified TLS context with public roots. Startup-test deadlines
were aligned to Electron's existing 15-second deadline after repeated 5-second
test-only timeouts under Docker/build I/O load; the final 62-test run passed.
The updated portable audit, whitespace check and native connected-UI test passed.

Adding public CA roots alone did not resolve the live probe. A credential-free
Windows-system TLS handshake directly to `api.avalai.ir` passed with no certificate
policy errors. A direct HTTPS GET to `/v1/models` returned the expected 401 without
credentials; the default system-proxy request timed out. Windows system proxy is
enabled. The proxy route is therefore the leading suspect, not a proven API-key
or account error. No successful model response has been obtained.

The user approved direct HTTPS only for AvalAI while preserving Windows proxy
settings and certificate verification. The provider now installs an empty
ProxyHandler only for the exact allowlisted `https://api.avalai.ir/v1` origin;
official OpenAI retains system proxy behavior. No global proxy settings or TLS
verification were changed. TLS certificate failures and other TLS negotiation
errors are distinguished, and only numeric verify codes/fixed reason labels can
be displayed. Raw SSL exception text is suppressed.

An intermediate portable assembly collided with a concurrently running native
test executable; assembly and UI verification were then run sequentially and
both passed. Generated artifacts remain ignored. No commit or push was made.

## Approved direct-route outcome

With the approved AvalAI-only direct route, the native live probe reached AvalAI
and returned HTTP 401 (API credential rejected), replacing the earlier TLS failure.
Neither `AVALAI_API_KEY` nor `OPENAI_API_KEY` was present in the probe environment;
the backend therefore used the private Windows DPAPI store. No key was displayed,
logged, copied into Docker or placed in the portable folder. The user must replace
or re-enter a valid API key before a successful model task can be verified.

The direct-route change passed the 63-test backend suite. The final updated-folder
artifact audit, 12 provider/credential tests, whitespace check and native connected
UI check also passed. The updated backend identity matches the freshly frozen
output. Native Docker/WSL, spaced Windows project path, read-only listing and
Node/Python smoke passed during the live probe. No successful model response or
end-to-end coding task is claimed; the API still rejects the current credential.

Additional files changed for this approved route: `spec.md` and `README.md`.
