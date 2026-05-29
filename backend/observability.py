"""
M365 Guardian — Observability.

Wires application telemetry (traces, metrics, logs) to Azure Application Insights
via OpenTelemetry. Gated on APPLICATIONINSIGHTS_CONNECTION_STRING: with no connection
string (local dev / tests) this is a no-op and logging stays console-only.

configure_azure_monitor() enables a set of default instrumentations but NOT the aiohttp
server or httpx client, so both are added explicitly:
- AioHttpServerInstrumentor — a span per incoming request (also correlates the logs emitted
  while handling it; trace/span ids attached automatically in App Insights).
- HTTPXClientInstrumentor — spans for outgoing httpx calls, i.e. Microsoft Graph (msgraph-sdk)
  and most LLM providers (litellm), so a chat turn shows its downstream calls end to end.
"""

import logging

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.instrumentation.aiohttp_server import AioHttpServerInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from backend.config import config

logger = logging.getLogger(__name__)

# Instrumentation patches global state, so guard against configuring twice
# (create_app may be called more than once, e.g. across tests).
_configured = False


def setup_observability() -> bool:
    """Configure Azure Monitor + aiohttp-server tracing. Idempotent and env-gated.

    Returns True if telemetry was configured, False if skipped (no connection string).
    """
    global _configured
    if _configured:
        return True
    if not config.appinsights_connection_string:
        logger.info("App Insights not configured — telemetry disabled (console logging only).")
        return False

    configure_azure_monitor(connection_string=config.appinsights_connection_string)
    # Neither aiohttp server nor httpx is among configure_azure_monitor's default instrumentations.
    AioHttpServerInstrumentor().instrument()  # incoming requests
    HTTPXClientInstrumentor().instrument()  # outgoing Graph + LLM calls
    _configured = True
    logger.info("Observability enabled — exporting traces/metrics/logs to App Insights.")
    return True
