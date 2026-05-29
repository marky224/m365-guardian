"""Pydantic models that validate LLM tool-call arguments before execution.

Each tool's arguments are validated against a model so a malformed call returns a
structured error the LLM can self-correct from, instead of raising a raw KeyError
deep inside a handler. Validation also coerces obvious types (e.g. "10" -> 10) and
materializes documented defaults.

The ``confirm`` flag is handled by the executor's confirmation gate and is
intentionally NOT part of these models — the executor strips it before validating.
Unknown fields are ignored (``extra="ignore"``) so minor LLM deviations don't break
a call, while missing required fields and wrong types are rejected.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _ToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── Read tools ───────────────────────────────────────────────────────


class SearchUsersArgs(_ToolArgs):
    query: str
    filter: str | None = None
    select: list[str] | None = None
    top: int = 10


class GetUserDetailsArgs(_ToolArgs):
    user_id: str
    include_mfa: bool = True
    include_sign_in_activity: bool = True
    include_groups: bool = False


class ListLicensesArgs(_ToolArgs):
    include_disabled: bool = False


class CheckMailboxStatusArgs(_ToolArgs):
    user_id: str


class GenerateReportArgs(_ToolArgs):
    checks: list[str] | None = None
    lookback_days: int = 7
    dormant_threshold_days: int = 90


class GetAuditLogArgs(_ToolArgs):
    start_date: str | None = None
    end_date: str | None = None
    action_type: str | None = None
    performed_by: str | None = None
    top: int = 25


# ── Write tools ──────────────────────────────────────────────────────


class CreateUserArgs(_ToolArgs):
    display_name: str
    mail_nickname: str
    user_principal_name: str
    password: str
    force_change_password: bool = True
    account_enabled: bool = True
    department: str | None = None
    job_title: str | None = None
    usage_location: str | None = None
    license_sku_id: str | None = None


class UpdateUserArgs(_ToolArgs):
    user_id: str
    updates: dict[str, Any]


class DeleteUserArgs(_ToolArgs):
    user_id: str


class ResetPasswordArgs(_ToolArgs):
    user_id: str
    new_password: str | None = None
    force_change_at_next_sign_in: bool = True


class EnforceMfaArgs(_ToolArgs):
    user_id: str
    method: str = "conditional_access"
    mfa_state: str = "enforced"


class AssignLicenseArgs(_ToolArgs):
    user_id: str
    sku_id: str
    disabled_plans: list[str] | None = None


class RemoveLicenseArgs(_ToolArgs):
    user_id: str
    sku_id: str


class ManageGroupMembershipArgs(_ToolArgs):
    action: Literal["add", "remove"]
    user_id: str
    group_id: str


class ManageSharedMailboxArgs(_ToolArgs):
    action: str
    mailbox_address: str
    display_name: str | None = None
    members: list[str] | None = None


class ManageDistributionGroupArgs(_ToolArgs):
    action: str
    group_email: str
    display_name: str | None = None
    members: list[str] | None = None


class SendReportToTeamsArgs(_ToolArgs):
    pass


class SendReportViaEmailArgs(_ToolArgs):
    recipients: list[str] | None = None


class BulkOperationArgs(_ToolArgs):
    operation: Literal[
        "reset_password",
        "assign_license",
        "remove_license",
        "enable_account",
        "disable_account",
    ]
    user_ids: list[str]
    parameters: dict[str, Any] | None = None


# Registry: tool name -> argument model. Must stay in lockstep with the handlers
# in executor.py and the schemas in docs/02_TOOL_SCHEMAS.json.
TOOL_ARG_MODELS: dict[str, type[_ToolArgs]] = {
    "search_users": SearchUsersArgs,
    "get_user_details": GetUserDetailsArgs,
    "create_user": CreateUserArgs,
    "update_user": UpdateUserArgs,
    "delete_user": DeleteUserArgs,
    "reset_password": ResetPasswordArgs,
    "enforce_mfa": EnforceMfaArgs,
    "list_available_licenses": ListLicensesArgs,
    "assign_license": AssignLicenseArgs,
    "remove_license": RemoveLicenseArgs,
    "manage_group_membership": ManageGroupMembershipArgs,
    "manage_shared_mailbox": ManageSharedMailboxArgs,
    "manage_distribution_group": ManageDistributionGroupArgs,
    "check_mailbox_status": CheckMailboxStatusArgs,
    "generate_weekly_insights_report": GenerateReportArgs,
    "send_report_to_teams": SendReportToTeamsArgs,
    "send_report_via_email": SendReportViaEmailArgs,
    "get_audit_log": GetAuditLogArgs,
    "bulk_operation": BulkOperationArgs,
}
