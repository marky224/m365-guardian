"""Tests for the ToolExecutor server-side write-confirmation gate.

These exercise the safety-critical gate in isolation: GraphService and
AuditService are injected as mocks, so no Microsoft Graph dependencies are
needed to run them.
"""

from unittest.mock import AsyncMock

from backend.tools.executor import ToolExecutor


def _make_executor(mfa_required_group_id=""):
    graph = AsyncMock()
    audit = AsyncMock()
    executor = ToolExecutor(
        graph=graph,
        audit=audit,
        session_id="s1",
        technician_id="tech1",
        technician_email="tech@contoso.com",
        mfa_required_group_id=mfa_required_group_id,
    )
    return executor, graph, audit


async def test_write_without_confirm_is_blocked():
    executor, graph, audit = _make_executor()

    result = await executor.execute("delete_user", {"user_id": "u1"})

    assert result["confirmation_required"] is True
    assert result["tool"] == "delete_user"
    assert "u1" in result["summary"]
    # Graph must never be touched without confirmation.
    graph.delete_user.assert_not_called()
    # The confirmation request must be recorded in the audit trail.
    audit.log_action.assert_awaited_once()
    assert audit.log_action.await_args.kwargs["status"] == "pending_confirmation"


async def test_write_with_confirm_executes():
    executor, graph, _ = _make_executor()
    graph.delete_user.return_value = {"user_id": "u1", "deleted": True}

    result = await executor.execute("delete_user", {"user_id": "u1", "confirm": True})

    assert result == {"user_id": "u1", "deleted": True}
    graph.delete_user.assert_awaited_once_with("u1")


async def test_confirm_flag_is_not_forwarded_to_graph():
    executor, graph, _ = _make_executor()
    graph.update_user.return_value = {"success": True}

    await executor.execute(
        "update_user",
        {"user_id": "u1", "updates": {"department": "IT"}, "confirm": True},
    )

    # confirm must be stripped before dispatch — Graph sees only the real args.
    graph.update_user.assert_awaited_once_with("u1", {"department": "IT"})


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


# ── Task 6: real vs. honest-limited tool handlers ────────────────────


async def test_manage_group_membership_add_calls_graph():
    executor, graph, _ = _make_executor()
    graph.add_group_member.return_value = {"success": True}

    result = await executor.execute(
        "manage_group_membership",
        {"action": "add", "user_id": "u1", "group_id": "g1", "confirm": True},
    )

    graph.add_group_member.assert_awaited_once_with("g1", "u1")
    assert result["success"] is True


async def test_manage_group_membership_remove_calls_graph():
    executor, graph, _ = _make_executor()
    graph.remove_group_member.return_value = {"success": True}

    await executor.execute(
        "manage_group_membership",
        {"action": "remove", "user_id": "u1", "group_id": "g1", "confirm": True},
    )

    graph.remove_group_member.assert_awaited_once_with("g1", "u1")


async def test_manage_group_membership_invalid_action_errors():
    executor, graph, _ = _make_executor()

    result = await executor.execute(
        "manage_group_membership",
        {"action": "promote", "user_id": "u1", "group_id": "g1", "confirm": True},
    )

    assert "error" in result
    graph.add_group_member.assert_not_called()
    graph.remove_group_member.assert_not_called()


async def test_shared_mailbox_is_honest_not_implemented():
    executor, graph, _ = _make_executor()

    result = await executor.execute(
        "manage_shared_mailbox",
        {"action": "create", "mailbox_address": "team@contoso.com", "confirm": True},
    )

    assert result["success"] is False
    assert result["not_implemented"] is True
    assert "Exchange Online PowerShell" in result["reason"]
    # No fake Graph call must be made.
    assert not graph.method_calls


async def test_distribution_group_is_honest_not_implemented():
    executor, graph, _ = _make_executor()

    result = await executor.execute(
        "manage_distribution_group",
        {"action": "create", "group_email": "all@contoso.com", "confirm": True},
    )

    assert result["success"] is False
    assert result["not_implemented"] is True
    assert not graph.method_calls


async def test_check_mailbox_status_calls_graph():
    executor, graph, _ = _make_executor()
    graph.get_mailbox_status.return_value = {"user_id": "u1", "mailbox_exists": True}

    result = await executor.execute("check_mailbox_status", {"user_id": "u1"})

    graph.get_mailbox_status.assert_awaited_once_with("u1")
    assert result["mailbox_exists"] is True


# ── Task 5: enforce_mfa via group-based Conditional Access ────────────


async def test_enforce_mfa_enforced_adds_to_group():
    executor, graph, _ = _make_executor(mfa_required_group_id="mfa-group-1")
    graph.add_group_member.return_value = {"success": True}

    result = await executor.execute("enforce_mfa", {"user_id": "u1", "mfa_state": "enforced", "confirm": True})

    graph.add_group_member.assert_awaited_once_with("mfa-group-1", "u1")
    graph.remove_group_member.assert_not_called()
    assert result["success"] is True
    assert result["method"] == "conditional_access"


async def test_enforce_mfa_disabled_removes_from_group():
    executor, graph, _ = _make_executor(mfa_required_group_id="mfa-group-1")
    graph.remove_group_member.return_value = {"success": True}

    result = await executor.execute("enforce_mfa", {"user_id": "u1", "mfa_state": "disabled", "confirm": True})

    graph.remove_group_member.assert_awaited_once_with("mfa-group-1", "u1")
    graph.add_group_member.assert_not_called()
    assert result["success"] is True


async def test_enforce_mfa_not_configured_is_honest():
    executor, graph, _ = _make_executor(mfa_required_group_id="")

    result = await executor.execute("enforce_mfa", {"user_id": "u1", "confirm": True})

    assert result["success"] is False
    assert result["not_configured"] is True
    graph.add_group_member.assert_not_called()
    graph.remove_group_member.assert_not_called()


async def test_enforce_mfa_legacy_per_user_is_honest():
    executor, graph, _ = _make_executor(mfa_required_group_id="mfa-group-1")

    result = await executor.execute("enforce_mfa", {"user_id": "u1", "method": "per_user_mfa", "confirm": True})

    assert result["success"] is False
    assert result["not_implemented"] is True
    # Must not touch the group even though one is configured.
    graph.add_group_member.assert_not_called()
    graph.remove_group_member.assert_not_called()


async def test_enforce_mfa_recommendation_only():
    executor, graph, _ = _make_executor()

    result = await executor.execute(
        "enforce_mfa",
        {"user_id": "u1", "method": "conditional_access_recommendation", "confirm": True},
    )

    assert "recommendation" in result
    graph.add_group_member.assert_not_called()
