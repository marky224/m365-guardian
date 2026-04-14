"""
M365 Guardian — Main Application.
Serves the Teams bot endpoint, the standalone web app, and the scheduled report job.
"""

import logging
import os
import sys

from aiohttp import web
from aiohttp.web import Request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity

from backend.config import config
from backend.bot import GuardianBot
from backend.services.audit_service import AuditService

# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="%(asctime)s | %(name)-25s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("m365guardian")


# ── Bot Framework Adapter ────────────────────────────────────────────

adapter_settings = BotFrameworkAdapterSettings(
    app_id=config.bot.app_id,
    app_password=config.bot.app_password,
)
adapter = BotFrameworkAdapter(adapter_settings)

# Error handler
async def on_error(context, error):
    logger.error(f"Bot error: {error}")
    await context.send_activity("⚠️ An unexpected error occurred. The incident has been logged.")

adapter.on_turn_error = on_error

# Bot instance
bot = GuardianBot()


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

    response = await adapter.process_activity(activity, auth_header, bot.on_turn)
    if response:
        return web.json_response(response.body, status=response.status)
    return Response(status=201)


async def web_chat(request: Request) -> Response:
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
    import json
    import uuid
    from backend.services.llm_service import LLMService
    from backend.services.graph_service import GraphService
    from backend.tools.executor import ToolExecutor

    body = await request.json()
    user_message = body.get("message", "")
    session_id = body.get("session_id", str(uuid.uuid4()))
    history = body.get("history", [])

    llm = LLMService()
    graph = GraphService()
    audit = AuditService()

    executor = ToolExecutor(
        graph=graph,
        audit=audit,
        session_id=session_id,
        technician_id=body.get("user_id", "web-user"),
        technician_email=body.get("user_email", "web-user@unknown"),
    )

    try:
        response_text, updated_history = await llm.chat_with_tool_loop(
            user_message=user_message,
            conversation_history=history,
            session_context={
                "technician_name": body.get("user_name", "Web User"),
                "technician_email": body.get("user_email", ""),
                "session_id": session_id,
            },
            tool_executor=executor.execute,
        )

        return web.json_response({
            "response": response_text,
            "session_id": session_id,
            "history": updated_history,
        })
    except Exception as e:
        logger.error(f"Web chat error: {e}")
        return web.json_response(
            {"error": str(e)},
            status=500,
        )


async def trigger_report(request: Request) -> Response:
    """Manually trigger the weekly insights report."""
    from backend.services.graph_service import GraphService
    from backend.services.report_service import ReportService

    graph = GraphService()
    report_svc = ReportService(graph)

    try:
        report = await report_svc.generate()
        return web.json_response(report)
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return web.json_response({"error": str(e)}, status=500)


# ── App Factory ──────────────────────────────────────────────────────

def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()

    # Routes
    app.router.add_get("/health", health)
    app.router.add_post("/api/messages", messages)          # Teams bot endpoint
    app.router.add_get("/", web_chat)                        # Web chat UI
    app.router.add_post("/api/chat", web_api_chat)           # Web chat API
    app.router.add_post("/api/report", trigger_report)       # Manual report trigger

    # Static files for web app
    static_path = os.path.join(os.path.dirname(__file__), "web-app", "static")
    if os.path.exists(static_path):
        app.router.add_static("/static/", static_path)

    # Startup tasks
    async def on_startup(app):
        audit = AuditService()
        await audit.initialize()
        logger.info(f"M365 Guardian started on port {config.web_port}")

    app.on_startup.append(on_startup)

    return app


# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=config.web_port)
