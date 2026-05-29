"""
M365 Guardian — Main Application.
Serves the Teams bot endpoint, the standalone web app, and the scheduled report job.
Includes Entra ID authentication for web routes.
"""

import hashlib
import logging
import os
import uuid

import msal
from aiohttp import web
from aiohttp.web import Request, Response
from aiohttp_session import get_session
from aiohttp_session import setup as session_setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity

from backend.bot import GuardianBot
from backend.config import config
from backend.services.audit_service import AuditService
from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService
from backend.services.report_service import ReportService
from backend.services.secret_service import SecretProvider
from backend.tools.executor import ToolExecutor

# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="%(asctime)s | %(name)-25s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("m365guardian")


# ── Shared service registry keys ─────────────────────────────────────
# Services are built exactly once in on_startup and stored on the app;
# handlers read them via request.app[...]. Typed AppKeys keep this
# mypy-checked and give later work a single place to swap construction.

LLM_KEY: web.AppKey[LLMService] = web.AppKey("llm", LLMService)
GRAPH_KEY: web.AppKey[GraphService] = web.AppKey("graph", GraphService)
AUDIT_KEY: web.AppKey[AuditService] = web.AppKey("audit", AuditService)
REPORT_KEY: web.AppKey[ReportService] = web.AppKey("report_svc", ReportService)
BOT_KEY: web.AppKey[GuardianBot] = web.AppKey("bot", GuardianBot)
ADAPTER_KEY: web.AppKey[BotFrameworkAdapter] = web.AppKey("adapter", BotFrameworkAdapter)


# Bot Framework turn-error handler
async def on_error(context, error):
    logger.error(f"Bot error: {error}")
    await context.send_activity("⚠️ An unexpected error occurred. The incident has been logged.")


# ── MSAL Helper ──────────────────────────────────────────────────────


def _get_msal_app() -> msal.ConfidentialClientApplication:
    """Create an MSAL confidential client for Entra ID auth."""
    return msal.ConfidentialClientApplication(
        config.azure_ad.client_id,
        authority=f"https://login.microsoftonline.com/{config.azure_ad.tenant_id}",
        client_credential=config.azure_ad.client_secret,
    )


# ── Auth Middleware ──────────────────────────────────────────────────

# Routes that do NOT require authentication
OPEN_PREFIXES = ("/health", "/api/messages", "/auth/", "/static/")


@web.middleware
async def auth_middleware(request, handler):
    """Require Entra ID sign-in for protected web routes."""
    if any(request.path.startswith(p) for p in OPEN_PREFIXES):
        return await handler(request)

    session = await get_session(request)
    if not session.get("user"):
        raise web.HTTPFound("/auth/login")

    return await handler(request)


# ── Auth Routes ──────────────────────────────────────────────────────


async def auth_login(request: Request) -> Response:
    """Redirect the user to Microsoft sign-in."""
    msal_app = _get_msal_app()
    auth_url = msal_app.get_authorization_request_url(
        scopes=["User.Read"],
        redirect_uri=f"{config.base_url}/auth/callback",
    )
    raise web.HTTPFound(auth_url)


async def auth_callback(request: Request) -> Response:
    """Handle the OAuth2 callback from Entra ID."""
    code = request.query.get("code")
    error = request.query.get("error")

    if error:
        logger.warning(f"Auth callback error: {error} - {request.query.get('error_description', '')}")
        return web.Response(
            text=f"Authentication failed: {request.query.get('error_description', error)}",
            status=401,
            content_type="text/html",
        )

    if not code:
        raise web.HTTPFound("/auth/login")

    msal_app = _get_msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=["User.Read"],
        redirect_uri=f"{config.base_url}/auth/callback",
    )

    if "access_token" in result:
        claims = result.get("id_token_claims", {})
        session = await get_session(request)
        session["user"] = {
            "name": claims.get("name", "Unknown"),
            "email": claims.get("preferred_username", ""),
            "oid": claims.get("oid", ""),
            "tenant_id": claims.get("tid", ""),
        }
        logger.info(f"User signed in: {claims.get('preferred_username', 'unknown')}")
        raise web.HTTPFound("/")

    logger.warning(f"Token acquisition failed: {result.get('error_description', 'unknown error')}")
    return web.Response(
        text="Authentication failed. Please try again.",
        status=401,
        content_type="text/html",
    )


async def auth_logout(request: Request) -> Response:
    """Clear the session and redirect to Microsoft sign-out."""
    session = await get_session(request)
    user_email = session.get("user", {}).get("email", "unknown")
    session.clear()
    logger.info(f"User signed out: {user_email}")

    # Redirect to Microsoft sign-out, then back to health page
    logout_url = (
        f"https://login.microsoftonline.com/{config.azure_ad.tenant_id}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={config.base_url}/health"
    )
    raise web.HTTPFound(logout_url)


async def auth_me(request: Request) -> Response:
    """Return the current authenticated user's info."""
    session = await get_session(request)
    user = session.get("user")
    if not user:
        return web.json_response({"authenticated": False}, status=401)
    return web.json_response({"authenticated": True, "user": user})


# ── Routes ───────────────────────────────────────────────────────────


async def health(request: Request) -> Response:
    """Health check endpoint."""
    return web.json_response({"status": "healthy", "service": "m365-guardian"})


async def messages(request: Request) -> Response:
    """Bot Framework messages endpoint (for Teams)."""
    if "application/json" not in (request.content_type or ""):
        return Response(status=415)

    body = await request.json()
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    adapter = request.app[ADAPTER_KEY]
    bot = request.app[BOT_KEY]
    response = await adapter.process_activity(activity, auth_header, bot.on_turn)
    if response:
        return web.json_response(response.body, status=response.status)
    return Response(status=201)


async def web_chat(request: Request) -> web.StreamResponse:
    """Serve the standalone web chat interface."""
    html_path = os.path.join(os.path.dirname(__file__), "web-app", "templates", "index.html")
    if os.path.exists(html_path):
        return web.FileResponse(html_path)
    # Fallback
    return web.Response(
        text="<h1>M365 Guardian Web Chat</h1><p>Web interface loading...</p>",
        content_type="text/html",
    )


async def web_api_chat(request: Request) -> Response:
    """REST API endpoint for the web chat interface."""
    # Get authenticated user from session
    session = await get_session(request)
    user = session.get("user", {})

    body = await request.json()
    user_message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    history = body.get("history", [])

    # Shared services are built once at startup; only the executor is
    # per-request (it is bound to this technician's identity and session).
    llm = request.app[LLM_KEY]
    graph = request.app[GRAPH_KEY]
    audit = request.app[AUDIT_KEY]

    executor = ToolExecutor(
        graph=graph,
        audit=audit,
        session_id=session_id,
        technician_id=user.get("oid", body.get("user_id", "web-user")),
        technician_email=user.get("email", body.get("user_email", "web-user@unknown")),
        mfa_required_group_id=config.security.mfa_required_group_id,
    )

    try:
        response_text, updated_history = await llm.chat_with_tool_loop(
            user_message=user_message,
            conversation_history=history,
            session_context={
                "technician_name": user.get("name", body.get("user_name", "Web User")),
                "technician_email": user.get("email", body.get("user_email", "")),
                "session_id": session_id,
            },
            tool_executor=executor.execute,
        )

        return web.json_response(
            {
                "response": response_text,
                "session_id": session_id,
                "history": updated_history,
            }
        )
    except Exception as e:
        error_id = uuid.uuid4().hex[:8]
        logger.error(f"Web chat error [error_id={error_id}]: {e}")
        return web.json_response(
            {
                "error": "An internal error occurred while processing your request.",
                "error_id": error_id,
            },
            status=500,
        )


async def trigger_report(request: Request) -> Response:
    """Manually trigger the weekly insights report."""
    report_svc = request.app[REPORT_KEY]

    try:
        report = await report_svc.generate()
        return web.json_response(report)
    except Exception as e:
        error_id = uuid.uuid4().hex[:8]
        logger.error(f"Report generation failed [error_id={error_id}]: {e}")
        return web.json_response(
            {"error": "Report generation failed.", "error_id": error_id},
            status=500,
        )


# ── App Factory ──────────────────────────────────────────────────────


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    # Resolve secrets before anything reads them: Key Vault in prod (KEY_VAULT_URL),
    # environment/.env locally. hydrate() is synchronous, so it runs here — ahead of
    # session_setup, which derives the cookie key from the (now hydrated) session_secret.
    secrets = SecretProvider()
    secrets.hydrate(config)
    secrets.close()
    config.ensure_valid()  # fail fast on missing/placeholder configuration

    app = web.Application()

    # Session setup FIRST — must be registered before auth middleware
    secret_key = hashlib.sha256(config.session_secret.encode()).digest()
    session_setup(app, EncryptedCookieStorage(secret_key, cookie_name="m365guardian_session"))

    # Auth middleware AFTER session setup
    app.middlewares.append(auth_middleware)

    # Auth routes
    app.router.add_get("/auth/login", auth_login)
    app.router.add_get("/auth/callback", auth_callback)
    app.router.add_get("/auth/logout", auth_logout)
    app.router.add_get("/auth/me", auth_me)

    # App routes
    app.router.add_get("/health", health)
    app.router.add_post("/api/messages", messages)  # Teams bot endpoint
    app.router.add_get("/", web_chat)  # Web chat UI
    app.router.add_post("/api/chat", web_api_chat)  # Web chat API
    app.router.add_post("/api/report", trigger_report)  # Manual report trigger

    # Static files for web app
    static_path = os.path.join(os.path.dirname(__file__), "web-app", "static")
    if os.path.exists(static_path):
        app.router.add_static("/static/", static_path)

    # Startup: build every shared service exactly once and stash on the app.
    async def on_startup(app: web.Application) -> None:
        llm = LLMService()
        graph = GraphService()
        audit = AuditService()
        await audit.initialize()

        adapter = BotFrameworkAdapter(
            BotFrameworkAdapterSettings(
                app_id=config.bot.app_id,
                app_password=config.bot.app_password,
                channel_auth_tenant=config.azure_ad.tenant_id,
            )
        )
        adapter.on_turn_error = on_error

        app[LLM_KEY] = llm
        app[GRAPH_KEY] = graph
        app[AUDIT_KEY] = audit
        app[REPORT_KEY] = ReportService(graph)
        app[BOT_KEY] = GuardianBot(llm=llm, graph=graph, audit=audit)
        app[ADAPTER_KEY] = adapter

        logger.info(f"M365 Guardian started on port {config.web_port}")

    # Cleanup: release the Graph credential transport on shutdown.
    async def on_cleanup(app: web.Application) -> None:
        graph = app.get(GRAPH_KEY)
        if graph is not None:
            try:
                graph.close()
            except Exception as e:  # never raise during shutdown
                logger.warning(f"Error closing Graph credential: {e}")

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=config.web_port)
