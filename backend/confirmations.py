"""
M365 Guardian — Layer 2 confirmation resolution (D-015).

Shared, surface-agnostic logic for approving/cancelling a pending write. Both the web
endpoint and the Teams bot funnel through here so the security-critical path has a single,
tested implementation: validate the approval token in code against the session's
server-stored pending record, then execute the *stored* action via a fingerprint grant.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from backend.services.session_service import SessionService
from backend.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


async def resolve_pending_confirmation(
    *,
    sessions: SessionService,
    key: str,
    owner_id: str,
    token: str,
    decision: str,
    build_executor: Callable[[str], ToolExecutor],
    now: datetime | None = None,
) -> str:
    """Approve or cancel the pending write for (key, owner_id); return a result message.

    ``build_executor(fingerprint)`` constructs a ToolExecutor pre-granted for that fingerprint.
    On approval the stored (tool, args) is executed — never model-reconstructed — and the outcome
    is recorded in the session transcript for conversational coherence.
    """
    now = now or datetime.now(UTC)

    if decision == "cancel":
        await sessions.clear_pending(key, owner_id)
        return "❌ Cancelled — no change was made."

    pending = await sessions.get_pending(key, owner_id)
    if not SessionService.is_pending_valid(pending, token, now):
        return "⚠️ This approval is no longer valid (it expired or was already used). Please ask for the change again."
    assert pending is not None  # guaranteed by is_pending_valid

    summary = pending.get("summary", "the requested change")
    executor = build_executor(pending["fingerprint"])
    try:
        result = await executor.execute(pending["tool"], pending["args"])
    except Exception:
        error_id = uuid.uuid4().hex[:8]
        logger.error("Confirmed action failed [error_id=%s]", error_id, exc_info=True)
        # Clear the stuck approval so the technician can re-request rather than re-fail.
        await sessions.clear_pending(key, owner_id)
        return f"⚠️ The approved change could not be completed (reference `{error_id}`)."

    await sessions.clear_pending(key, owner_id)
    if isinstance(result, dict) and (result.get("error") or result.get("success") is False):
        reason = result.get("reason") or result.get("error") or "see logs"
        message = f"⚠️ Could not complete: {summary} ({reason})"
    else:
        message = f"✅ Done — {summary}"

    # Record the outcome in the durable transcript so the conversation stays coherent.
    sess = await sessions.get_or_create(key, owner_id)
    history = sess["history"]
    history.append({"role": "assistant", "content": message})
    await sessions.save(key, owner_id, history)

    return message
