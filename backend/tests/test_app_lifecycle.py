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


class _FakeSession:
    def __init__(self):
        self.initialized = False

    async def initialize(self):
        self.initialized = True


class _FakeReport:
    def __init__(self, graph):
        self.graph = graph


class _FakeBot:
    def __init__(self, llm, graph, audit, sessions):
        self.llm = llm
        self.graph = graph
        self.audit = audit
        self.sessions = sessions


class _FakeAdapter:
    def __init__(self, auth):
        self.auth = auth
        self.on_turn_error = None


def _patch_services(monkeypatch, *, bot_app_id="test-app-id"):
    monkeypatch.setattr(app_module, "LLMService", _FakeLLM)
    monkeypatch.setattr(app_module, "GraphService", _FakeGraph)
    monkeypatch.setattr(app_module, "AuditService", _FakeAudit)
    monkeypatch.setattr(app_module, "SessionService", _FakeSession)
    monkeypatch.setattr(app_module, "ReportService", _FakeReport)
    monkeypatch.setattr(app_module, "GuardianBot", _FakeBot)
    # CloudAdapter is built from ConfigurationBotFrameworkAuthentication; fake both so the
    # SingleTenant credential factory never validates/reaches the network.
    monkeypatch.setattr(app_module, "CloudAdapter", _FakeAdapter)
    monkeypatch.setattr(app_module, "ConfigurationBotFrameworkAuthentication", lambda cfg: cfg)
    # The adapter is only built when a bot app id is configured.
    monkeypatch.setattr(app_module.config.bot, "app_id", bot_app_id)
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
    sessions = app[app_module.SESSION_KEY]
    report = app[app_module.REPORT_KEY]
    bot = app[app_module.BOT_KEY]
    adapter = app[app_module.ADAPTER_KEY]

    assert isinstance(llm, _FakeLLM)
    assert isinstance(graph, _FakeGraph)
    assert isinstance(audit, _FakeAudit)
    assert isinstance(sessions, _FakeSession)

    # Audit and sessions are each initialized exactly once at startup.
    assert audit.initialized is True
    assert sessions.initialized is True

    # Bot and report service reuse the SAME shared instances — the single site.
    assert bot.llm is llm
    assert bot.graph is graph
    assert bot.audit is audit
    assert bot.sessions is sessions
    assert report.graph is graph

    # The bot adapter's turn-error handler is wired.
    assert adapter.on_turn_error is app_module.on_error

    # Cleanup releases the Graph credential transport.
    await app.cleanup()
    assert graph.closed is True


async def test_bot_adapter_disabled_without_creds(monkeypatch):
    # No bot app id → the Teams adapter is not built, but the rest of the app still starts.
    _patch_services(monkeypatch, bot_app_id="")
    app = app_module.create_app()

    app.on_startup.freeze()
    await app.startup()
    app.freeze()

    assert app.get(app_module.ADAPTER_KEY) is None
    # The bot itself is still constructed (used by the adapter when configured).
    assert app[app_module.BOT_KEY] is not None
    await app.cleanup()


def test_bot_uses_injected_services_without_constructing_them():
    llm, graph, audit, sessions = object(), object(), object(), object()
    bot = GuardianBot(llm=llm, graph=graph, audit=audit, sessions=sessions)

    assert bot.llm is llm
    assert bot.graph is graph
    assert bot.audit is audit
    assert bot.sessions is sessions
    # The old in-memory session dict is gone — sessions are durable now.
    assert not hasattr(bot, "_sessions")
