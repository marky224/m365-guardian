# 🛡️ M365 Guardian

**Your Microsoft 365 user & security guardian — powered by natural language.**

M365 Guardian is an LLM-powered chatbot built for SMB IT technicians. It enables natural-language management of Microsoft Entra ID users and Exchange Online mailboxes, with automated weekly security insights.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        M365 GUARDIAN                             │
├──────────────┬───────────────┬───────────────┬──────────────────┤
│  Teams Bot   │   Web Chat    │  Timer Func   │   REST API       │
│  (Bot Fwk)   │   (aiohttp)   │  (Az Func)    │   /api/chat      │
├──────────────┴───────────────┴───────────────┴──────────────────┤
│                    LLM Orchestration Layer                       │
│              LiteLLM (Anthropic / Azure OpenAI / OpenAI / xAI)  │
│              Tool Calling + Structured Output                    │
├─────────────────────────────────────────────────────────────────┤
│                    Tool Executor                                 │
│         Routes LLM tool calls → Graph API service methods        │
│         Audit logging on every read/write operation              │
├──────────────┬──────────────────────────┬──────────────────────┤
│  Graph API   │     Report Service       │    Audit Service      │
│  (msgraph)   │  10 security checks      │  (Cosmos DB)          │
│  Users/Mail  │  Teams + Email delivery   │  Full traceability    │
├──────────────┴──────────────────────────┴──────────────────────┤
│                Microsoft Graph API                              │
│          Entra ID  ·  Exchange Online  ·  Identity Protection   │
└─────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
m365-guardian/
├── backend/
│   ├── app.py                    # Main entry point (aiohttp server) + app factory/lifecycle
│   ├── bot.py                    # Teams bot handler
│   ├── config.py                 # Configuration from environment
│   ├── observability.py          # Azure Monitor / OpenTelemetry setup (App Insights)
│   ├── services/
│   │   ├── graph_service.py      # Microsoft Graph API wrapper (managed identity)
│   │   ├── llm_service.py        # LLM orchestration via LiteLLM
│   │   ├── audit_service.py      # Cosmos DB audit logging
│   │   ├── session_service.py    # Durable Cosmos conversation sessions
│   │   ├── secret_service.py     # Key Vault / env secret resolution
│   │   └── report_service.py     # Weekly security report (10 checks)
│   ├── tools/
│   │   ├── executor.py           # Routes tool calls to Graph methods (confirmation gate)
│   │   └── validation.py         # Per-tool pydantic argument validation
│   ├── functions/
│   │   └── weekly_report.py      # Azure Function timer trigger
│   ├── web-app/
│   │   └── templates/
│   │       └── index.html        # Standalone web chat interface
│   └── tests/                    # pytest suite
├── docs/
│   ├── 01_SYSTEM_PROMPT.md       # Complete chatbot system prompt
│   ├── 02_TOOL_SCHEMAS.json      # All 19 tool/function definitions
│   ├── 03_DEPLOYMENT_GUIDE.md    # Step-by-step Azure deployment
│   └── 04_SAMPLE_CONVERSATIONS.md # PoC scenario conversation flows
├── .env.template                 # Environment variable template
├── pyproject.toml                # Python project configuration
└── README.md                     # This file
```

## Quick Start

### 1. Clone and configure

```bash
cp .env.template .env
# Edit .env with your tenant, app registration, and API keys
```

### 2. Install dependencies

```bash
pip install -e .
```

### 3. Run locally

```bash
python -m backend.app
# Server starts on http://localhost:8080
# Web chat:     http://localhost:8080/
# Bot endpoint: http://localhost:8080/api/messages
# Health check: http://localhost:8080/health
```

### Configuration notes

- **LLM Provider**: Defaults to xAI (Grok). Set `LLM_PROVIDER` and the corresponding API key in `.env`.
- **Bot Type**: Uses `SingleTenant` (MultiTenant is deprecated by Azure).
- **Azure Region**: Deployed to `centralus` (eastus had quota limitations).
- **IP Restriction**: The App Service is locked to specific IPs via Azure platform-level access restrictions.
- **Deployment**: Set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` in App Service settings so Azure installs Python dependencies during deployment.
- **Python Runtime**: Must use Python 3.11. Deploying with 3.12 causes `libpython3.11.so` errors because the virtual environment is built against 3.11.

### 4. Deploy to Azure

Follow the complete guide in `docs/03_DEPLOYMENT_GUIDE.md`.

## PoC Scenarios

| # | Scenario | Tools Used |
|---|----------|------------|
| 1 | Create user + mailbox | `create_user` → `assign_license` → `enforce_mfa` |
| 2 | Password reset + MFA | `search_users` → `get_user_details` → `reset_password` → `enforce_mfa` |
| 3 | Weekly security report | `generate_weekly_insights_report` → `send_report_to_teams` → `send_report_via_email` (Phase 2) |

See full conversation transcripts in `docs/04_SAMPLE_CONVERSATIONS.md`.

## Weekly Security Report — 10 Checks

| # | Check | Severity Logic |
|---|-------|---------------|
| 1 | Suspicious Sign-Ins | 🔴 if >3 risky, 🟡 if 1–3, 🟢 if 0 |
| 2 | MFA Compliance Gaps | 🔴 if >5 users without MFA |
| 3 | Dormant Accounts | 🔴 if >10 accounts inactive 90+ days |
| 4 | License Optimization | 🟡 if >5 unused licenses per SKU |
| 5 | Privileged Access Hygiene | 🔴 if >5 permanent privileged admins |
| 6 | Guest User & External Access | 🟡 if >20 guests |
| 7 | Legacy Authentication | Checks for blocked legacy auth |
| 8 | Exchange Best Practices | Forwarding, delegations, storage |
| 9 | Conditional Access Gaps | Policy coverage analysis |
| 10 | Password & Auth Hygiene | SSPR, banned passwords, methods |

## Switching LLM Providers

M365 Guardian supports one-click LLM swapping via LiteLLM:

| Provider | `LLM_PROVIDER` | Required Env Vars |
|----------|----------------|-------------------|
| xAI / Grok (default) | `xai` | `XAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Azure OpenAI | `azure_openai` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` |
| OpenAI | `openai` | `OPENAI_API_KEY` |

## Production Hardening

M365 Guardian runs on Azure with platform-managed identity and secrets. Every feature below is
**environment-gated**, so a local checkout runs with no Azure dependencies.

- **Managed identity for Graph** — app-only Microsoft Graph auth uses `DefaultAzureCredential` (the
  App Service's managed identity in Azure; falls back to the env client secret / `az login` locally).
  Grant the identity the required Graph **application permissions** (admin consent).
- **Managed identity for Cosmos** — leave `COSMOS_KEY` blank in production and the app authenticates
  to Cosmos with managed identity (AAD RBAC); grant the identity a Cosmos data-plane role. Set the key
  for local dev / the emulator.
- **Secretless web sign-in (WIF)** — set `AZURE_USE_WIF=true` and the MSAL web sign-in authenticates
  with a user-assigned managed-identity assertion instead of `AZURE_CLIENT_SECRET`. Configure the
  identity as a federated identity credential on the app registration and set
  `AZURE_WIF_MANAGED_IDENTITY_CLIENT_ID` (see `docs/03_DEPLOYMENT_GUIDE.md`). The client secret is kept
  as the local-dev/CI fallback.
- **Key Vault for secrets** — set `KEY_VAULT_URL` and the app fetches `azure-client-secret`,
  `llm-api-key`, `bot-app-password`, `cosmos-key`, and `session-secret` from Key Vault at startup via
  managed identity. With it unset, secrets come from the environment / `.env` (local dev). Under WIF
  (above) and Cosmos managed identity, `azure-client-secret` and `cosmos-key` are unnecessary in prod.
- **Durable sessions** — conversation history is stored in the Cosmos `sessions` container (partition
  key `/owner_id`, 30-day TTL), so sessions survive restarts and scale across instances. History is
  scoped to the authenticated user.
- **Bot authentication** — the Teams endpoint uses `CloudAdapter`, honoring `BOT_APP_TYPE`
  (SingleTenant / MultiTenant / UserAssignedMSI). The endpoint is enabled only when `BOT_APP_ID` is set.
- **Observability** — set `APPLICATIONINSIGHTS_CONNECTION_STRING` to ship traces, metrics, and
  request-correlated logs to Application Insights (OpenTelemetry; aiohttp-server + httpx instrumentation,
  so incoming requests and outgoing Graph/LLM calls are traced end to end). Unset = console logging only.

## Security Principles

- **Two-layer write confirmation** — server-enforced, not just prompted. Layer 1 gates every write; Layer 2 binds approval to a human **Approve** action (web buttons / Teams Adaptive Card) validated in code against a server-minted token — so a prompt-injected model cannot self-approve
- **Least-privilege** — Graph permissions are scoped to exactly what's needed
- **Full audit trail** — every action logged with who, what, when, and transcript
- **IP restriction** — Azure App Service access restrictions block unauthorized IPs at the platform level before they reach the application
- **No data leakage** — passwords masked, secrets never echoed
- **Provider isolation** — no customer data used for LLM training

## Required Entra ID Roles

In addition to the Graph API application permissions listed in the deployment guide, the M365 Guardian **service principal** requires the **Helpdesk Administrator** directory role in Entra ID. This is separate from API permissions — without it, password resets return a 403 `Authorization_RequestDenied` error even with `User.ReadWrite.All` granted.

Assign via: **Entra ID → Roles and administrators → Helpdesk Administrator → Add assignments → select "M365 Guardian" (Enterprise Application)**.

> **Note:** Helpdesk Administrator can reset passwords for non-admin users only. Resets for Global Admins will be denied by design — this is correct least-privilege behavior.

## Tool Inventory (19 Functions)

| Tool | Type | Description |
|------|------|-------------|
| `search_users` | Read | Search Entra ID users |
| `get_user_details` | Read | Full user profile + MFA + sign-in |
| `create_user` | Write | Create user + optional license/mailbox |
| `update_user` | Write | Update user properties |
| `delete_user` | Write | Soft-delete user (30-day recovery) |
| `reset_password` | Write | Reset password with temp generation |
| `enforce_mfa` | Write | Enforce MFA via group-based Conditional Access (adds/removes user from an MFA-required group) |
| `list_available_licenses` | Read | List tenant license SKUs |
| `assign_license` | Write | Assign license to user |
| `remove_license` | Write | Remove license from user |
| `manage_group_membership` | Write | Add/remove group members |
| `manage_shared_mailbox` | Write | ⏳ Not yet implemented — requires Exchange Online PowerShell (see [docs/05_EXCHANGE_ONLINE_INTEGRATION.md](docs/05_EXCHANGE_ONLINE_INTEGRATION.md)) |
| `manage_distribution_group` | Write | ⏳ Not yet implemented — requires Exchange Online PowerShell (see [docs/05_EXCHANGE_ONLINE_INTEGRATION.md](docs/05_EXCHANGE_ONLINE_INTEGRATION.md)) |
| `check_mailbox_status` | Read | Check mailbox provisioning + forwarding |
| `generate_weekly_insights_report` | Read | Run all 10 security checks |
| `send_report_to_teams` | Write | Post Adaptive Card to Teams |
| `send_report_via_email` | Write | Send HTML report via email |
| `get_audit_log` | Read | Query Guardian action history |
| `bulk_operation` | Write | Bulk password/license/MFA operations |

## License

Proprietary — All rights reserved.
