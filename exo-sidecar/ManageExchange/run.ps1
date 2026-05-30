using namespace System.Net

# M365 Guardian — Exchange Online PowerShell sidecar.
#
# HTTP-triggered Azure Function that performs the shared-mailbox and distribution-group
# operations Microsoft Graph cannot. The Python service POSTs {operation, params}; this
# function connects to Exchange Online with its own managed identity and runs a narrow,
# allow-listed set of cmdlets.
#
# AUTH (two secretless hops — see README.md):
#   1. Caller -> this Function: the function binding is authLevel=anonymous; App Service
#      "Easy Auth" (App Service Authentication) MUST be enabled to validate the caller's
#      AAD bearer token against this Function app's audience. Do NOT switch to a function
#      key — that would re-introduce a stored secret. Easy Auth is the gate.
#   2. This Function -> Exchange Online: Connect-ExchangeOnline -ManagedIdentity. The
#      Function's managed identity needs the Exchange.ManageAsApp app role + the Exchange
#      Administrator directory role. Certificate-based app-only auth is the documented
#      fallback (see README).
#
# Response contract: always JSON. { "success": true, "result": {...} } on success;
# { "success": false, "error": "<message>" } on failure (HTTP 400/500). The Python client
# trusts "success" only when true and never fabricates success.

param($Request, $TriggerMetadata)

$ErrorActionPreference = 'Stop'

# Organization (tenant) for Connect-ExchangeOnline, e.g. contoso.onmicrosoft.com.
# Set EXO_ORGANIZATION in the Function app settings.
$organization = $env:EXO_ORGANIZATION
# Optional: a user-assigned managed identity client id. Blank = system-assigned MI.
$miClientId = $env:EXO_MANAGED_IDENTITY_CLIENT_ID

function Send-Json {
    param([int]$Status, [hashtable]$Body)
    Push-OutputBinding -Name Response -Value ([HttpResponseContext]@{
            StatusCode  = $Status
            Headers     = @{ 'Content-Type' = 'application/json' }
            Body        = ($Body | ConvertTo-Json -Depth 8 -Compress)
        })
}

function Get-Param {
    param($Params, [string]$Name, [bool]$Required = $true)
    $value = $Params.$Name
    if ($Required -and [string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required parameter: $Name"
    }
    return $value
}

# ── Parse the request ────────────────────────────────────────────────
$operation = $Request.Body.operation
$params = $Request.Body.params
if ([string]::IsNullOrWhiteSpace($operation)) {
    Send-Json -Status 400 -Body @{ success = $false; error = 'Missing "operation".' }
    return
}
if ([string]::IsNullOrWhiteSpace($organization)) {
    Send-Json -Status 500 -Body @{ success = $false; error = 'Server misconfigured: EXO_ORGANIZATION is not set.' }
    return
}

# Allow-list: never dispatch an operation we don't explicitly recognize.
$allowed = @(
    'create_shared_mailbox', 'delete_shared_mailbox', 'add_shared_mailbox_member', 'remove_shared_mailbox_member',
    'create_distribution_group', 'delete_distribution_group', 'add_distribution_group_member', 'remove_distribution_group_member'
)
if ($operation -notin $allowed) {
    Send-Json -Status 400 -Body @{ success = $false; error = "Unsupported operation: $operation" }
    return
}

$connected = $false
try {
    # ── Hop 2: connect to Exchange Online with the Function's managed identity ──
    $connectArgs = @{ ManagedIdentity = $true; Organization = $organization; ShowBanner = $false }
    if (-not [string]::IsNullOrWhiteSpace($miClientId)) {
        $connectArgs['ManagedIdentityAccountId'] = $miClientId
    }
    Connect-ExchangeOnline @connectArgs
    $connected = $true

    $result = $null
    switch ($operation) {
        'create_shared_mailbox' {
            $addr = Get-Param $params 'mailbox_address'
            $name = $params.display_name
            if ([string]::IsNullOrWhiteSpace($name)) { $name = $addr.Split('@')[0] }
            $mbx = New-Mailbox -Shared -Name $name -DisplayName $name -PrimarySmtpAddress $addr
            $result = @{ mailbox_address = $addr; identity = $mbx.Identity }
        }
        'delete_shared_mailbox' {
            $addr = Get-Param $params 'mailbox_address'
            Remove-Mailbox -Identity $addr -Confirm:$false
            $result = @{ mailbox_address = $addr; deleted = $true }
        }
        'add_shared_mailbox_member' {
            $addr = Get-Param $params 'mailbox_address'
            $members = @(Get-Param $params 'members')
            foreach ($m in $members) {
                # Grant both FullAccess and SendAs — FullAccess alone can't send AS the mailbox.
                Add-MailboxPermission -Identity $addr -User $m -AccessRights FullAccess -InheritanceType All -Confirm:$false | Out-Null
                Add-RecipientPermission -Identity $addr -Trustee $m -AccessRights SendAs -Confirm:$false | Out-Null
            }
            $result = @{ mailbox_address = $addr; members_added = $members; rights = @('FullAccess', 'SendAs') }
        }
        'remove_shared_mailbox_member' {
            $addr = Get-Param $params 'mailbox_address'
            $members = @(Get-Param $params 'members')
            foreach ($m in $members) {
                Remove-MailboxPermission -Identity $addr -User $m -AccessRights FullAccess -Confirm:$false | Out-Null
                Remove-RecipientPermission -Identity $addr -Trustee $m -AccessRights SendAs -Confirm:$false | Out-Null
            }
            $result = @{ mailbox_address = $addr; members_removed = $members }
        }
        'create_distribution_group' {
            $email = Get-Param $params 'group_email'
            $name = $params.display_name
            if ([string]::IsNullOrWhiteSpace($name)) { $name = $email.Split('@')[0] }
            $grp = New-DistributionGroup -Name $name -DisplayName $name -PrimarySmtpAddress $email
            $result = @{ group_email = $email; identity = $grp.Identity }
        }
        'delete_distribution_group' {
            $email = Get-Param $params 'group_email'
            Remove-DistributionGroup -Identity $email -Confirm:$false
            $result = @{ group_email = $email; deleted = $true }
        }
        'add_distribution_group_member' {
            $email = Get-Param $params 'group_email'
            $members = @(Get-Param $params 'members')
            foreach ($m in $members) {
                Add-DistributionGroupMember -Identity $email -Member $m -BypassSecurityGroupManagerCheck -Confirm:$false | Out-Null
            }
            $result = @{ group_email = $email; members_added = $members }
        }
        'remove_distribution_group_member' {
            $email = Get-Param $params 'group_email'
            $members = @(Get-Param $params 'members')
            foreach ($m in $members) {
                Remove-DistributionGroupMember -Identity $email -Member $m -BypassSecurityGroupManagerCheck -Confirm:$false | Out-Null
            }
            $result = @{ group_email = $email; members_removed = $members }
        }
    }

    Send-Json -Status 200 -Body @{ success = $true; operation = $operation; result = $result }
}
catch {
    # Honest failure — the Python client surfaces this and never claims success.
    $message = $_.Exception.Message
    Write-Error "EXO operation '$operation' failed: $message"
    Send-Json -Status 500 -Body @{ success = $false; operation = $operation; error = $message }
}
finally {
    if ($connected) {
        try { Disconnect-ExchangeOnline -Confirm:$false } catch { Write-Warning "Disconnect failed: $($_.Exception.Message)" }
    }
}
