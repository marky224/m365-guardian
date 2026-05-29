"""Tests for the shared Layer 2 confirmation resolver (D-015).

Uses the real SessionService (in-memory mode) for pending storage and a real ToolExecutor
with a mocked GraphService, so the approve→execute path is exercised end to end without Azure.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from backend.confirmations import resolve_pending_confirmation
from backend.services.session_service import SessionService
from backend.tools.executor import ToolExecutor


async def _setup(tool, args, *, token="tok123", ttl_minutes=10):
    sessions = SessionService()  # in-memory fallback
    await sessions.get_or_create("k", owner_id="o")
    now = datetime.now(UTC)
    await sessions.set_pending(
        "k",
        "o",
        {
            "token": token,
            "fingerprint": ToolExecutor._fingerprint(tool, args),
            "tool": tool,
            "args": args,
            "summary": f"Run {tool}.",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        },
    )
    graph = AsyncMock()

    def build_executor(fingerprint):
        return ToolExecutor(
            graph=graph,
            audit=AsyncMock(),
            session_id="k",
            technician_id="t",
            technician_email="t@x",
            confirmed_fingerprint=fingerprint,
        )

    return sessions, graph, build_executor


async def test_approve_executes_stored_action_and_clears_pending():
    sessions, graph, build = await _setup("delete_user", {"user_id": "u1"})
    graph.delete_user.return_value = {"deleted": True}

    msg = await resolve_pending_confirmation(
        sessions=sessions, key="k", owner_id="o", token="tok123", decision="approve", build_executor=build
    )

    assert "Done" in msg
    graph.delete_user.assert_awaited_once_with("u1")
    assert await sessions.get_pending("k", "o") is None


async def test_wrong_token_is_rejected_and_pending_kept():
    sessions, graph, build = await _setup("delete_user", {"user_id": "u1"})

    msg = await resolve_pending_confirmation(
        sessions=sessions, key="k", owner_id="o", token="WRONG", decision="approve", build_executor=build
    )

    assert "no longer valid" in msg
    graph.delete_user.assert_not_called()
    # A wrong token must not consume the pending approval.
    assert await sessions.get_pending("k", "o") is not None


async def test_expired_token_is_rejected():
    sessions, graph, build = await _setup("delete_user", {"user_id": "u1"}, ttl_minutes=-1)

    msg = await resolve_pending_confirmation(
        sessions=sessions, key="k", owner_id="o", token="tok123", decision="approve", build_executor=build
    )

    assert "no longer valid" in msg
    graph.delete_user.assert_not_called()


async def test_cancel_clears_without_executing():
    sessions, graph, build = await _setup("delete_user", {"user_id": "u1"})

    msg = await resolve_pending_confirmation(
        sessions=sessions, key="k", owner_id="o", token="tok123", decision="cancel", build_executor=build
    )

    assert "Cancelled" in msg
    graph.delete_user.assert_not_called()
    assert await sessions.get_pending("k", "o") is None
