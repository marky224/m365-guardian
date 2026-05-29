"""
M365 Guardian — Session Service.

Durable conversation state in Azure Cosmos DB, replacing the bot's in-memory dict
and the web client's cookie/round-tripped history. Each session is one document.

Partition key is ``/owner_id``, so owner-scoping is *structural*: a read is
``read_item(id, partition_key=owner_id)``, which can only ever return a document in
the caller's own partition. An authenticated user therefore cannot read or continue
another user's session even by guessing its id — it lives in a different partition.

When Cosmos is not configured (local dev), sessions are kept in an in-memory dict
with the same API, so the app still runs — they are simply lost on restart.
"""

import logging
from datetime import UTC, datetime

from azure.cosmos import ContainerProxy, CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from backend.config import config

logger = logging.getLogger(__name__)

# Sessions expire after 30 idle days; every write refreshes the TTL countdown.
_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SessionService:
    """Stores conversation history per (owner_id, session key) in Cosmos DB."""

    def __init__(self) -> None:
        self._client: CosmosClient | None = None
        self._container: ContainerProxy | None = None
        # Local fallback when Cosmos is unconfigured: (owner_id, key) -> document.
        self._memory: dict[tuple[str, str], dict] = {}

    async def initialize(self) -> None:
        """Connect to Cosmos and ensure the sessions container exists. No-op locally."""
        if not config.cosmos.endpoint or not config.cosmos.key:
            logger.warning("Cosmos DB not configured — sessions are in-memory only (lost on restart).")
            return
        try:
            self._client = CosmosClient(config.cosmos.endpoint, config.cosmos.key)
            db = self._client.create_database_if_not_exists(config.cosmos.database)
            self._container = db.create_container_if_not_exists(
                id=config.cosmos.sessions_container,
                partition_key=PartitionKey(path="/owner_id"),
                default_ttl=_SESSION_TTL_SECONDS,
            )
            logger.info("Session service initialized with Cosmos DB.")
        except Exception as e:
            logger.error(f"Cosmos DB session init failed: {e}")

    async def get(self, key: str, owner_id: str) -> dict | None:
        """Return the session document for (key, owner_id), or None if absent.

        Owner-scoped by partition: a key owned by a different user reads as not-found.
        """
        if self._container is None:
            return self._memory.get((owner_id, key))
        try:
            return dict(self._container.read_item(item=key, partition_key=owner_id))
        except CosmosResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Session read failed: {e}")
            return None

    async def get_or_create(self, key: str, owner_id: str, *, user_name: str = "", user_email: str = "") -> dict:
        """Return the existing session for (key, owner_id) or create an empty one."""
        existing = await self.get(key, owner_id)
        if existing is not None:
            return existing
        now = _now()
        doc = {
            "id": key,
            "owner_id": owner_id,
            "session_id": key,  # correlation id for audit; equals the session key
            "user_name": user_name,
            "user_email": user_email,
            "history": [],
            "created_at": now,
            "updated_at": now,
        }
        self._write(doc)
        return doc

    async def save(
        self,
        key: str,
        owner_id: str,
        history: list[dict],
        *,
        user_name: str | None = None,
        user_email: str | None = None,
    ) -> None:
        """Persist updated history for a session, refreshing its TTL."""
        doc = await self.get(key, owner_id)
        if doc is None:
            now = _now()
            doc = {
                "id": key,
                "owner_id": owner_id,
                "session_id": key,
                "user_name": user_name or "",
                "user_email": user_email or "",
                "history": [],
                "created_at": now,
                "updated_at": now,
            }
        doc["history"] = history
        doc["updated_at"] = _now()
        if user_name is not None:
            doc["user_name"] = user_name
        if user_email is not None:
            doc["user_email"] = user_email
        self._write(doc)

    def _write(self, doc: dict) -> None:
        if self._container is None:
            self._memory[(doc["owner_id"], doc["id"])] = doc
            return
        try:
            self._container.upsert_item(doc)
        except Exception as e:
            logger.error(f"Session write failed: {e}")

    @staticmethod
    def renderable_messages(history: list[dict]) -> list[dict]:
        """Project stored LLM history to a display transcript: user + assistant text only.

        Skips the tool calls/results and any assistant turn that carried only tool calls,
        so the web UI can re-render a conversation without leaking internal machinery.
        """
        out: list[dict] = []
        for m in history:
            role = m.get("role")
            content = m.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if role == "user":
                out.append({"role": "user", "text": content})
            elif role == "assistant":
                out.append({"role": "bot", "text": content})
        return out
