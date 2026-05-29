# Exchange Online Integration — Design Note

## Status

`manage_shared_mailbox` and `manage_distribution_group` are **not implemented**.
They return a structured `not_implemented` result (never a fake success) so the
chatbot never tells a technician a change happened when it did not.

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

## Recommended future approach: an app-only EXO PowerShell sidecar

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

Until that sidecar exists, these operations stay honest-limited.
