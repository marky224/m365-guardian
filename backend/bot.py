"""
M365 Guardian — Microsoft Teams Bot Handler.
Handles incoming messages from Teams via Azure Bot Service.
"""

import logging
import uuid

from botbuilder.core import ActivityHandler, CardFactory, MessageFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes, Attachment

from backend.config import config
from backend.confirmations import resolve_pending_confirmation
from backend.services.audit_service import AuditService
from backend.services.graph_service import GraphService
from backend.services.llm_service import LLMService
from backend.services.session_service import SessionService
from backend.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


class GuardianBot(ActivityHandler):
    """Bot handler for M365 Guardian in Microsoft Teams."""

    def __init__(
        self,
        llm: LLMService,
        graph: GraphService,
        audit: AuditService,
        sessions: SessionService,
    ):
        # Services are constructed and initialized once at app startup and
        # injected here, so a single GuardianBot reuses shared clients.
        self.llm = llm
        self.graph = graph
        self.audit = audit
        self.sessions = sessions

    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming messages."""
        # An Adaptive Card Approve/Cancel click arrives as a submit action in activity.value
        # (with no text). Handle it in code — the model is never consulted for the approval.
        submit = turn_context.activity.value
        if isinstance(submit, dict) and submit.get("action") == "guardian_confirm":
            await self._handle_confirm_submit(turn_context, submit)
            return

        user_message = turn_context.activity.text or ""
        user_id = turn_context.activity.from_property.id or "unknown"
        user_name = turn_context.activity.from_property.name or "Unknown"
        user_email = turn_context.activity.from_property.aad_object_id or user_id
        conversation_id = turn_context.activity.conversation.id

        # Durable session keyed by the Bot Framework-trusted conversation id, which is
        # also the owner partition — the conversation's history is shared by its members.
        session = await self.sessions.get_or_create(
            conversation_id,
            owner_id=conversation_id,
            user_name=user_name,
            user_email=user_email,
        )

        # Create tool executor for this session
        executor = ToolExecutor(
            graph=self.graph,
            audit=self.audit,
            session_id=session["session_id"],
            technician_id=user_id,
            technician_email=user_email,
            mfa_required_group_id=config.security.mfa_required_group_id,
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

            # Persist updated history durably (refreshes the session TTL)
            await self.sessions.save(
                conversation_id,
                owner_id=conversation_id,
                history=updated_history,
                user_name=user_name,
                user_email=user_email,
            )

            # Send response (split if > 4000 chars for Teams)
            if response_text and len(response_text) > 4000:
                chunks = [response_text[i : i + 3900] for i in range(0, len(response_text), 3900)]
                for chunk in chunks:
                    await turn_context.send_activity(chunk)
            elif response_text:
                await turn_context.send_activity(response_text)

            # If a write was proposed, persist the approval and render an Approve/Cancel card.
            # The token rides in the card's Action.Submit and is validated in code on click.
            if executor.pending_confirmation:
                await self.sessions.set_pending(
                    conversation_id, owner_id=conversation_id, pending=executor.pending_confirmation
                )
                card = self._confirmation_card(
                    executor.pending_confirmation["summary"], executor.pending_confirmation["token"]
                )
                await turn_context.send_activity(MessageFactory.attachment(card))

        except Exception as e:
            error_id = uuid.uuid4().hex[:8]
            logger.error(f"Error handling message [error_id={error_id}]: {e}")
            await turn_context.send_activity(
                "⚠️ I encountered an error processing your request "
                f"(reference `{error_id}`).\n\nPlease try again. If the issue persists, "
                "share this reference with your administrator."
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
                    'Try: *"Create a new user named Jane Doe in the Engineering department"*'
                )
                await turn_context.send_activity(welcome)

    async def _handle_confirm_submit(self, turn_context: TurnContext, submit: dict) -> None:
        """Resolve an Adaptive Card Approve/Cancel click (Layer 2, D-015)."""
        conversation_id = turn_context.activity.conversation.id
        user_id = turn_context.activity.from_property.id or "unknown"
        user_email = turn_context.activity.from_property.aad_object_id or user_id

        def build_executor(fingerprint: str) -> ToolExecutor:
            return ToolExecutor(
                graph=self.graph,
                audit=self.audit,
                session_id=conversation_id,
                technician_id=user_id,
                technician_email=user_email,
                mfa_required_group_id=config.security.mfa_required_group_id,
                confirmed_fingerprint=fingerprint,
            )

        message = await resolve_pending_confirmation(
            sessions=self.sessions,
            key=conversation_id,
            owner_id=conversation_id,
            token=submit.get("token", ""),
            decision=submit.get("decision", "approve"),
            build_executor=build_executor,
        )
        await turn_context.send_activity(message)

    @staticmethod
    def _confirmation_card(summary: str, token: str) -> Attachment:
        """Adaptive Card with Approve/Cancel; each carries the approval token in its submit data."""
        return CardFactory.adaptive_card(
            {
                "type": "AdaptiveCard",
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": "⚠️ Approval required", "weight": "Bolder", "wrap": True},
                    {"type": "TextBlock", "text": summary, "wrap": True},
                ],
                "actions": [
                    {
                        "type": "Action.Submit",
                        "title": "✅ Approve",
                        "data": {"action": "guardian_confirm", "decision": "approve", "token": token},
                    },
                    {
                        "type": "Action.Submit",
                        "title": "✖ Cancel",
                        "data": {"action": "guardian_confirm", "decision": "cancel", "token": token},
                    },
                ],
            }
        )
