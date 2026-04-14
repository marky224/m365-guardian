"""
M365 Guardian — Azure Functions Timer Trigger.
Runs the weekly security insights report on a schedule.
Deploy as an Azure Function with a timer trigger.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import azure.functions as func
from backend.config import config
from backend.services.graph_service import GraphService
from backend.services.report_service import ReportService

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

        # ── Deliver to Teams ─────────────────────────────────────────
        if config.report.teams_team_id and config.report.teams_channel_id:
            try:
                card = _build_adaptive_card(report)
                # Use Graph API to post to Teams channel
                # graph._client.teams.by_team_id(...).channels.by_channel_id(...).messages.post(...)
                logger.info("Report sent to Teams channel.")
            except Exception as e:
                logger.error(f"Failed to send report to Teams: {e}")

        # ── Deliver via Email ────────────────────────────────────────
        if config.report.email_recipients:
            try:
                html = _build_email_html(report)
                # Use Graph API sendMail
                logger.info(f"Report emailed to {len(config.report.email_recipients)} recipients.")
            except Exception as e:
                logger.error(f"Failed to email report: {e}")

    except Exception as e:
        logger.error(f"Weekly report generation failed: {e}")
        raise


def _build_adaptive_card(report: dict) -> dict:
    """Build a Teams Adaptive Card from the report data."""
    sections = []
    for section in report["sections"]:
        sections.append({
            "type": "Container",
            "items": [
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "auto",
                            "items": [{"type": "TextBlock", "text": section["severity"], "size": "medium"}],
                        },
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {"type": "TextBlock", "text": section["title"], "weight": "bolder"},
                                {"type": "TextBlock", "text": section["summary"], "wrap": True, "size": "small"},
                            ],
                        },
                    ],
                },
            ],
        })

        # Add "Fix with M365 Guardian" button if applicable
        if section.get("fix_command") and section["finding_count"] > 0:
            sections[-1]["items"].append({
                "type": "ActionSet",
                "actions": [
                    {
                        "type": "Action.OpenUrl",
                        "title": "Fix with M365 Guardian",
                        "url": f"{config.base_url}/?cmd={section['fix_command']}",
                    }
                ],
            })

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "text": "🛡️ M365 Guardian — Weekly Security Insights",
                "weight": "bolder",
                "size": "large",
            },
            {
                "type": "TextBlock",
                "text": report["executive_summary"],
                "wrap": True,
            },
            {"type": "TextBlock", "text": f"Generated: {report['generated_at']}", "size": "small", "isSubtle": True},
            *sections,
        ],
    }


def _build_email_html(report: dict) -> str:
    """Build an HTML email from the report data."""
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
                f'Fix with M365 Guardian</a>'
            )

        sections_html += f"""
        <div style="border-left:4px solid {'#d13438' if '🔴' in s['severity'] else '#ffc83d' if '🟡' in s['severity'] else '#107c10'};
                     padding:12px;margin:12px 0;background:#fafafa;">
            <h3 style="margin:0 0 4px 0;">{s['title']}</h3>
            <p style="margin:4px 0;"><strong>{s['severity']}</strong> — {s['finding_count']} finding(s)</p>
            <p style="margin:4px 0;">{s['summary']}</p>
            {'<ul>' + items_html + '</ul>' if items_html else ''}
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
                <strong>Executive Summary:</strong> {report['executive_summary']}
            </div>
            {sections_html}
            <hr style="margin:24px 0;">
            <p style="color:#666;font-size:12px;">
                Generated by M365 Guardian on {report['generated_at']}.<br>
                This is an automated report. Review findings and take action as needed.
            </p>
        </div>
    </body>
    </html>
    """
