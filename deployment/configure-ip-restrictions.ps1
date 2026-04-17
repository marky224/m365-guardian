param(
    [Parameter(Mandatory=$true)]
    [string[]]$AllowedIPs,

    [string]$AppName = "m365guardian-app",
    [string]$ResourceGroup = "rg-m365guardian"
)

# Clear existing rules
az webapp config access-restriction set --name $AppName --resource-group $ResourceGroup --default-action Deny

# Add each IP
$priority = 100
foreach ($ip in $AllowedIPs) {
    az webapp config access-restriction add `
        --name $AppName `
        --resource-group $ResourceGroup `
        --priority $priority `
        --rule-name "AllowedIP-$priority" `
        --action Allow `
        --ip-address "$ip/32"
    $priority += 10
}

# Always allow Bot Framework
az webapp config access-restriction add `
    --name $AppName `
    --resource-group $ResourceGroup `
    --priority 500 `
    --rule-name "BotFramework" `
    --action Allow `
    --service-tag AzureBotService

Write-Host "Access restrictions configured for $AppName"