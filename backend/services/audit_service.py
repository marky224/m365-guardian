"""
M365 Guardian — Audit Logging Service.
Records every action for compliance and traceability.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from azure.cosmos import CosmosClient, PartitionKey
from backend.config import config

logger = logging.getLogger(__name__)


class AuditService:
    """Handles audit trail storage in Azure Cosmos DB."""

    def __init__(self):
        self._client = None
        self._container = None

    async def initialize(self):
        """Initialize Cosmos DB connection and ensure container exists."""
        if not config.cosmos.endpoint or not config.cosmos.key:
            logger.warning("Cosmos DB not configured — audit logs will be local-only.")
            return

        try:
            self._client = CosmosClient(config.cosmos.endpoint, config.cosmos.key)
            db = self._client.create_database_if_not_exists(config.cosmos.database)
            self._container = db.create_container_if_not_exists(
                id=config.cosmos.audit_container,
                partition_key=PartitionKey(path="/session_id"),
                default_ttl=365 * 24 * 60 * 60,  # 1 year retention
            )
            logger.info("Audit service initialized with Cosmos DB.")
        except Exception as e:
            logger.error(f"Cosmos DB initialization failed: {e}")

    async def log_action(
        self,
        session_id: str,
        technician_id: str,
        technician_email: str,
        action: str,
        tool_name: str,
        tool_args: dict,
        result: dict | None = None,
        status: str = "success",
        error: str | None = None,
    ) -> str:
        """
        Log an action to the audit trail.

        Returns the audit entry ID.
        """
        audit_id = str(uuid.uuid4())
        entry = {
            "id": audit_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "technician_id": technician_id,
            "technician_email": technician_email,
            "action": action,
            "tool_name": tool_name,
            "tool_arguments": self._sanitize(tool_args),
            "result_summary": self._summarize_result(result) if result else None,
            "status": status,
            "error": error,
        }

        # Write to Cosmos DB if available
        if self._container:
            try:
                self._container.create_item(entry)
            except Exception as e:
                logger.error(f"Failed to write audit log to Cosmos DB: {e}")

        # Always log locally
        logger.info(
            f"AUDIT | {entry['timestamp']} | {technician_email} | "
            f"{tool_name} | {status} | {audit_id}"
        )

        return audit_id

    async def query_logs(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        action_type: str | None = None,
        performed_by: str | None = None,
        top: int = 25,
    ) -> list[dict]:
        """Query audit logs with optional filters."""
        if not self._container:
            return []

        conditions = ["1=1"]
        params = []

        if start_date:
            conditions.append("c.timestamp >= @start")
            params.append({"name": "@start", "value": start_date})
        if end_date:
            conditions.append("c.timestamp <= @end")
            params.append({"name": "@end", "value": end_date})
        if action_type:
            conditions.append("c.tool_name = @action")
            params.append({"name": "@action", "value": action_type})
        if performed_by:
            conditions.append("c.technician_email = @by")
            params.append({"name": "@by", "value": performed_by})

        query = (
            f"SELECT TOP {top} * FROM c WHERE {' AND '.join(conditions)} "
            f"ORDER BY c.timestamp DESC"
        )

        try:
            items = list(self._container.query_items(query, parameters=params, enable_cross_partition_query=True))
            return items
        except Exception as e:
            logger.error(f"Audit log query failed: {e}")
            return []

    @staticmethod
    def _sanitize(args: dict) -> dict:
        """Remove sensitive fields from tool arguments before logging."""
        sanitized = dict(args)
        sensitive_keys = {"password", "new_password", "secret", "token", "api_key"}
        for key in sensitive_keys:
            if key in sanitized:
                sanitized[key] = "***REDACTED***"
        return sanitized

    @staticmethod
    def _summarize_result(result: dict) -> dict:
        """Create a brief summary of tool results for the audit log."""
        if not result:
            return {}
        summary = {}
        for key in ["id", "user_id", "success", "deleted", "assigned", "removed", "password_reset"]:
            if key in result:
                summary[key] = result[key]
        return summary
