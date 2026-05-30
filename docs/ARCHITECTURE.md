# M365 Guardian — Architecture

> Conceptual architecture and engineering rationale for M365 Guardian. This document explains
> *how the system is built and why*; it is intentionally not a deployment runbook. Provisioning,
> credential wiring, and operational procedures are maintained privately. For evaluation or
> licensing inquiries, please get in touch (see the repository owner's profile).

M365 Guardian is an LLM-powered Microsoft 365 administration assistant for SMB IT technicians.
A natural-language request ("reset Jane's password", "who hasn't enrolled in MFA?") is turned into
**audited, human-approved** actions against Microsoft Graph and Exchange Online.

## High-level shape

```
┌──────────────────────────────────────────────────────────────────┐
│                          M365 GUARDIAN                            │
├──────────────┬───────────────┬───────────────┬──────────────────┤
│  Teams Bot   │   Web Chat    │  Timer Func   │   REST API        │
│  (Bot Fwk)   │   (aiohttp)   │  (Az Func)    │   /api/chat       │
├──────────────┴───────────────┴───────────────┴──────────────────┤
│                     LLM Orchestration Layer                       │
│         LiteLLM (Anthropic / Azure OpenAI / OpenAI / xAI)        │
│                  Tool calling + structured output                 │
├───────────────────────────────────────────────────────────────────┤
│                          Tool Executor                            │
│        Routes model tool-calls → service methods; server-          │
│        enforced write-confirmation gate; audit on every op         │
├──────────────┬──────────────────────────┬──────────────────────┤
│  Graph API   │     Report Service        │    Audit Service       │
│  (msgraph)   │   10 security checks       │   (Cosmos DB)          │
├──────────────┴──────────────────────────┴──────────────────────┤
│        Microsoft Graph  ·  Exchange Online (PowerShell sidecar)   │
└───────────────────────────────────────────────────────────────────┘
```

## Request lifecycle

1. A message arrives from **Teams** (`/api/messages`, Bot Framework `CloudAdapter`) or the
   **web chat** (`/api/chat`, Entra ID-authenticated session).
2. `LLMService` runs a tool-calling loop (LiteLLM, provider-agnostic).
3. Each tool call is dispatched by `ToolExecutor`, which validates arguments (pydantic, per-tool
   models) and enforces the **write-confirmation gate** before any mutating call.
4. Reads return immediately. Writes pause and surface a human **Approve / Cancel** control; only an
   in-code-validated approval token releases the *stored* action for execution.
5. Every operation is written to an append-only **audit** store with who/what/when and the transcript.

## Design pillars

### Provider-agnostic LLM
All model access goes through LiteLLM, so the provider is a config switch (xAI/Grok, Anthropic,
Azure OpenAI, OpenAI) with no code change. Temperature is kept low for reliable tool-calling.

### Schema ↔ executor lockstep
The tool catalog is defined once as JSON schemas and mirrored exactly by the executor's handlers
and the validation models. Names, required args, and the `confirm` flag on every write tool are kept
in lockstep so the model can never call a handler that doesn't exist or skip validation.

### Secretless by default in production
The system is designed to run on Azure with **no stored secrets** on the hot path:
- **Microsoft Graph** — app-only auth via **managed identity** (`DefaultAzureCredential`); locally it
  falls back to a dev credential. The identity is granted Graph *application* permissions with admin
  consent.
- **Cosmos DB** — **AAD RBAC** via managed identity (data-plane role), no account key in production.
- **Web sign-in** — optional **Workload Identity Federation**: the confidential client authenticates
  with a managed-identity-minted assertion instead of a client secret.
- **Exchange Online sidecar** — a **two-hop, keyless** path: the app's managed identity mints a token
  for the sidecar's Easy Auth audience; the sidecar then connects to Exchange with its *own* managed
  identity. No function key, no shared secret.
- **Key Vault** — where a secret is genuinely unavoidable (local/CI parity), it is resolved from Key
  Vault at startup via managed identity rather than baked into config.

### Exchange Online via a narrow PowerShell sidecar
Shared mailboxes and distribution-group management are **not** available through Microsoft Graph;
they are Exchange-admin operations exposed only by Exchange Online PowerShell. M365 Guardian isolates
these behind a small, audited PowerShell **sidecar** with a narrow operation surface. When the sidecar
is not configured, the corresponding tools stay **honest-limited** — they return a structured
`not_implemented` result rather than ever faking success.

### Honest limitations over fake success
A recurring principle: when a capability isn't configured or available (Exchange sidecar absent, MFA
group unset, a premium-licensed signal unavailable), the tool returns a truthful structured result.
The assistant never tells a technician that a change happened when it did not.

### Durable, user-scoped sessions
Conversation history is persisted (Cosmos `sessions`, partitioned and TTL'd) so sessions survive
restarts and scale across instances, and history is scoped to the authenticated user.

### Observability
With a connection string set, the app ships traces/metrics/request-correlated logs to Application
Insights via OpenTelemetry (aiohttp-server + httpx instrumentation), so an incoming request and its
downstream Graph/LLM calls are traced end to end. Unset = console logging only.

## Security model

See **[SECURITY.md](../SECURITY.md)** for the full write-up. In brief: a **two-layer,
server-enforced** write confirmation (a prompt-injected model cannot self-approve), least-privilege
Graph permissions, a full audit trail, secret masking, and platform-level network restrictions.

## Quality bar

- Static gates: `ruff` (lint + format), `mypy` against the **real** SDK stubs (not
  `ignore_missing_imports`), and a `pytest` suite — all enforced in CI.
- Secret scanning: `gitleaks` runs both as a pre-commit hook and in CI over full history.
- Pre-commit hygiene hooks (private-key detection, large-file guard, debug-statement guard, etc.).

## Engineering surface (what's in this repo)

The full application source is here: the aiohttp app and lifecycle, the Teams bot handler, the LLM
orchestration loop, the tool executor + validation, the Graph/audit/session/report/secret services,
the Exchange sidecar **client**, and the test suite. The **provisioning recipe** (exact Azure
resource creation, identity/permission wiring, sidecar and Teams-app deployment) is maintained
privately and is available under license.
