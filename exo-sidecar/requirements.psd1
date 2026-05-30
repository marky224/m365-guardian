# Azure Functions PowerShell managed dependencies.
# host.json's managedDependency.enabled=true installs these on the Function host.
# ExchangeOnlineManagement V3 is required for -ManagedIdentity (secretless app-only auth).
@{
    'ExchangeOnlineManagement' = '3.*'
}
