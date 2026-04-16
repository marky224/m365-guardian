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
│   ├── app.py                    # Main entry point (aiohttp server)
│   ├── bot.py                    # Teams bot handler
│   ├── config.py                 # Configuration from environment
│   ├── services/
│   │   ├── graph_service.py      # Microsoft Graph API wrapper
│   │   ├── llm_service.py        # LLM orchestration via LiteLLM
│   │   ├── audit_service.py      # Cosmos DB audit logging
│   │   └── report_service.py     # Weekly security report (10 checks)
│   ├── tools/
│   │   └── executor.py           # Routes tool calls to Graph methods
│   ├── functions/
│   │   └── weekly_report.py      # Azure Function timer trigger
│   └── web-app/
│       └── templates/
│           └── index.html        # Standalone web chat interface
├── docs/
│   ├── 01_SYSTEM_PROMPT.md       # Complete chatbot system prompt
│   ├── 02_TOOL_SCHEMAS.json      # All 18 tool/function definitions
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
- **IP Restriction**: The App Service is locked to specific IPs via access restrictions.

### 4. Deploy to Azure

Follow the complete guide in `docs/03_DEPLOYMENT_GUIDE.md`.

## PoC Scenarios

| # | Scenario | Tools Used |
|---|----------|------------|
| 1 | Create user + mailbox | `create_user` → `assign_license` → `enforce_mfa` |
| 2 | Password reset + MFA | `search_users` → `get_user_details` → `reset_password` → `enforce_mfa` |
| 3 | Weekly security report | `generate_weekly_insights_report` → `send_report_to_teams` → `send_report_via_email` |

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

## Security Principles

- **Mandatory confirmation** — every write action requires explicit `YES`
- **Least-privilege** — Graph permissions are scoped to exactly what's needed
- **Full audit trail** — every action logged with who, what, when, and transcript
- **No data leakage** — passwords masked, secrets never echoed
- **Provider isolation** — no customer data used for LLM training

## Tool Inventory (18 Functions)

| Tool | Type | Description |
|------|------|-------------|
| `search_users` | Read | Search Entra ID users |
| `get_user_details` | Read | Full user profile + MFA + sign-in |
| `create_user` | Write | Create user + optional license/mailbox |
| `update_user` | Write | Update user properties |
| `delete_user` | Write | Soft-delete user (30-day recovery) |
| `reset_password` | Write | Reset password with temp generation |
| `enforce_mfa` | Write | Enable/enforce per-user MFA |
| `list_available_licenses` | Read | List tenant license SKUs |
| `assign_license` | Write | Assign license to user |
| `remove_license` | Write | Remove license from user |
| `manage_group_membership` | Write | Add/remove group members |
| `manage_shared_mailbox` | Write | Create/manage shared mailboxes |
| `manage_distribution_group` | Write | Create/manage distribution groups |
| `check_mailbox_status` | Read | Check mailbox provisioning + health |
| `generate_weekly_insights_report` | Read | Run all 10 security checks |
| `send_report_to_teams` | Write | Post Adaptive Card to Teams |
| `send_report_via_email` | Write | Send HTML report via email |
| `get_audit_log` | Read | Query Guardian action history |
| `bulk_operation` | Write | Bulk password/license/MFA operations |

## License

Proprietary — All rights reserved.
