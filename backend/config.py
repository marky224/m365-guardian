"""
M365 Guardian — Configuration module.
Loads settings from environment variables with validation.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AzureADConfig:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""

    def __post_init__(self):
        self.tenant_id = os.getenv("AZURE_TENANT_ID", "")
        self.client_id = os.getenv("AZURE_CLIENT_ID", "")
        self.client_secret = os.getenv("AZURE_CLIENT_SECRET", "")

    def validate(self) -> list[str]:
        errors = []
        if not self.tenant_id:
            errors.append("AZURE_TENANT_ID is required")
        if not self.client_id:
            errors.append("AZURE_CLIENT_ID is required")
        if not self.client_secret:
            errors.append("AZURE_CLIENT_SECRET is required")
        return errors


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key: str = ""
    max_tokens: int = 4096
    temperature: float = 0.1

    def __post_init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "anthropic")
        self.model = os.getenv("LLM_MODEL", "claude-sonnet-4-20250514")
        key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "xai": "XAI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "azure_openai": "AZURE_OPENAI_API_KEY",
        }
        self.api_key = os.getenv(key_map.get(self.provider, "ANTHROPIC_API_KEY"), "")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))

    @property
    def litellm_model(self) -> str:
        """Return the model string formatted for LiteLLM."""
        provider_map = {
            "anthropic": f"anthropic/{self.model}",
            "azure_openai": f"azure/{os.getenv('AZURE_OPENAI_DEPLOYMENT', self.model)}",
            "openai": self.model,
            "xai": f"xai/{self.model}",
        }
        return provider_map.get(self.provider, self.model)


@dataclass
class CosmosConfig:
    endpoint: str = ""
    key: str = ""
    database: str = "m365guardian"
    sessions_container: str = "sessions"
    audit_container: str = "audit_logs"

    def __post_init__(self):
        self.endpoint = os.getenv("COSMOS_ENDPOINT", "")
        self.key = os.getenv("COSMOS_KEY", "")
        self.database = os.getenv("COSMOS_DATABASE", "m365guardian")
        self.sessions_container = os.getenv("COSMOS_SESSIONS_CONTAINER", "sessions")
        self.audit_container = os.getenv("COSMOS_AUDIT_CONTAINER", "audit_logs")


@dataclass
class BotConfig:
    app_id: str = ""
    app_password: str = ""
    app_type: str = "MultiTenant"

    def __post_init__(self):
        self.app_id = os.getenv("BOT_APP_ID", "")
        self.app_password = os.getenv("BOT_APP_PASSWORD", "")
        self.app_type = os.getenv("BOT_APP_TYPE", "MultiTenant")


@dataclass
class ReportConfig:
    teams_team_id: str = ""
    teams_channel_id: str = ""
    email_recipients: list[str] = field(default_factory=list)
    sender_upn: str = ""
    schedule_cron: str = "0 8 * * 1"

    def __post_init__(self):
        self.teams_team_id = os.getenv("REPORT_TEAMS_TEAM_ID", "")
        self.teams_channel_id = os.getenv("REPORT_TEAMS_CHANNEL_ID", "")
        raw = os.getenv("REPORT_EMAIL_RECIPIENTS", "")
        self.email_recipients = [e.strip() for e in raw.split(",") if e.strip()]
        self.sender_upn = os.getenv("REPORT_SENDER_UPN", "")
        self.schedule_cron = os.getenv("REPORT_SCHEDULE_CRON", "0 8 * * 1")


@dataclass
class AppConfig:
    azure_ad: AzureADConfig = field(default_factory=AzureADConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    cosmos: CosmosConfig = field(default_factory=CosmosConfig)
    bot: BotConfig = field(default_factory=BotConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    web_port: int = 8080
    base_url: str = ""
    log_level: str = "INFO"

    def __post_init__(self):
        self.web_port = int(os.getenv("WEB_APP_PORT", "8080"))
        self.base_url = os.getenv("WEB_APP_BASE_URL", "http://localhost:8080")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

    def validate(self) -> list[str]:
        errors = self.azure_ad.validate()
        if not self.llm.api_key:
            errors.append(f"API key is required for LLM_PROVIDER={self.llm.provider}")
        return errors


# Singleton
config = AppConfig()
