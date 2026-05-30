"""
M365 Guardian — Azure Functions Timer Trigger.
Runs the weekly security insights report on a schedule.
Deploy as an Azure Function with a timer trigger.
"""

import logging

import azure.functions as func

from backend.config import config
from backend.services.graph_service import GraphService
from backend.services.report_service import ReportService
from backend.services.secret_service import SecretProvider

logger = logging.getLogger(__name__)

app = func.FunctionApp()


@app.timer_trigger(
    schedule=config.report.schedule_cron,
    arg_name="timer",
    run_on_startup=False,
)
async def weekly_report_trigger(timer: func.TimerRequest) -> None:
    """
    Timer-triggered Azure Function that generates and delivers the weekly report.
    Default schedule: Every Monday at 8:00 AM UTC.
    """
    if timer.past_due:
        logger.warning("Weekly report trigger is past due — running now.")

    logger.info("Starting weekly security insights report generation...")

    # Resolve secrets (Key Vault via this Function's managed identity, or env), then validate.
    secrets = SecretProvider()
    secrets.hydrate(config)
    secrets.close()
    config.ensure_valid()  # fail fast on missing/placeholder configuration

    try:
        graph = GraphService()
        report_svc = ReportService(graph)

        # Generate the full report
        report = await report_svc.generate()

        logger.info(
            f"Report generated: {report['overall_severity']} | "
            f"{report['total_findings']} findings | "
            f"{report['critical_count']} critical"
        )

        html = _build_email_html(report)
        subject = f"M365 Guardian — Weekly Security Insights ({report['overall_severity']})"

        # ── Deliver to Teams ─────────────────────────────────────────
        if config.report.teams_team_id and config.report.teams_channel_id:
            try:
                await graph.send_channel_message(
                    config.report.teams_team_id,
                    config.report.teams_channel_id,
                    html,
                )
                logger.info("Report sent to Teams channel.")
            except Exception as e:
                logger.error(f"Failed to send report to Teams: {e}")
        else:
            logger.info("Teams delivery skipped — REPORT_TEAMS_TEAM_ID/CHANNEL_ID not set.")

        # ── Deliver via Email ────────────────────────────────────────
        if config.report.email_recipients and config.report.sender_upn:
            try:
                await graph.send_mail(
                    config.report.sender_upn,
                    config.report.email_recipients,
                    subject,
                    html,
                )
                logger.info(f"Report emailed to {len(config.report.email_recipients)} recipients.")
            except Exception as e:
                logger.error(f"Failed to email report: {e}")
        else:
            logger.info("Email delivery skipped — REPORT_EMAIL_RECIPIENTS/SENDER_UPN not set.")

    except Exception as e:
        logger.error(f"Weekly report generation failed: {e}")
        raise


def _build_email_html(report: dict) -> str:
    """Build an HTML email (also used as the Teams channel message body) from the report data."""
    sections_html = ""
    for s in report["sections"]:
        items_html = ""
        for item in s.get("items", [])[:5]:
            display = item.get("displayName") or item.get("userPrincipalName") or item.get("skuPartNumber") or str(item)
            items_html += f"<li>{display}</li>"

        fix_button = ""
        if s.get("fix_command") and s["finding_count"] > 0:
            fix_button = (
                f'<a href="{config.base_url}/?cmd={s["fix_command"]}" '
                f'style="background:#0078d4;color:white;padding:6px 16px;'
                f'text-decoration:none;border-radius:4px;font-size:13px;">'
                f"Fix with M365 Guardian</a>"
            )

        border_color = "#d13438" if "🔴" in s["severity"] else "#ffc83d" if "🟡" in s["severity"] else "#107c10"
        sections_html += f"""
        <div style="border-left:4px solid {border_color};
                     padding:12px;margin:12px 0;background:#fafafa;">
            <h3 style="margin:0 0 4px 0;">{s["title"]}</h3>
            <p style="margin:4px 0;"><strong>{s["severity"]}</strong> — {s["finding_count"]} finding(s)</p>
            <p style="margin:4px 0;">{s["summary"]}</p>
            {"<ul>" + items_html + "</ul>" if items_html else ""}
            {fix_button}
        </div>
        """

    return f"""
    <html>
    <body style="font-family:Segoe UI,sans-serif;max-width:700px;margin:0 auto;">
        <div style="background:#0078d4;color:white;padding:20px;text-align:center;">
            <h1 style="margin:0;">🛡️ M365 Guardian</h1>
            <p style="margin:4px 0;">Weekly Security & Best-Practice Insights</p>
        </div>
        <div style="padding:20px;">
            <div style="background:#f0f0f0;padding:16px;border-radius:8px;margin-bottom:20px;">
                <strong>Executive Summary:</strong> {report["executive_summary"]}
            </div>
            {sections_html}
            <hr style="margin:24px 0;">
            <p style="color:#666;font-size:12px;">
                Generated by M365 Guardian on {report["generated_at"]}.<br>
                This is an automated report. Review findings and take action as needed.
            </p>
        </div>
    </body>
    </html>
    """
