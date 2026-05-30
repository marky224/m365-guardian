# Exchange Online Integration — Design Note

## Status

`manage_shared_mailbox` and `manage_distribution_group` are **implemented via the
EXO PowerShell sidecar** (`exo-sidecar/`): when `EXO_SIDECAR_URL` is configured they
perform real Exchange operations; when it is not, they return a structured
`not_implemented` result (never a fake success) so the chatbot never tells a
technician a change happened when it did not. The recommended sidecar approach
below is now built — see `exo-sidecar/README.md` and the deployment guide §5b.

## Why Graph can't do it

As of 2026, Microsoft Graph does **not** support creating or managing shared
mailboxes, and distribution groups / mail-enabled security groups are
**read-only** in Graph. These are Exchange-admin operations that only the
**Exchange Online PowerShell** module exposes.

- Shared mailbox via Graph — unsupported:
  <https://learn.microsoft.com/en-us/answers/questions/5609825/how-to-create-a-shared-mailbox-using-microsoft-gra>
- App-only auth for EXO PowerShell:
  <https://learn.microsoft.com/en-us/powershell/exchange/app-only-auth-powershell-v2?view=exchange-ps>

## What *is* implemented via Graph (supported today)

| Capability | Graph endpoint |
|---|---|
| Add group member | `POST /groups/{id}/members/$ref` |
| Remove group member | `DELETE /groups/{id}/members/{userId}/$ref` |
| Mailbox status (provisioning, automatic replies) | `GET /users/{id}/mailboxSettings` |
| Forwarding rules | `GET /users/{id}/mailFolders/inbox/messageRules` |

## The EXO PowerShell sidecar (built — D-019)

> **Status: implemented.** The design below is what shipped. Code: `exo-sidecar/`
> (the PowerShell Function) and `backend/services/exo_service.py` (the async client).
> Deploy steps: `docs/03_DEPLOYMENT_GUIDE.md` §5b. The app→sidecar hop is secretless
> (the app's managed identity mints a token for the Function's Easy Auth audience —
> no function key), and the sidecar→Exchange hop uses `Connect-ExchangeOnline -ManagedIdentity`.

A small **PowerShell Azure Function** (or container) the Python service calls
over an internal authenticated endpoint:

1. Register a dedicated app; grant the **`Exchange.ManageAsApp`** application
   permission and assign the **Exchange Administrator** (or a least-privilege
   custom RBAC) directory role to its service principal.
2. Authenticate non-interactively with **certificate-based app-only auth**:
   `Connect-ExchangeOnline -AppId <id> -CertificateThumbprint <thumb> -Organization <tenant>.onmicrosoft.com`.
   Store the certificate in **Azure Key Vault**, accessed via managed identity.
   (CNG certificates are not supported — use a CSP key provider.)
3. Expose narrow, audited operations only: `New-Mailbox -Shared`,
   `Add-MailboxPermission`, `New-DistributionGroup`, `Add-DistributionGroupMember`.
4. The Python `ToolExecutor` calls the sidecar; the existing confirmation gate
   and audit logging apply unchanged.

When the sidecar is not configured (`EXO_SIDECAR_URL` unset), these operations stay
honest-limited (`not_implemented`).
