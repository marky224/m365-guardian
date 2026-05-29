"""Tests for configuration parsing and validation.

AppConfig reads environment variables in __post_init__, so each test constructs a
fresh AppConfig after setting env via monkeypatch. The real .env is gitignored and
absent in CI, so values come purely from the patched environment.
"""

import pytest

from backend.config import AppConfig, LLMConfig

# Minimal env that makes a config valid; individual tests remove pieces to test failure.
_VALID_ENV = {
    "AZURE_TENANT_ID": "tenant",
    "AZURE_CLIENT_ID": "client",
    "AZURE_CLIENT_SECRET": "secret",
    "LLM_PROVIDER": "anthropic",
    "ANTHROPIC_API_KEY": "sk-test",
    "SESSION_SECRET": "a-real-secret",
}


def _apply(monkeypatch, env, *, clear_keys=()):
    for k in (
        "AZURE_TENANT_ID",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "SESSION_SECRET",
        "PORT",
        "WEB_APP_PORT",
        "MFA_REQUIRED_GROUP_ID",
        "REPORT_EMAIL_RECIPIENTS",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for k in clear_keys:
        monkeypatch.delenv(k, raising=False)


def test_valid_config_has_no_errors(monkeypatch):
    _apply(monkeypatch, _VALID_ENV)
    cfg = AppConfig()
    assert cfg.validate() == []
    cfg.ensure_valid()  # must not raise


def test_missing_azure_fields_reported(monkeypatch):
    _apply(monkeypatch, _VALID_ENV, clear_keys=("AZURE_TENANT_ID", "AZURE_CLIENT_ID"))
    cfg = AppConfig()
    errors = cfg.validate()
    assert any("AZURE_TENANT_ID" in e for e in errors)
    assert any("AZURE_CLIENT_ID" in e for e in errors)


def test_missing_llm_key_reported(monkeypatch):
    _apply(monkeypatch, _VALID_ENV, clear_keys=("ANTHROPIC_API_KEY",))
    cfg = AppConfig()
    assert any("API key is required" in e for e in cfg.validate())


def test_default_session_secret_is_rejected(monkeypatch):
    env = dict(_VALID_ENV)
    env["SESSION_SECRET"] = "change-me-in-production"
    _apply(monkeypatch, env)
    cfg = AppConfig()
    assert any("SESSION_SECRET" in e for e in cfg.validate())


def test_ensure_valid_raises_with_all_errors(monkeypatch):
    _apply(monkeypatch, {})  # nothing set
    cfg = AppConfig()
    with pytest.raises(RuntimeError) as exc:
        cfg.ensure_valid()
    msg = str(exc.value)
    assert "AZURE_TENANT_ID" in msg
    assert "SESSION_SECRET" in msg


def test_provider_selects_matching_api_key_env(monkeypatch):
    env = dict(_VALID_ENV)
    env["LLM_PROVIDER"] = "xai"
    env["XAI_API_KEY"] = "xai-key"
    _apply(monkeypatch, env)
    cfg = AppConfig()
    assert cfg.llm.provider == "xai"
    assert cfg.llm.api_key == "xai-key"


def test_port_falls_back_through_options(monkeypatch):
    env = dict(_VALID_ENV)
    env["WEB_APP_PORT"] = "9001"
    _apply(monkeypatch, env)
    cfg = AppConfig()
    assert cfg.web_port == 9001


def test_email_recipients_parsed_as_list(monkeypatch):
    env = dict(_VALID_ENV)
    env["REPORT_EMAIL_RECIPIENTS"] = "a@x.com, b@x.com ,c@x.com"
    _apply(monkeypatch, env)
    cfg = AppConfig()
    assert cfg.report.email_recipients == ["a@x.com", "b@x.com", "c@x.com"]


def test_appinsights_connection_string_read(monkeypatch):
    _apply(monkeypatch, _VALID_ENV)
    assert AppConfig().appinsights_connection_string == ""  # unset → telemetry disabled

    env = dict(_VALID_ENV)
    env["APPLICATIONINSIGHTS_CONNECTION_STRING"] = "InstrumentationKey=xyz"
    _apply(monkeypatch, env)
    assert AppConfig().appinsights_connection_string == "InstrumentationKey=xyz"


def test_litellm_model_formatting(monkeypatch):
    _apply(monkeypatch, {"LLM_PROVIDER": "anthropic", "LLM_MODEL": "claude-x"})
    assert LLMConfig().litellm_model == "anthropic/claude-x"

    _apply(monkeypatch, {"LLM_PROVIDER": "xai", "LLM_MODEL": "grok-x"})
    assert LLMConfig().litellm_model == "xai/grok-x"

    _apply(monkeypatch, {"LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-x"})
    assert LLMConfig().litellm_model == "gpt-x"
