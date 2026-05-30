# Azure Functions PowerShell profile — runs once per worker cold start.
#
# We intentionally do NOT call Connect-ExchangeOnline here. The connection is
# established per-request inside ManageExchange/run.ps1 so that a failed connect
# returns a clean structured error to the caller instead of crashing the worker.
#
# NOTE: The host's own MANAGED IDENTITY authenticates to Azure automatically; we
# never call Connect-AzAccount or read any secret here. Keep this file minimal.

if ($env:MSI_SECRET -and (Get-Module -ListAvailable Az.Accounts)) {
    # Az is not required by this sidecar; left as a no-op hook for future use.
}
