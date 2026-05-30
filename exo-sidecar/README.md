# M365 Guardian — Exchange Online PowerShell sidecar

A small PowerShell **Azure Function** that performs the Exchange-admin operations
Microsoft Graph cannot: **shared mailboxes** (Graph: unsupported) and **distribution
groups** (Graph: read-only). The Python service (`backend/services/exo_service.py`)
calls this over an authenticated internal HTTP endpoint; the function connects to
Exchange Online and runs a narrow, allow-listed set of cmdlets.

Until this sidecar is deployed and `EXO_SIDECAR_URL` is set, the
`manage_shared_mailbox` / `manage_distribution_group` tools stay **honest-limited**
(they return `not_implemented`, never a fake success).

## Why a sidecar

These operations require the **Exchange Online PowerShell V3** module
(`ExchangeOnlineManagement`); there is no Graph equivalent. Rather than embed
PowerShell in the Python service, we isolate it in a single-purpose Function with a
tiny HTTP contract.

## HTTP contract

`POST <EXO_SIDECAR_URL>` — JSON in, JSON out.

```jsonc
// request
{
  "operation": "add_shared_mailbox_member",
  "params": { "mailbox_address": "team@contoso.com", "members": ["a@contoso.com"] }
}
// success
{ "success": true, "operation": "add_shared_mailbox_member", "result": { ... } }
// failure (HTTP 400/500)
{ "success": false, "operation": "add_shared_mailbox_member", "error": "<message>" }
```

The Python client trusts `success` only when `true`; any non-2xx, transport error,
non-JSON body, or `success:false` becomes a structured failure on its side.

| operation | params | cmdlets |
|---|---|---|
| `create_shared_mailbox` | `mailbox_address`, `display_name?` | `New-Mailbox -Shared` |
| `delete_shared_mailbox` | `mailbox_address` | `Remove-Mailbox` |
| `add_shared_mailbox_member` | `mailbox_address`, `members[]` | `Add-MailboxPermission` (FullAccess) + `Add-RecipientPermission` (SendAs) |
| `remove_shared_mailbox_member` | `mailbox_address`, `members[]` | `Remove-MailboxPermission` + `Remove-RecipientPermission` |
| `create_distribution_group` | `group_email`, `display_name?` | `New-DistributionGroup` |
| `delete_distribution_group` | `group_email` | `Remove-DistributionGroup` |
| `add_distribution_group_member` | `group_email`, `members[]` | `Add-DistributionGroupMember` |
| `remove_distribution_group_member` | `group_email`, `members[]` | `Remove-DistributionGroupMember` |

> Shared-mailbox member ops grant/revoke **both FullAccess and SendAs** — FullAccess
> alone cannot send *as* the mailbox, the most common follow-up support ticket.

## Two secretless auth hops

The whole app is secretless in production (managed identity for Graph, Cosmos, and
web sign-in). This sidecar keeps that property — **no function key, no stored secret**.

1. **App → Function.** The Python app's managed identity mints an AAD bearer token for
   this Function's app-registration audience and sends it as `Authorization: Bearer …`.
   The function binding is `authLevel=anonymous`; **App Service Easy Auth** validates
   the token. Do **not** switch to a function key — that is a stored secret and defeats
   the design.
2. **Function → Exchange Online.** `Connect-ExchangeOnline -ManagedIdentity`. The
   Function's own managed identity needs the **`Exchange.ManageAsApp`** app role and the
   **Exchange Administrator** directory role. Certificate-based app-only auth
   (`-AppId -CertificateThumbprint -Organization`, cert in Key Vault) is the fallback.

## Deploy (summary — full steps in `docs/03_DEPLOYMENT_GUIDE.md`)

```bash
# Function app (PowerShell 7.4, Functions v4, Linux)
az functionapp create --name m365guardian-exo --resource-group $RG \
  --consumption-plan-location $LOCATION --runtime powershell --runtime-version 7.4 \
  --functions-version 4 --os-type Linux --storage-account $STORAGE

# Settings: tenant for Connect-ExchangeOnline (+ optional UAMI client id)
az functionapp config appsettings set --name m365guardian-exo --resource-group $RG \
  --settings EXO_ORGANIZATION="contoso.onmicrosoft.com"

# Managed identity + Exchange.ManageAsApp app role + Exchange Administrator role,
# Easy Auth with the app registration as audience, then publish:
cd exo-sidecar && func azure functionapp publish m365guardian-exo
```

On the app side, set `EXO_SIDECAR_URL` (the function URL) and `EXO_SIDECAR_AUDIENCE`
(the Function's app-registration App ID URI / client id).

## Verification gap

The live two-hop round-trip is **not locally verifiable** — it needs a real tenant,
both managed identities, Easy Auth, and the Exchange role grant. A wrong audience or a
missing role saves without error and fails only at call time. Smoke-test in a real
tenant after deploying.
