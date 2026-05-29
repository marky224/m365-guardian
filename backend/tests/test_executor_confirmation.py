"""Tests for the ToolExecutor write-confirmation gate (Layer 1 + Layer 2).

GraphService and AuditService are injected as mocks, so no Microsoft Graph
dependencies are needed. Layer 2 (D-015): a write executes only when its
fingerprint matches a grant the handler sets after a human approval — the
model's `confirm` flag no longer authorizes anything.
"""

from unittest.mock import AsyncMock

from backend.tools.executor import ToolExecutor


def _make_executor(mfa_required_group_id="", confirmed_fingerprint=None):
    graph = AsyncMock()
    audit = AsyncMock()
    executor = ToolExecutor(
        graph=graph,
        audit=audit,
        session_id="s1",
        technician_id="tech1",
        technician_email="tech@contoso.com",
        mfa_required_group_id=mfa_required_group_id,
        confirmed_fingerprint=confirmed_fingerprint,
    )
    return executor, graph, audit


async def _execute_confirmed(executor, tool, args):
    """Mirror prod: propose (mints pending) → grant its fingerprint → execute stored args."""
    proposed = await executor.execute(tool, args)
    assert proposed.get("confirmation_required"), proposed
    pending = executor.pending_confirmation
    executor.confirmed_fingerprint = pending["fingerprint"]
    return await executor.execute(pending["tool"], pending["args"])


# ── Gate basics ──────────────────────────────────────────────────────


async def test_write_without_grant_is_blocked():
    executor, graph, audit = _make_executor()

    result = await executor.execute("delete_user", {"user_id": "u1"})

    assert result["confirmation_required"] is True
    assert result["tool"] == "delete_user"
    assert "u1" in result["summary"]
    # Graph must never be touched without an approval grant.
    graph.delete_user.assert_not_called()
    # The confirmation request must be recorded in the audit trail.
    audit.log_action.assert_awaited_once()
    assert audit.log_action.await_args.kwargs["status"] == "pending_confirmation"


async def test_pending_is_minted_and_token_not_leaked_to_model():
    executor, _, _ = _make_executor()

    result = await executor.execute("delete_user", {"user_id": "u1"})
    pending = executor.pending_confirmation

    assert pending is not None
    assert pending["tool"] == "delete_user"
    assert pending["fingerprint"] == ToolExecutor._fingerprint("delete_user", {"user_id": "u1"})
    assert len(pending["token"]) >= 6
    # The token must never reach the model — only the handler reads pending_confirmation.
    assert "token" not in result


async def test_confirm_flag_alone_does_not_authorize():
    # The core Layer 2 property: a prompt-injected model that sets confirm=true on its own
    # cannot self-approve a write.
    executor, graph, _ = _make_executor()

    result = await executor.execute("delete_user", {"user_id": "u1", "confirm": True})

    assert result["confirmation_required"] is True
    graph.delete_user.assert_not_called()


async def test_granted_write_executes():
    executor, graph, _ = _make_executor()
    graph.delete_user.return_value = {"user_id": "u1", "deleted": True}

    result = await _execute_confirmed(executor, "delete_user", {"user_id": "u1"})

    assert result == {"user_id": "u1", "deleted": True}
    graph.delete_user.assert_awaited_once_with("u1")


async def test_grant_for_different_args_reprompts():
    # A grant is bound to an exact (tool, args) fingerprint; mutated args aren't covered.
    fp = ToolExecutor._fingerprint("delete_user", {"user_id": "u1"})
    executor, graph, _ = _make_executor(confirmed_fingerprint=fp)

    result = await executor.execute("delete_user", {"user_id": "u2"})

    assert result["confirmation_required"] is True
    graph.delete_user.assert_not_called()


async def test_confirm_flag_is_not_forwarded_to_graph():
    executor, graph, _ = _make_executor()
    graph.update_user.return_value = {"success": True}

    await _execute_confirmed(
        executor,
        "update_user",
        {"user_id": "u1", "updates": {"department": "IT"}, "confirm": True},
    )

    # confirm must be stripped before dispatch — Graph sees only the real args.
    graph.update_user.assert_awaited_once_with("u1", {"department": "IT"})


def test_fingerprint_is_stable_and_arg_sensitive():
    a = ToolExecutor._fingerprint("delete_user", {"user_id": "u1"})
    assert a == ToolExecutor._fingerprint("delete_user", {"user_id": "u1"})
    assert a != ToolExecutor._fingerprint("delete_user", {"user_id": "u2"})
    assert a != ToolExecutor._fingerprint("reset_password", {"user_id": "u1"})


async def test_read_tool_runs_without_confirmation():
    executor, graph, _ = _make_executor()
    graph.search_users.return_value = [{"id": "u1"}]

    result = await executor.execute("search_users", {"query": "jane"})

    assert result["count"] == 1
    graph.search_users.assert_awaited_once()


async def test_unknown_tool_returns_error():
    executor, _, _ = _make_executor()

    result = await executor.execute("does_not_exist", {})

    assert "error" in result


async def test_every_write_tool_has_a_custom_description():
    executor, _, _ = _make_executor()
    for tool in executor.WRITE_TOOLS:
        summary = executor._describe_action(tool, {})
        # Each write tool must have a tailored summary, not the generic fallback.
        assert summary
        assert summary != f"Perform '{tool}'."


# ── Real vs. honest-limited tool handlers ────────────────────────────


async def test_manage_group_membership_add_calls_graph():
    executor, graph, _ = _make_executor()
    graph.add_group_member.return_value = {"success": True}

    result = await _execute_confirmed(
        executor,
        "manage_group_membership",
        {"action": "add", "user_id": "u1", "group_id": "g1"},
    )

    graph.add_group_member.assert_awaited_once_with("g1", "u1")
    assert result["success"] is True


async def test_manage_group_membership_remove_calls_graph():
    executor, graph, _ = _make_executor()
    graph.remove_group_member.return_value = {"success": True}

    await _execute_confirmed(
        executor,
        "manage_group_membership",
        {"action": "remove", "user_id": "u1", "group_id": "g1"},
    )

    graph.remove_group_member.assert_awaited_once_with("g1", "u1")


async def test_manage_group_membership_invalid_action_errors():
    executor, graph, _ = _make_executor()

    # Invalid args fail validation BEFORE the gate → structured error, no confirmation.
    result = await executor.execute(
        "manage_group_membership",
        {"action": "promote", "user_id": "u1", "group_id": "g1"},
    )

    assert "error" in result
    graph.add_group_member.assert_not_called()
    graph.remove_group_member.assert_not_called()


async def test_shared_mailbox_is_honest_not_implemented():
    executor, graph, _ = _make_executor()

    result = await _execute_confirmed(
        executor,
        "manage_shared_mailbox",
        {"action": "create", "mailbox_address": "team@contoso.com"},
    )

    assert result["success"] is False
    assert result["not_implemented"] is True
    assert "Exchange Online PowerShell" in result["reason"]
    # No fake Graph call must be made.
    assert not graph.method_calls


async def test_distribution_group_is_honest_not_implemented():
    executor, graph, _ = _make_executor()

    result = await _execute_confirmed(
        executor,
        "manage_distribution_group",
        {"action": "create", "group_email": "all@contoso.com"},
    )

    assert result["success"] is False
    assert result["not_implemented"] is True
    assert not graph.method_calls
