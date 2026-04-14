# M365 Guardian — Deployment Guide

## Prerequisites

- An Azure subscription
- A Microsoft 365 test tenant (with at least one E3/E5 or Business Premium license)
- Azure CLI installed (`az` command)
- Python 3.11+
- Node.js 18+ (for Bot Framework Emulator, optional)
- An Anthropic API key (or Azure OpenAI endpoint)

---

## Step 1: Register the Entra ID Application

This app registration grants M365 Guardian the permissions it needs to manage users, mailboxes, and read security data via Microsoft Graph.

### 1.1 Create the App Registration

```bash
# Login to Azure
az login --tenant YOUR_TENANT_ID

# Create the app registration
az ad app create \
  --display-name "M365 Guardian" \
  --sign-in-audience AzureADMyOrg \
  --required-resource-accesses @app-permissions.json
```

Create `app-permissions.json` with these Graph API application permissions:

```json
[
  {
    "resourceAppId": "00000003-0000-0000-c000-000000000000",
    "resourceAccess": [
      { "id": "df021288-bdef-4463-88db-98f22de89214", "type": "Role" },
      { "id": "741f803b-c850-494e-b5df-cde7c675a1ca", "type": "Role" },
      { "id": "1bfefb4e-e0b5-418b-a88f-73c46d2cc8e9", "type": "Role" },
      { "id": "62a82d76-70ea-41e2-9197-370581804d09", "type": "Role" },
      { "id": "7ab1d382-f21e-4acd-a863-ba3e13f7da61", "type": "Role" },
      { "id": "246dd0d5-5bd0-4def-940b-0421030a5b68", "type": "Role" },
      { "id": "5b567255-7703-4780-807c-7be8301ae99b", "type": "Role" },
      { "id": "b0afded3-3588-46d8-8b3d-9842eff778da", "type": "Role" },
      { "id": "498476ce-e0fe-48b0-b801-37ba7e2685c6", "type": "Role" },
      { "id": "dc5007c0-2d7d-4c42-879c-2dab87571379", "type": "Role" },
      { "id": "e1fe6dd8-ba31-4d61-89e7-88639da4683d", "type": "Role" }
    ]
  }
]
```

### Permission Mapping

| Permission ID | Permission Name | Purpose |
|---|---|---|
| `df021288...` | User.ReadWrite.All | Create, update, delete users |
| `741f803b...` | Directory.ReadWrite.All | Manage directory objects |
| `1bfefb4e...` | User.ReadWrite.All | License management |
| `62a82d76...` | Group.ReadWrite.All | Group membership |
| `7ab1d382...` | Directory.Read.All | Read directory data |
| `246dd0d5...` | Reports.Read.All | Sign-in and usage reports |
| `5b567255...` | Member.Read.Hidden | Read hidden memberships |
| `b0afded3...` | AuditLog.Read.All | Read audit logs |
| `498476ce...` | IdentityRiskyUser.Read.All | Risky user detection |
| `dc5007c0...` | UserAuthenticationMethod.ReadWrite.All | MFA management |
| `e1fe6dd8...` | Mail.Send | Send report emails |

### 1.2 Create a Client Secret

```bash
# Get the App ID
APP_ID=$(az ad app list --display-name "M365 Guardian" --query "[0].appId" -o tsv)

# Create a client secret (valid for 1 year)
az ad app credential reset --id $APP_ID --years 1
```

Save the `password` output — this is your `AZURE_CLIENT_SECRET`.

### 1.3 Grant Admin Consent

```bash
# Create the service principal
az ad sp create --id $APP_ID

# Grant admin consent (requires Global Administrator)
az ad app permission admin-consent --id $APP_ID
```

Alternatively, go to **Azure Portal → Entra ID → App registrations → M365 Guardian → API permissions → Grant admin consent**.

---

## Step 2: Create Azure Resources

### 2.1 Resource Group

```bash
RESOURCE_GROUP="rg-m365guardian"
LOCATION="eastus"

az group create --name $RESOURCE_GROUP --location $LOCATION
```

### 2.2 Azure App Service (for the bot + web app)

```bash
# Create App Service plan
az appservice plan create \
  --name "plan-m365guardian" \
  --resource-group $RESOURCE_GROUP \
  --sku B1 \
  --is-linux

# Create Web App
az webapp create \
  --name "m365guardian-app" \
  --resource-group $RESOURCE_GROUP \
  --plan "plan-m365guardian" \
  --runtime "PYTHON:3.11"
```

### 2.3 Azure Cosmos DB (session + audit storage)

```bash
az cosmosdb create \
  --name "m365guardian-cosmos" \
  --resource-group $RESOURCE_GROUP \
  --kind GlobalDocumentDB \
  --default-consistency-level Session

# Create database
az cosmosdb sql database create \
  --account-name "m365guardian-cosmos" \
  --resource-group $RESOURCE_GROUP \
  --name "m365guardian"

# Create containers
az cosmosdb sql container create \
  --account-name "m365guardian-cosmos" \
  --resource-group $RESOURCE_GROUP \
  --database-name "m365guardian" \
  --name "sessions" \
  --partition-key-path "/session_id"

az cosmosdb sql container create \
  --account-name "m365guardian-cosmos" \
  --resource-group $RESOURCE_GROUP \
  --database-name "m365guardian" \
  --name "audit_logs" \
  --partition-key-path "/session_id" \
  --default-ttl 31536000
```

### 2.4 Azure Bot Service

```bash
# Create Bot registration
az bot create \
  --name "m365guardian-bot" \
  --resource-group $RESOURCE_GROUP \
  --kind registration \
  --appid $APP_ID \
  --password "YOUR_APP_PASSWORD" \
  --endpoint "https://m365guardian-app.azurewebsites.net/api/messages"
```

### 2.5 Connect Bot to Microsoft Teams

```bash
az bot msteams create \
  --name "m365guardian-bot" \
  --resource-group $RESOURCE_GROUP
```

---

## Step 3: Configure Environment Variables

Set all environment variables on the App Service:

```bash
az webapp config appsettings set \
  --name "m365guardian-app" \
  --resource-group $RESOURCE_GROUP \
  --settings \
    AZURE_TENANT_ID="your-tenant-id" \
    AZURE_CLIENT_ID="your-client-id" \
    AZURE_CLIENT_SECRET="your-client-secret" \
    LLM_PROVIDER="anthropic" \
    ANTHROPIC_API_KEY="your-anthropic-key" \
    LLM_MODEL="claude-sonnet-4-20250514" \
    BOT_APP_ID="your-bot-app-id" \
    BOT_APP_PASSWORD="your-bot-password" \
    COSMOS_ENDPOINT="https://m365guardian-cosmos.documents.azure.com:443/" \
    COSMOS_KEY="your-cosmos-key" \
    COSMOS_DATABASE="m365guardian" \
    REPORT_TEAMS_TEAM_ID="your-team-id" \
    REPORT_TEAMS_CHANNEL_ID="your-channel-id" \
    REPORT_EMAIL_RECIPIENTS="admin@yourdomain.com" \
    REPORT_SENDER_UPN="m365guardian@yourdomain.com" \
    WEB_APP_BASE_URL="https://m365guardian-app.azurewebsites.net"
```

---

## Step 4: Deploy the Application

### 4.1 Deploy via ZIP

```bash
cd m365-guardian

# Install dependencies
pip install -r requirements.txt

# Create deployment package
zip -r deploy.zip backend/ docs/ pyproject.toml

# Deploy
az webapp deployment source config-zip \
  --name "m365guardian-app" \
  --resource-group $RESOURCE_GROUP \
  --src deploy.zip
```

### 4.2 Configure Startup Command

```bash
az webapp config set \
  --name "m365guardian-app" \
  --resource-group $RESOURCE_GROUP \
  --startup-file "python -m backend.app"
```

---

## Step 5: Deploy the Weekly Report Azure Function

### 5.1 Create a Function App

```bash
az functionapp create \
  --name "m365guardian-func" \
  --resource-group $RESOURCE_GROUP \
  --consumption-plan-location $LOCATION \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux \
  --storage-account "m365guardianstore"
```

### 5.2 Deploy the Function

```bash
cd m365-guardian
func azure functionapp publish m365guardian-func
```

### 5.3 Set Function App Settings

Apply the same environment variables as the main app (Step 3).

---

## Step 6: Install the Teams App

### 6.1 Create the Teams App Manifest

Create `manifest.json`:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
  "manifestVersion": "1.16",
  "version": "1.0.0",
  "id": "YOUR_BOT_APP_ID",
  "developer": {
    "name": "Your Company",
    "websiteUrl": "https://m365guardian-app.azurewebsites.net",
    "privacyUrl": "https://m365guardian-app.azurewebsites.net/privacy",
    "termsOfUseUrl": "https://m365guardian-app.azurewebsites.net/terms"
  },
  "name": { "short": "M365 Guardian", "full": "M365 Guardian — IT Admin Assistant" },
  "description": {
    "short": "Your Microsoft 365 user & security guardian",
    "full": "LLM-powered chatbot for managing Entra ID users, Exchange mailboxes, and tenant security."
  },
  "icons": { "color": "color.png", "outline": "outline.png" },
  "accentColor": "#0078D4",
  "bots": [
    {
      "botId": "YOUR_BOT_APP_ID",
      "scopes": ["personal", "team"],
      "commandLists": [
        {
          "scopes": ["personal"],
          "commands": [
            { "title": "Create user", "description": "Create a new M365 user" },
            { "title": "Reset password", "description": "Reset a user's password" },
            { "title": "Security report", "description": "Generate a security insights report" }
          ]
        }
      ]
    }
  ],
  "validDomains": ["m365guardian-app.azurewebsites.net"]
}
```

### 6.2 Upload to Teams

1. Go to **Microsoft Teams Admin Center** → **Teams apps** → **Manage apps**.
2. Click **Upload new app** → upload the ZIP containing `manifest.json` + icon files.
3. Or sideload in Teams: **Apps → Manage your apps → Upload a custom app**.

---

## Step 7: Verify the PoC

### Test Checklist

1. **Open M365 Guardian in Teams** — you should see the welcome message.
2. **Test user creation**: Type `"Create a new user Jane Doe in Engineering, email jane.doe@yourdomain.com"`.
3. **Verify confirmation prompt** — the bot should show a summary and ask for `YES`.
4. **Test password reset**: `"Reset the password for jane.doe@yourdomain.com"`.
5. **Test MFA enforcement**: `"Enforce MFA for jane.doe@yourdomain.com"`.
6. **Trigger the weekly report**: `"Generate the weekly security report"`.
7. **Check the web app**: Navigate to `https://m365guardian-app.azurewebsites.net`.
8. **Review audit logs**: `"Show me the audit log for today"`.

### Verify Weekly Report Delivery

- Check the configured Teams channel for the Adaptive Card report.
- Check the configured email recipients for the HTML report.
- Manually trigger via: `POST https://m365guardian-app.azurewebsites.net/api/report`.

---

## Switching the LLM Provider

M365 Guardian uses LiteLLM for provider-agnostic LLM access. To switch:

### To Azure OpenAI

```bash
az webapp config appsettings set --name "m365guardian-app" --resource-group $RESOURCE_GROUP \
  --settings \
    LLM_PROVIDER="azure_openai" \
    AZURE_OPENAI_API_KEY="your-key" \
    AZURE_OPENAI_ENDPOINT="https://your-instance.openai.azure.com/" \
    AZURE_OPENAI_DEPLOYMENT="gpt-4o" \
    LLM_MODEL="gpt-4o"
```

### To OpenAI Direct

```bash
az webapp config appsettings set --name "m365guardian-app" --resource-group $RESOURCE_GROUP \
  --settings LLM_PROVIDER="openai" OPENAI_API_KEY="your-key" LLM_MODEL="gpt-4o"
```

### To xAI (Grok)

```bash
az webapp config appsettings set --name "m365guardian-app" --resource-group $RESOURCE_GROUP \
  --settings LLM_PROVIDER="xai" XAI_API_KEY="your-key" LLM_MODEL="grok-2"
```

No code changes required — just update the environment variables and restart the app.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| 403 on Graph API calls | Check that admin consent was granted for all permissions |
| Bot doesn't respond in Teams | Verify the messaging endpoint URL matches your App Service URL + `/api/messages` |
| MFA check returns empty | Requires Azure AD Premium P1 license for authentication methods API |
| Risky sign-ins always empty | Requires Azure AD Premium P2 for Identity Protection |
| Weekly report not sending | Check the Azure Function logs and verify CRON schedule |
| LLM timeout | Increase `LLM_MAX_TOKENS` or check API key validity |
