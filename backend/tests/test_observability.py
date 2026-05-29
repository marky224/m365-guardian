"""Tests for observability setup — env-gated and idempotent, with no real App Insights.

configure_azure_monitor and the aiohttp instrumentor are faked, so these never touch
the network or patch global aiohttp state.
"""

import backend.observability as obs


def test_setup_is_noop_without_connection_string(monkeypatch):
    monkeypatch.setattr(obs, "_configured", False)
    monkeypatch.setattr(obs.config, "appinsights_connection_string", "")

    calls = []
    monkeypatch.setattr(obs, "configure_azure_monitor", lambda **kw: calls.append(kw))

    assert obs.setup_observability() is False
    assert calls == []  # telemetry not configured


def test_setup_configures_once_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(obs, "_configured", False)
    monkeypatch.setattr(
        obs.config,
        "appinsights_connection_string",
        "InstrumentationKey=abc;IngestionEndpoint=https://x/",
    )

    monitor_calls = []
    monkeypatch.setattr(obs, "configure_azure_monitor", lambda **kw: monitor_calls.append(kw))

    instrument_calls = []

    class _FakeInstrumentor:
        def instrument(self):
            instrument_calls.append(True)

    monkeypatch.setattr(obs, "AioHttpServerInstrumentor", _FakeInstrumentor)

    assert obs.setup_observability() is True
    assert len(monitor_calls) == 1
    assert monitor_calls[0]["connection_string"].startswith("InstrumentationKey=")
    assert len(instrument_calls) == 1

    # Second call is a no-op (already configured) — no double instrumentation.
    assert obs.setup_observability() is True
    assert len(monitor_calls) == 1
    assert len(instrument_calls) == 1
