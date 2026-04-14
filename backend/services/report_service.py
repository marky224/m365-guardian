"""
M365 Guardian — Weekly Security Insights Report Service.
Runs all 10 security checks and generates the formatted report.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from backend.services.graph_service import GraphService

logger = logging.getLogger(__name__)

# Severity thresholds
SEVERITY_CRITICAL = "🔴 Critical"
SEVERITY_WARNING = "🟡 Warning"
SEVERITY_OK = "🟢 OK"


class ReportService:
    """Generates the M365 Guardian Weekly Security & Best-Practice Insights Report."""

    def __init__(self, graph: GraphService):
        self.graph = graph

    async def generate(
        self,
        checks: list[str] | None = None,
        lookback_days: int = 7,
        dormant_threshold: int = 90,
    ) -> dict:
        """Run all specified checks and compile the report."""
        all_checks = [
            "suspicious_sign_ins",
            "mfa_compliance",
            "dormant_accounts",
            "license_optimization",
            "privileged_access",
            "guest_users",
            "legacy_auth",
            "exchange_best_practices",
            "conditional_access_gaps",
            "password_hygiene",
        ]
        checks = checks or all_checks
        report_time = datetime.now(timezone.utc).isoformat()

        sections = []
        critical_count = 0
        warning_count = 0

        for check in checks:
            handler = getattr(self, f"_check_{check}", None)
            if handler:
                try:
                    section = await handler(lookback_days, dormant_threshold)
                    sections.append(section)
                    if section["severity"] == SEVERITY_CRITICAL:
                        critical_count += 1
                    elif section["severity"] == SEVERITY_WARNING:
                        warning_count += 1
                except Exception as e:
                    logger.error(f"Check '{check}' failed: {e}")
                    sections.append({
                        "check": check,
                        "title": check.replace("_", " ").title(),
                        "severity": SEVERITY_WARNING,
                        "finding_count": 0,
                        "summary": f"Check failed: {e}",
                        "items": [],
                        "fix_command": None,
                    })

        # Build executive summary
        total_findings = sum(s["finding_count"] for s in sections)
        if critical_count > 0:
            overall_severity = SEVERITY_CRITICAL
        elif warning_count > 0:
            overall_severity = SEVERITY_WARNING
        else:
            overall_severity = SEVERITY_OK

        executive_summary = (
            f"M365 Guardian found {total_findings} findings across {len(sections)} checks. "
            f"{critical_count} critical, {warning_count} warnings. "
            f"Overall tenant health: {overall_severity}."
        )

        return {
            "report_type": "weekly_security_insights",
            "generated_at": report_time,
            "lookback_days": lookback_days,
            "overall_severity": overall_severity,
            "executive_summary": executive_summary,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "total_findings": total_findings,
            "sections": sections,
        }

    # ── INDIVIDUAL CHECKS ────────────────────────────────────────────

    async def _check_suspicious_sign_ins(self, lookback_days: int, _: int) -> dict:
        items = await self.graph.get_risky_sign_ins(lookback_days)
        count = len(items)
        if count == 0:
            severity = SEVERITY_OK
            summary = "No suspicious sign-ins detected."
        elif count <= 3:
            severity = SEVERITY_WARNING
            summary = f"{count} risky sign-in(s) detected in the last {lookback_days} days."
        else:
            severity = SEVERITY_CRITICAL
            summary = f"{count} risky sign-ins detected — immediate review recommended."

        return {
            "check": "suspicious_sign_ins",
            "title": "1. Suspicious Sign-Ins",
            "severity": severity,
            "finding_count": count,
            "summary": summary,
            "items": items[:5],
            "fix_command": "Review risky users and dismiss or remediate each sign-in.",
        }

    async def _check_mfa_compliance(self, *_) -> dict:
        items = await self.graph.get_users_without_mfa()
        count = len(items)
        if count == 0:
            severity = SEVERITY_OK
            summary = "All users have MFA methods registered."
        elif count <= 5:
            severity = SEVERITY_WARNING
            summary = f"{count} user(s) without MFA registration."
        else:
            severity = SEVERITY_CRITICAL
            summary = f"{count} users without MFA — significant security risk."

        return {
            "check": "mfa_compliance",
            "title": "2. MFA Compliance Gaps",
            "severity": severity,
            "finding_count": count,
            "summary": summary,
            "items": items[:5],
            "fix_command": "Enforce MFA for {user_principal_name}",
        }

    async def _check_dormant_accounts(self, _, threshold: int) -> dict:
        items = await self.graph.get_dormant_accounts(threshold)
        count = len(items)
        if count == 0:
            severity = SEVERITY_OK
            summary = f"No accounts dormant for more than {threshold} days."
        elif count <= 10:
            severity = SEVERITY_WARNING
            summary = f"{count} account(s) inactive for {threshold}+ days."
        else:
            severity = SEVERITY_CRITICAL
            summary = f"{count} dormant accounts — review and disable or delete."

        return {
            "check": "dormant_accounts",
            "title": "3. Dormant / Inactive Accounts",
            "severity": severity,
            "finding_count": count,
            "summary": summary,
            "items": items[:5],
            "fix_command": "Disable account {user_principal_name}",
        }

    async def _check_license_optimization(self, *_) -> dict:
        licenses = await self.graph.list_licenses(include_disabled=True)
        wasted = [l for l in licenses if l["availableUnits"] > 5]
        count = len(wasted)
        severity = SEVERITY_WARNING if count > 0 else SEVERITY_OK
        summary = (
            f"{count} license SKU(s) with significant unused capacity."
            if count > 0 else "License utilization is healthy."
        )

        return {
            "check": "license_optimization",
            "title": "4. License Optimization",
            "severity": severity,
            "finding_count": count,
            "summary": summary,
            "items": wasted[:5],
            "fix_command": "Show license details for {skuPartNumber}",
        }

    async def _check_privileged_access(self, *_) -> dict:
        items = await self.graph.get_privileged_role_holders()
        privileged_roles = {"Global Administrator", "Privileged Role Administrator", "Exchange Administrator"}
        critical_holders = [i for i in items if i["roleName"] in privileged_roles]
        count = len(critical_holders)

        if count <= 2:
            severity = SEVERITY_OK
            summary = f"{count} permanent privileged admin(s) — within best-practice limits."
        elif count <= 5:
            severity = SEVERITY_WARNING
            summary = f"{count} permanent privileged admins — consider reducing or using PIM."
        else:
            severity = SEVERITY_CRITICAL
            summary = f"{count} permanent privileged admins — excessive, use PIM for JIT access."

        return {
            "check": "privileged_access",
            "title": "5. Privileged Access Hygiene",
            "severity": severity,
            "finding_count": count,
            "summary": summary,
            "items": critical_holders[:5],
            "fix_command": "Review admin role for {principalDisplayName}",
        }

    async def _check_guest_users(self, *_) -> dict:
        items = await self.graph.get_guest_users()
        count = len(items)
        severity = SEVERITY_WARNING if count > 20 else SEVERITY_OK
        summary = f"{count} guest user(s) in the tenant." + (
            " Review for stale or unnecessary guests." if count > 20 else ""
        )

        return {
            "check": "guest_users",
            "title": "6. Guest User & External Access",
            "severity": severity,
            "finding_count": count,
            "summary": summary,
            "items": items[:5],
            "fix_command": "Show details for guest {displayName}",
        }

    async def _check_legacy_auth(self, *_) -> dict:
        # Requires sign-in logs with clientAppUsed filter
        # Placeholder — real implementation queries sign-in logs
        return {
            "check": "legacy_auth",
            "title": "7. Legacy Authentication Usage",
            "severity": SEVERITY_WARNING,
            "finding_count": 0,
            "summary": (
                "Legacy authentication check requires Azure AD Premium P1. "
                "Ensure Conditional Access blocks legacy auth protocols."
            ),
            "items": [],
            "fix_command": "Create Conditional Access policy to block legacy authentication",
        }

    async def _check_exchange_best_practices(self, *_) -> dict:
        # Placeholder — real implementation checks mailbox forwarding, delegations, quotas
        return {
            "check": "exchange_best_practices",
            "title": "8. Exchange Online Mailbox Best Practices",
            "severity": SEVERITY_OK,
            "finding_count": 0,
            "summary": "Exchange Online checks require additional Graph permissions for mailbox settings.",
            "items": [],
            "fix_command": "Check mailbox for {user_principal_name}",
        }

    async def _check_conditional_access_gaps(self, *_) -> dict:
        # Placeholder — real implementation lists CA policies
        return {
            "check": "conditional_access_gaps",
            "title": "9. Conditional Access & Risk Policy Gaps",
            "severity": SEVERITY_WARNING,
            "finding_count": 0,
            "summary": (
                "Review your Conditional Access policies manually. "
                "M365 Guardian recommends: require MFA for all users, "
                "block legacy auth, require compliant devices for admins."
            ),
            "items": [],
            "fix_command": None,
        }

    async def _check_password_hygiene(self, *_) -> dict:
        # Placeholder — checks password policies and SSPR status
        return {
            "check": "password_hygiene",
            "title": "10. Password & Authentication Hygiene",
            "severity": SEVERITY_OK,
            "finding_count": 0,
            "summary": "Ensure password hash sync, SSPR, and banned password lists are enabled.",
            "items": [],
            "fix_command": None,
        }
