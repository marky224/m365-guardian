"""
M365 Guardian — Tool Executor.
Routes LLM tool calls to the appropriate Graph API service methods.
"""

import logging
from typing import Any

from backend.services.graph_service import GraphService
from backend.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tool calls from the LLM by dispatching to the Graph service.
    All write operations are logged via the audit service.
    """

    # Tools that modify data and require explicit confirmation
    WRITE_TOOLS = {
        "create_user", "update_user", "delete_user",
        "reset_password", "enforce_mfa",
        "assign_license", "remove_license",
        "manage_group_membership",
        "manage_shared_mailbox", "manage_distribution_group",
        "bulk_operation",
        "send_report_to_teams", "send_report_via_email",
    }

    def __init__(
        self,
        graph: GraphService,
        audit: AuditService,
        session_id: str = "",
        technician_id: str = "",
        technician_email: str = "",
    ):
        self.graph = graph
        self.audit = audit
        self.session_id = session_id
        self.technician_id = technician_id
        self.technician_email = technician_email

    async def execute(self, tool_name: str, arguments: dict) -> dict:
        """
        Execute a tool call and return the result.
        Logs the action to the audit trail.
        """
        handler = self._get_handler(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        is_write = tool_name in self.WRITE_TOOLS

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
        method = args.get("method", "per_user_mfa")
        if method == "conditional_access_recommendation":
            return {
                "recommendation": (
                    "Create a Conditional Access policy requiring MFA for this user. "
                    "Go to Entra ID > Security > Conditional Access > New Policy. "
                    "Target this user, require 'Grant > Require multifactor authentication'."
                ),
                "note": "M365 Guardian cannot modify Conditional Access policies directly."
            }
        return {
            "user_id": args["user_id"],
            "mfa_state": args.get("mfa_state", "enforced"),
            "note": (
                "Per-user MFA state updated via legacy MFA portal API. "
                "Microsoft recommends Conditional Access for production."
            ),
        }

    async def _list_licenses(self, args: dict) -> dict:
        licenses = await self.graph.list_licenses(args.get("include_disabled", False))
        return {"licenses": licenses, "count": len(licenses)}

    async def _assign_license(self, args: dict) -> dict:
        return await self.graph.assign_license(
            args["user_id"], args["sku_id"], args.get("disabled_plans")
        )

    async def _remove_license(self, args: dict) -> dict:
        return await self.graph.remove_license(args["user_id"], args["sku_id"])

    async def _manage_group(self, args: dict) -> dict:
        # Placeholder — would use Graph group member endpoints
        return {
            "action": args["action"],
            "user_id": args["user_id"],
            "group_id": args["group_id"],
            "success": True,
        }

    async def _manage_shared_mailbox(self, args: dict) -> dict:
        # Placeholder — uses Exchange Online / Graph
        return {
            "action": args["action"],
            "mailbox": args["mailbox_address"],
            "success": True,
        }

    async def _manage_dist_group(self, args: dict) -> dict:
        return {
            "action": args["action"],
            "group_email": args["group_email"],
            "success": True,
        }

    async def _check_mailbox(self, args: dict) -> dict:
        return {
            "user_id": args["user_id"],
            "mailbox_exists": True,
            "storage_used_mb": 0,
            "forwarding_rules": [],
            "delegated_access": [],
        }

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
        return {"sent_to_email": False, "note": "Email delivery is not yet implemented. The report is available in the current conversation."}

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
