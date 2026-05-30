"""
M365 Guardian — Secret Provider.

Resolves the handful of unavoidable runtime secrets at process startup.

- **Local dev (KEY_VAULT_URL unset):** secrets come from the environment / .env,
  exactly as before. ``hydrate`` is a no-op.
- **Production (KEY_VAULT_URL set):** secrets are fetched from Azure Key Vault via
  ``DefaultAzureCredential`` (managed identity) and copied onto the in-memory config,
  each falling back to the existing env value if the vault entry is missing.

Graph (app-only) auth uses managed identity directly via ``DefaultAzureCredential``
in ``GraphService`` and does not pass through here. The MSAL web sign-in client needs a
confidential-client credential for the delegated auth-code flow: under Workload Identity
Federation (``AZURE_USE_WIF``, D-018) it is a managed-identity assertion, so the
``azure-client-secret`` vault entry is unnecessary and is skipped; otherwise the AAD client
secret is hydrated like the rest.
"""

import logging
import os

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from backend.config import AppConfig

logger = logging.getLogger(__name__)


class SecretProvider:
    """Hydrates config secrets from Key Vault when configured; else leaves env values."""

    def __init__(self, vault_url: str | None = None, *, client: SecretClient | None = None):
        # An explicit client (tests) forces KV mode; otherwise read KEY_VAULT_URL.
        self._vault_url = vault_url if vault_url is not None else os.getenv("KEY_VAULT_URL", "")
        self._credential: DefaultAzureCredential | None = None
        self._client = client
        self._owns_client = client is None

    @property
    def enabled(self) -> bool:
        """True when secrets should be sourced from Key Vault."""
        return self._client is not None or bool(self._vault_url)

    def hydrate(self, cfg: AppConfig) -> None:
        """Overwrite cfg's secret fields from Key Vault. No-op in local/env mode."""
        if not self.enabled:
            logger.info("KEY_VAULT_URL not set — using environment secrets (local mode).")
            return

        if self._client is None:
            self._credential = DefaultAzureCredential()
            self._client = SecretClient(vault_url=self._vault_url, credential=self._credential)

        # Under WIF the web sign-in uses a managed-identity assertion, so no secret is needed.
        if not cfg.azure_ad.use_wif:
            cfg.azure_ad.client_secret = self._get("azure-client-secret", cfg.azure_ad.client_secret)
        cfg.llm.api_key = self._get("llm-api-key", cfg.llm.api_key)
        cfg.bot.app_password = self._get("bot-app-password", cfg.bot.app_password)
        cfg.cosmos.key = self._get("cosmos-key", cfg.cosmos.key)
        cfg.session_secret = self._get("session-secret", cfg.session_secret)
        logger.info("Secrets hydrated from Key Vault.")

    def _get(self, name: str, fallback: str) -> str:
        """Fetch a secret by name, falling back to the env-sourced value on any failure."""
        assert self._client is not None  # set by hydrate() before this is called
        try:
            value = self._client.get_secret(name).value
            return value if value else fallback
        except Exception as e:
            # Never log the secret itself — only the failure type — and keep running on env.
            logger.warning(f"Key Vault secret '{name}' unavailable; using fallback ({type(e).__name__}).")
            return fallback

    def close(self) -> None:
        """Release the vault client and credential. Safe to call once after hydrate()."""
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:  # pragma: no cover - best-effort shutdown
                pass
        if self._credential is not None:
            try:
                self._credential.close()
            except Exception:  # pragma: no cover - best-effort shutdown
                pass
