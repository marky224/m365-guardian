"""Tests for the app's shared-service lifecycle.

create_app builds every service exactly once in on_startup and stores it on the
aiohttp app; handlers then read them via request.app[...]. These tests drive the
real startup/cleanup signals with the services faked out, so nothing touches
Azure (no Graph credential, no Cosmos connection).
"""

import backend.app as app_module
from backend.bot import GuardianBot


class _FakeLLM:
    pass


class _FakeGraph:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeAudit:
    def __init__(self):
        self.initialized = False

    async def initialize(self):
        self.initialized = True


class _FakeReport:
    def __init__(self, graph):
        self.graph = graph


class _FakeBot:
    def __init__(self, llm, graph, audit):
        self.llm = llm
        self.graph = graph
        self.audit = audit


class _FakeAdapter:
    def __init__(self, settings):
        self.settings = settings
        self.on_turn_error = None


def _patch_services(monkeypatch):
    monkeypatch.setattr(app_module, "LLMService", _FakeLLM)
    monkeypatch.setattr(app_module, "GraphService", _FakeGraph)
    monkeypatch.setattr(app_module, "AuditService", _FakeAudit)
    monkeypatch.setattr(app_module, "ReportService", _FakeReport)
    monkeypatch.setattr(app_module, "GuardianBot", _FakeBot)
    monkeypatch.setattr(app_module, "BotFrameworkAdapter", _FakeAdapter)
    # create_app fails fast on invalid config; tests carry no real env, so bypass it.
    monkeypatch.setattr(app_module.config, "ensure_valid", lambda: None)


async def test_startup_builds_shared_services_once_and_wires_them(monkeypatch):
    _patch_services(monkeypatch)
    app = app_module.create_app()

    # Mirror AppRunner's production sequence: freeze the signal, run startup,
    # then freeze the whole app (so setting app state in on_startup is warning-free).
    app.on_startup.freeze()
    await app.startup()
    app.freeze()

    llm = app[app_module.LLM_KEY]
    graph = app[app_module.GRAPH_KEY]
    audit = app[app_module.AUDIT_KEY]
    report = app[app_module.REPORT_KEY]
    bot = app[app_module.BOT_KEY]
    adapter = app[app_module.ADAPTER_KEY]

    assert isinstance(llm, _FakeLLM)
    assert isinstance(graph, _FakeGraph)
    assert isinstance(audit, _FakeAudit)

    # Audit is initialized exactly once at startup (no per-request init).
    assert audit.initialized is True

    # Bot and report service reuse the SAME shared instances — the single site.
    assert bot.llm is llm
    assert bot.graph is graph
    assert bot.audit is audit
    assert report.graph is graph

    # The bot adapter's turn-error handler is wired.
    assert adapter.on_turn_error is app_module.on_error

    # Cleanup releases the Graph credential transport.
    await app.cleanup()
    assert graph.closed is True


def test_bot_uses_injected_services_without_constructing_them():
    llm, graph, audit = object(), object(), object()
    bot = GuardianBot(llm=llm, graph=graph, audit=audit)

    assert bot.llm is llm
    assert bot.graph is graph
    assert bot.audit is audit
    # The old lazy-init flag is gone — audit is initialized at app startup now.
    assert not hasattr(bot, "_audit_initialized")
