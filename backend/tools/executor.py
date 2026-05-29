"""
M365 Guardian — Tool Executor.
Routes LLM tool calls to the appropriate Graph API service methods.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from backend.tools.validation import TOOL_ARG_MODELS

if TYPE_CHECKING:
    from backend.services.audit_service import AuditService
    from backend.services.graph_service import GraphService

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tool calls from the LLM by dispatching to the Graph service.
    All write operations are logged via the audit service.
    """

    # Tools that modify data and require explicit confirmation
    WRITE_TOOLS = {
        "create_user",
        "update_user",
        "delete_user",
        "reset_password",
        "enforce_mfa",
        "assign_license",
        "remove_license",
        "manage_group_membership",
        "manage_shared_mailbox",
        "manage_distribution_group",
        "bulk_operation",
        "send_report_to_teams",
        "send_report_via_email",
    }

    def __init__(
        self,
        graph: GraphService,
        audit: AuditService,
        session_id: str = "",
        technician_id: str = "",
        technician_email: str = "",
        mfa_required_group_id: str = "",
    ):
        self.graph = graph
        self.audit = audit
        self.session_id = session_id
        self.technician_id = technician_id
        self.technician_email = technician_email
        # Entra group an MFA Conditional Access policy targets; injected so the
        # executor stays decoupled from the global config singleton (and unit-testable).
        self.mfa_required_group_id = mfa_required_group_id

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """
        Execute a tool call and return the result.

        Write tools are gated: they cannot reach Microsoft Graph unless the call
        carries an explicit ``confirm=true``. Without it, a structured
        ``confirmation_required`` payload is returned and nothing is executed.
        The gate is enforced here in code, not just in the system prompt, so a
        hallucinated or prompt-injected tool call cannot perform a write on its
        own. Every attempt (confirmation request, success, failure) is audited.
        """
        handler = self._get_handler(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        is_write = tool_name in self.WRITE_TOOLS

        confirmed = False
        if is_write:
            confirmed = bool(arguments.get("confirm"))
            # Never forward the confirm flag down to the Graph layer.
            arguments = {k: v for k, v in arguments.items() if k != "confirm"}

        # Validate (and normalize) arguments before doing anything else, so a
        # malformed call returns a structured error the LLM can correct — not a
        # KeyError, and not a confirmation prompt for an action that can't run.
        validation = self._validate_arguments(tool_name, arguments)
        if validation.get("invalid"):
            return validation["error"]
        arguments = validation["args"]

        if is_write and not confirmed:
            summary = self._describe_action(tool_name, arguments)
            await self.audit.log_action(
                session_id=self.session_id,
                technician_id=self.technician_id,
                technician_email=self.technician_email,
                action=f"CONFIRMATION_REQUESTED: {tool_name}",
                tool_name=tool_name,
                tool_args=arguments,
                status="pending_confirmation",
            )
            return {
                "confirmation_required": True,
                "tool": tool_name,
                "summary": summary,
                "message": (
                    f"⚠️ Confirmation required before this change is made. {summary} "
                    "Present this to the technician and proceed only after they explicitly "
                    f"approve. To execute, call {tool_name} again with confirm=true."
                ),
            }

        try:
            result = await handler(arguments)

            # Log to audit trail
            await self.audit.log_action(
                session_id=self.session_id,
                technician_id=self.technician_id,
                technician_email=self.technician_email,
                action=f"{'WRITE' if is_write else 'READ'}: {tool_name}",
                tool_name=tool_name,
                tool_args=arguments,
                result=result,
                status="success",
            )

            return result

        except Exception as e:
            # Log the failure
            await self.audit.log_action(
                session_id=self.session_id,
                technician_id=self.technician_id,
                technician_email=self.technician_email,
                action=f"{'WRITE' if is_write else 'READ'}: {tool_name}",
                tool_name=tool_name,
                tool_args=arguments,
                status="error",
                error=str(e),
            )
            raise

    def _validate_arguments(self, tool_name: str, arguments: dict) -> dict:
        """Validate/normalize tool arguments against the tool's pydantic model.

        Returns ``{"args": <normalized dict>}`` on success, or
        ``{"invalid": True, "error": <structured error>}`` on failure. Tools with
        no registered model pass through unchanged.
        """
        model = TOOL_ARG_MODELS.get(tool_name)
        if model is None:
            return {"args": arguments}

        try:
            normalized = model(**arguments).model_dump(exclude_none=True)
            return {"args": normalized}
        except ValidationError as e:
            details = [
                {"field": ".".join(str(p) for p in err["loc"]) or "(root)", "message": err["msg"]} for err in e.errors()
            ]
            logger.warning("Invalid arguments for %s: %s", tool_name, details)
            return {
                "invalid": True,
                "error": {
                    "error": "invalid_arguments",
                    "tool": tool_name,
                    "details": details,
                    "message": (
                        f"The arguments for '{tool_name}' are invalid. "
                        "Correct them per the listed details and call the tool again."
                    ),
                },
            }

    def _describe_action(self, tool_name: str, args: dict) -> str:
        """Human-readable summary of a pending write, shown to the technician for approval."""
        descriptions = {
            "create_user": (f"Create user '{args.get('display_name', '?')}' ({args.get('user_principal_name', '?')})."),
            "update_user": (
                f"Update user {args.get('user_id', '?')}: "
                f"{', '.join((args.get('updates') or {}).keys()) or 'no fields'}."
            ),
            "delete_user": (f"Delete user {args.get('user_id', '?')} (soft-delete, 30-day recovery window)."),
            "reset_password": f"Reset the password for user {args.get('user_id', '?')}.",
            "enforce_mfa": (
                f"Set MFA enforcement to '{args.get('mfa_state', 'enforced')}' for user "
                f"{args.get('user_id', '?')} (via the Conditional Access MFA group)."
            ),
            "assign_license": (f"Assign license {args.get('sku_id', '?')} to user {args.get('user_id', '?')}."),
            "remove_license": (f"Remove license {args.get('sku_id', '?')} from user {args.get('user_id', '?')}."),
            "manage_group_membership": (
                f"{args.get('action', '?')} user {args.get('user_id', '?')} in group {args.get('group_id', '?')}."
            ),
            "manage_shared_mailbox": (f"{args.get('action', '?')} shared mailbox {args.get('mailbox_address', '?')}."),
            "manage_distribution_group": (
                f"{args.get('action', '?')} distribution group {args.get('group_email', '?')}."
            ),
            "bulk_operation": (f"Bulk '{args.get('operation', '?')}' on {len(args.get('user_ids') or [])} user(s)."),
            "send_report_to_teams": "Post the security report to the configured Teams channel.",
            "send_report_via_email": "Email the security report to the configured recipients.",
        }
        return descriptions.get(tool_name, f"Perform '{tool_name}'.")

    def _get_handler(self, tool_name: str):
        """Map tool name to handler method."""
        handlers = {
            "search_users": self._search_users,
            "get_user_details": self._get_user_details,
            "create_user": self._create_user,
            "update_user": self._update_user,
            "delete_user": self._delete_user,
            "reset_password": self._reset_password,
            "enforce_mfa": self._enforce_mfa,
            "list_available_licenses": self._list_licenses,
            "assign_license": self._assign_license,
            "remove_license": self._remove_license,
            "manage_group_membership": self._manage_group,
            "manage_shared_mailbox": self._manage_shared_mailbox,
            "manage_distribution_group": self._manage_dist_group,
            "check_mailbox_status": self._check_mailbox,
            "generate_weekly_insights_report": self._generate_report,
            "send_report_to_teams": self._send_teams_report,
            "send_report_via_email": self._send_email_report,
            "get_audit_log": self._get_audit_log,
            "bulk_operation": self._bulk_operation,
        }
        return handlers.get(tool_name)

    # ── HANDLER IMPLEMENTATIONS ──────────────────────────────────────

    async def _search_users(self, args: dict) -> dict:
        users = await self.graph.search_users(
            query=args["query"],
            odata_filter=args.get("filter"),
            select=args.get("select"),
            top=args.get("top", 10),
        )
        return {"users": users, "count": len(users)}

    async def _get_user_details(self, args: dict) -> dict:
        return await self.graph.get_user_details(
            user_id=args["user_id"],
            include_mfa=args.get("include_mfa", True),
            include_sign_in=args.get("include_sign_in_activity", True),
            include_groups=args.get("include_groups", False),
        )

    async def _create_user(self, args: dict) -> dict:
        result = await self.graph.create_user(
            display_name=args["display_name"],
            mail_nickname=args["mail_nickname"],
            user_principal_name=args["user_principal_name"],
            password=args["password"],
            force_change=args.get("force_change_password", True),
            account_enabled=args.get("account_enabled", True),
            department=args.get("department"),
            job_title=args.get("job_title"),
            usage_location=args.get("usage_location"),
        )

        # Optionally assign license
        if args.get("license_sku_id"):
            try:
                await self.graph.assign_license(result["id"], args["license_sku_id"])
                result["license_assigned"] = True
                result["license_sku_id"] = args["license_sku_id"]
            except Exception as e:
                result["license_error"] = str(e)

        return result

    async def _update_user(self, args: dict) -> dict:
        return await self.graph.update_user(args["user_id"], args["updates"])

    async def _delete_user(self, args: dict) -> dict:
        return await self.graph.delete_user(args["user_id"])

    async def _reset_password(self, args: dict) -> dict:
        return await self.graph.reset_password(
            user_id=args["user_id"],
            new_password=args.get("new_password"),
            force_change=args.get("force_change_at_next_sign_in", True),
        )

    async def _enforce_mfa(self, args: dict) -> dict:
        """Enforce/relax MFA for a user via group-based Conditional Access.

        Production approach (Microsoft-recommended): the user is added to / removed from an
        Entra ID security group that an admin-created Conditional Access policy targets to
        require MFA. Legacy per-user MFA (perUserMfaState) is a beta API Microsoft marks "not
        supported in production" and is intentionally NOT implemented here — we return an honest
        result instead of faking success.
        """
        method = args.get("method", "conditional_access")

        # Explicit request for guidance only.
        if method == "conditional_access_recommendation":
            return {
                "recommendation": (
                    "Create a Conditional Access policy requiring MFA, targeting the MFA security "
                    "group (Entra ID > Protection > Conditional Access > New Policy; Grant > "
                    "Require multifactor authentication). M365 Guardian manages group membership, "
                    "not the policy itself."
                ),
                "note": "M365 Guardian cannot create or modify Conditional Access policies directly.",
            }

        # Legacy per-user MFA is not supported (beta-only, Microsoft-discouraged).
        if method == "per_user_mfa":
            return {
                "success": False,
                "not_implemented": True,
                "user_id": args["user_id"],
                "reason": (
                    "Legacy per-user MFA (perUserMfaState) is a beta API that Microsoft marks "
                    "'not supported in production' and is being deprecated in favor of Conditional "
                    "Access. Use method='conditional_access' (the default) instead."
                ),
            }

        # Group-based Conditional Access (the supported, default path).
        group_id = self.mfa_required_group_id
        if not group_id:
            return {
                "success": False,
                "not_configured": True,
                "user_id": args["user_id"],
                "reason": (
                    "MFA enforcement via Conditional Access requires an MFA security group, but "
                    "MFA_REQUIRED_GROUP_ID is not configured. Ask an admin to create a security "
                    "group, target it with a Conditional Access 'require MFA' policy, and set "
                    "MFA_REQUIRED_GROUP_ID. Then M365 Guardian can manage membership."
                ),
            }

        # mfa_state controls direction: enforced/enabled -> require MFA (add); disabled -> remove.
        state = args.get("mfa_state", "enforced").lower()
        if state == "disabled":
            result = await self.graph.remove_group_member(group_id, args["user_id"])
            action = "removed from"
        else:
            result = await self.graph.add_group_member(group_id, args["user_id"])
            action = "added to"

        return {
            "success": True,
            "user_id": args["user_id"],
            "mfa_state": state,
            "method": "conditional_access",
            "mfa_group_id": group_id,
            "note": (
                f"User {action} the MFA-required security group. MFA is enforced by the "
                "Conditional Access policy targeting that group, per Microsoft best practice."
            ),
            "graph_result": result,
        }

    async def _list_licenses(self, args: dict) -> dict:
        licenses = await self.graph.list_licenses(args.get("include_disabled", False))
        return {"licenses": licenses, "count": len(licenses)}

    async def _assign_license(self, args: dict) -> dict:
        return await self.graph.assign_license(args["user_id"], args["sku_id"], args.get("disabled_plans"))

    async def _remove_license(self, args: dict) -> dict:
        return await self.graph.remove_license(args["user_id"], args["sku_id"])

    async def _manage_group(self, args: dict) -> dict:
        action = args["action"]
        if action == "add":
            return await self.graph.add_group_member(args["group_id"], args["user_id"])
        if action == "remove":
            return await self.graph.remove_group_member(args["group_id"], args["user_id"])
        return {
            "error": f"Unsupported group action: {action}",
            "supported_actions": ["add", "remove"],
        }

    async def _manage_shared_mailbox(self, args: dict) -> dict:
        # Honest limitation: shared-mailbox management is not exposed by Microsoft
        # Graph. It requires Exchange Online PowerShell (app-only certificate auth),
        # which this service does not yet run. We return not_implemented rather than
        # a fake success so the technician is never told a change happened when it did not.
        return {
            "success": False,
            "not_implemented": True,
            "action": args["action"],
            "mailbox_address": args.get("mailbox_address"),
            "reason": (
                "Shared mailbox management is not available via Microsoft Graph. It requires "
                "Exchange Online PowerShell (planned: an app-only EXO PowerShell sidecar). "
                "Perform this in the Exchange admin center for now."
            ),
        }

    async def _manage_dist_group(self, args: dict) -> dict:
        # Honest limitation: distribution groups are read-only in Microsoft Graph and
        # cannot be created/modified there — Exchange Online PowerShell is required.
        return {
            "success": False,
            "not_implemented": True,
            "action": args["action"],
            "group_email": args.get("group_email"),
            "reason": (
                "Distribution group management is not available via Microsoft Graph (groups are "
                "read-only there). It requires Exchange Online PowerShell (planned: an app-only "
                "EXO PowerShell sidecar). Perform this in the Exchange admin center for now."
            ),
        }

    async def _check_mailbox(self, args: dict) -> dict:
        return await self.graph.get_mailbox_status(args["user_id"])

    async def _generate_report(self, args: dict) -> dict:
        """Run all 10 security checks and compile the report."""
        from backend.services.report_service import ReportService

        report_svc = ReportService(self.graph)
        return await report_svc.generate(
            checks=args.get("checks"),
            lookback_days=args.get("lookback_days", 7),
            dormant_threshold=args.get("dormant_threshold_days", 90),
        )

    async def _send_teams_report(self, args: dict) -> dict:
        """Return the report for display in the current Teams conversation."""
        from backend.services.report_service import ReportService

        report_svc = ReportService(self.graph)
        report = await report_svc.generate()
        return {"sent_to_teams": True, "delivered_in": "current_conversation", "report": report}

    async def _send_email_report(self, args: dict) -> dict:
        """Email delivery is planned for Phase 2."""
        return {
            "sent_to_email": False,
            "note": "Email delivery is not yet implemented. The report is available in the current conversation.",
        }

    async def _get_audit_log(self, args: dict) -> dict:
        logs = await self.audit.query_logs(
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            action_type=args.get("action_type"),
            performed_by=args.get("performed_by"),
            top=args.get("top", 25),
        )
        return {"logs": logs, "count": len(logs)}

    async def _bulk_operation(self, args: dict) -> dict:
        results = []
        for uid in args["user_ids"]:
            try:
                if args["operation"] == "reset_password":
                    r = await self.graph.reset_password(uid)
                elif args["operation"] == "assign_license":
                    r = await self.graph.assign_license(uid, args["parameters"]["sku_id"])
                elif args["operation"] == "remove_license":
                    r = await self.graph.remove_license(uid, args["parameters"]["sku_id"])
                elif args["operation"] in ("enable_account", "disable_account"):
                    enabled = args["operation"] == "enable_account"
                    r = await self.graph.update_user(uid, {"accountEnabled": enabled})
                else:
                    r = {"user_id": uid, "skipped": True, "reason": "Unsupported operation"}
                results.append({"user_id": uid, "status": "success", "result": r})
            except Exception as e:
                results.append({"user_id": uid, "status": "error", "error": str(e)})
        return {"operation": args["operation"], "results": results, "total": len(results)}
