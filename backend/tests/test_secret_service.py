"""Tests for the SecretProvider (Key Vault vs environment secret resolution).

A fake SecretClient is injected so nothing touches Azure. Local mode is the
no-KEY_VAULT_URL path; KV mode overwrites config secret fields, with env fallback
when a vault entry is missing, empty, or errors.
"""

from types import SimpleNamespace

from backend.config import AppConfig
from backend.services.secret_service import SecretProvider


class _FakeSecretClient:
    def __init__(self, secrets: dict[str, str], *, erroring: tuple[str, ...] = ()):
        self._secrets = secrets
        self._erroring = set(erroring)
        self.closed = False

    def get_secret(self, name: str):
        if name in self._erroring:
            raise RuntimeError("vault error")
        if name not in self._secrets:
            raise RuntimeError("SecretNotFound")
        return SimpleNamespace(value=self._secrets[name])

    def close(self):
        self.closed = True


def _config_with_env_sentinels() -> AppConfig:
    cfg = AppConfig()
    cfg.azure_ad.client_secret = "env-azure-secret"
    cfg.llm.api_key = "env-llm-key"
    cfg.bot.app_password = "env-bot-pass"
    cfg.cosmos.key = "env-cosmos-key"
    cfg.session_secret = "env-session-secret"
    return cfg


def test_env_mode_is_noop(monkeypatch):
    monkeypatch.delenv("KEY_VAULT_URL", raising=False)
    provider = SecretProvider()
    assert provider.enabled is False

    cfg = _config_with_env_sentinels()
    provider.hydrate(cfg)

    assert cfg.azure_ad.client_secret == "env-azure-secret"
    assert cfg.llm.api_key == "env-llm-key"
    assert cfg.session_secret == "env-session-secret"


def test_kv_mode_overwrites_all_secrets():
    fake = _FakeSecretClient(
        {
            "azure-client-secret": "kv-azure",
            "llm-api-key": "kv-llm",
            "bot-app-password": "kv-bot",
            "cosmos-key": "kv-cosmos",
            "session-secret": "kv-session",
        }
    )
    provider = SecretProvider(client=fake)
    assert provider.enabled is True

    cfg = _config_with_env_sentinels()
    provider.hydrate(cfg)

    assert cfg.azure_ad.client_secret == "kv-azure"
    assert cfg.llm.api_key == "kv-llm"
    assert cfg.bot.app_password == "kv-bot"
    assert cfg.cosmos.key == "kv-cosmos"
    assert cfg.session_secret == "kv-session"


def test_kv_missing_secret_keeps_env_value():
    # Only one secret present in the vault; the rest are absent.
    fake = _FakeSecretClient({"llm-api-key": "kv-llm"})
    cfg = _config_with_env_sentinels()
    SecretProvider(client=fake).hydrate(cfg)

    assert cfg.llm.api_key == "kv-llm"  # present → overwritten
    assert cfg.azure_ad.client_secret == "env-azure-secret"  # absent → env fallback
    assert cfg.cosmos.key == "env-cosmos-key"


def test_kv_empty_value_falls_back():
    fake = _FakeSecretClient({"llm-api-key": ""})  # present but blank
    cfg = _config_with_env_sentinels()
    SecretProvider(client=fake).hydrate(cfg)

    assert cfg.llm.api_key == "env-llm-key"  # blank vault value → env fallback


def test_kv_error_falls_back_without_raising():
    fake = _FakeSecretClient(
        {},
        erroring=(
            "azure-client-secret",
            "llm-api-key",
            "bot-app-password",
            "cosmos-key",
            "session-secret",
        ),
    )
    cfg = _config_with_env_sentinels()
    SecretProvider(client=fake).hydrate(cfg)  # must not raise

    assert cfg.llm.api_key == "env-llm-key"
    assert cfg.azure_ad.client_secret == "env-azure-secret"


def test_close_does_not_close_injected_client():
    fake = _FakeSecretClient({})
    provider = SecretProvider(client=fake)
    provider.hydrate(_config_with_env_sentinels())
    provider.close()
    assert fake.closed is False  # a borrowed (injected) client is not owned, so not closed
