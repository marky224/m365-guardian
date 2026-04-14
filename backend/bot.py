"""
M365 Guardian — Microsoft Teams Bot Handler.
Handles incoming messages from Teams via Azure Bot Service.
"""

import logging
import uuid
from typing import Any

from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import Activity, ActivityTypes

from backend.services.llm_service import LLMService
from backend.services.graph_service import GraphService
from backend.services.audit_service import AuditService
from backend.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class GuardianBot(ActivityHandler):
    """Bot handler for M365 Guardian in Microsoft Teams."""

    def __init__(self):
        self.llm = LLMService()
        self.graph = GraphService()
        self.audit = AuditService()
        # In-memory session store (use Cosmos DB in production)
        self._sessions: dict[str, dict] = {}

    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming messages."""
        user_message = turn_context.activity.text or ""
        user_id = turn_context.activity.from_property.id or "unknown"
        user_name = turn_context.activity.from_property.name or "Unknown"
        user_email = turn_context.activity.from_property.aad_object_id or user_id
        conversation_id = turn_context.activity.conversation.id

        # Get or create session
        session = self._get_or_create_session(conversation_id, user_id, user_name, user_email)

        # Create tool executor for this session
        executor = ToolExecutor(
            graph=self.graph,
            audit=self.audit,
            session_id=session["session_id"],
            technician_id=user_id,
            technician_email=user_email,
        )

        # Show typing indicator
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        try:
            # Run the LLM conversation loop
            response_text, updated_history = await self.llm.chat_with_tool_loop(
                user_message=user_message,
                conversation_history=session["history"],
                session_context={
                    "technician_name": user_name,
                    "technician_email": user_email,
                    "session_id": session["session_id"],
                },
                tool_executor=executor.execute,
            )

            # Update session history
            session["history"] = updated_history

            # Send response (split if > 4000 chars for Teams)
            if len(response_text) > 4000:
                chunks = [response_text[i:i+3900] for i in range(0, len(response_text), 3900)]
                for chunk in chunks:
                    await turn_context.send_activity(chunk)
            else:
                await turn_context.send_activity(response_text)

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            await turn_context.send_activity(
                f"⚠️ I encountered an error processing your request: {str(e)}\n\n"
                "Please try again. If the issue persists, check the Azure Function logs."
            )

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        """Welcome new users when the bot is added."""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                welcome = (
                    "👋 **Welcome to M365 Guardian!**\n\n"
                    "I'm your Microsoft 365 user & security assistant. "
                    "I can help you with:\n\n"
                    "• **User management** — Create, update, delete users\n"
                    "• **Password & MFA** — Reset passwords, enforce MFA\n"
                    "• **Mailbox management** — Shared mailboxes, permissions\n"
                    "• **Security insights** — Weekly reports on your tenant health\n\n"
                    "All actions require your explicit approval and are fully logged.\n\n"
                    "Try: *\"Create a new user named Jane Doe in the Engineering department\"*"
                )
                await turn_context.send_activity(welcome)

    def _get_or_create_session(
        self, conversation_id: str, user_id: str, user_name: str, user_email: str
    ) -> dict:
        """Get existing session or create a new one."""
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = {
                "session_id": str(uuid.uuid4()),
                "user_id": user_id,
                "user_name": user_name,
                "user_email": user_email,
                "history": [],
            }
        return self._sessions[conversation_id]
