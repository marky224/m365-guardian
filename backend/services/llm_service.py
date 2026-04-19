"""
M365 Guardian — LLM Orchestration Service.
Pluggable LLM layer using LiteLLM for provider-agnostic tool calling.
"""

import json
import logging
from pathlib import Path
from typing import Any

import litellm
from backend.config import config

logger = logging.getLogger(__name__)

# Load system prompt
_SYSTEM_PROMPT_PATH = Path(__file__).parent.parent.parent / "docs" / "01_SYSTEM_PROMPT.md"
_TOOL_SCHEMAS_PATH = Path(__file__).parent.parent.parent / "docs" / "02_TOOL_SCHEMAS.json"


def _load_system_prompt() -> str:
    """Load and clean the system prompt from markdown file."""
    raw = _SYSTEM_PROMPT_PATH.read_text()
    # Strip the markdown code fences, keep the content
    lines = raw.strip().split("\n")
    cleaned = []
    in_block = False
    for line in lines:
        if line.strip().startswith("```") and not in_block:
            in_block = True
            continue
        elif line.strip() == "```" and in_block:
            in_block = False
            continue
        if in_block:
            cleaned.append(line)
    return "\n".join(cleaned) if cleaned else raw


def _load_tool_schemas() -> list[dict]:
    """Load tool definitions and convert to LiteLLM/OpenAI function format."""
    raw = json.loads(_TOOL_SCHEMAS_PATH.read_text())
    tools = []
    for tool in raw["tools"]:
        tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        })
    return tools


class LLMService:
    """Manages LLM interactions with tool calling support."""

    def __init__(self):
        self.system_prompt = _load_system_prompt()
        self.tools = _load_tool_schemas()
        self._configure_litellm()

    def _configure_litellm(self):
        """Set LiteLLM environment based on config."""
        import os
        litellm.set_verbose = False
        if config.llm.provider == "anthropic":
            litellm.anthropic_key = config.llm.api_key
        elif config.llm.provider == "azure_openai":
            litellm.azure_key = os.getenv("AZURE_OPENAI_API_KEY", "")
        elif config.llm.provider == "xai":
            os.environ["XAI_API_KEY"] = config.llm.api_key
        elif config.llm.provider == "openai":
            os.environ["OPENAI_API_KEY"] = config.llm.api_key

    async def chat(
        self,
        messages: list[dict],
        session_context: dict | None = None,
    ) -> dict:
        """
        Send a conversation to the LLM with tools enabled.

        Args:
            messages: Conversation history in OpenAI format.
            session_context: Optional session metadata (user identity, etc.)

        Returns:
            LLM response dict with 'content' and optional 'tool_calls'.
        """
        # Prepend system prompt
        full_messages = [{"role": "system", "content": self.system_prompt}]

        # Inject session context if available
        if session_context:
            ctx = (
                f"\n\n[Session Context]\n"
                f"Technician: {session_context.get('technician_name', 'Unknown')}\n"
                f"Current Date: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                f"Technician Email: {session_context.get('technician_email', 'Unknown')}\n"
                f"Tenant: {session_context.get('tenant_id', config.azure_ad.tenant_id)}\n"
                f"Session ID: {session_context.get('session_id', 'N/A')}\n"
            )
            full_messages[0]["content"] += ctx

        full_messages.extend(messages)

        try:
            response = await litellm.acompletion(
                model=config.llm.litellm_model,
                messages=full_messages,
                tools=self.tools,
                tool_choice="auto",
                max_tokens=config.llm.max_tokens,
                temperature=config.llm.temperature,
            )

            choice = response.choices[0]
            result = {
                "content": choice.message.content or "",
                "tool_calls": [],
                "finish_reason": choice.finish_reason,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }

            # Extract tool calls if any
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    result["tool_calls"].append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    })

            return result

        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            raise

    async def chat_with_tool_loop(
        self,
        user_message: str,
        conversation_history: list[dict],
        session_context: dict | None = None,
        tool_executor=None,
        max_iterations: int = 5,
    ) -> tuple[str, list[dict]]:
        """
        Full conversation loop: send message → handle tool calls → return final response.

        Args:
            user_message: The user's latest message.
            conversation_history: Existing message history.
            session_context: Session metadata.
            tool_executor: Callable that executes tool calls and returns results.
            max_iterations: Max tool-calling round-trips before forcing a text response.

        Returns:
            Tuple of (final_text_response, updated_conversation_history).
        """
        messages = list(conversation_history)
        messages.append({"role": "user", "content": user_message})

        for iteration in range(max_iterations):
            response = await self.chat(messages, session_context)

            # If no tool calls, we have a final text response
            if not response["tool_calls"]:
                messages.append({"role": "assistant", "content": response["content"]})
                return response["content"], messages

            # Process tool calls
            assistant_msg = {
                "role": "assistant",
                "content": response["content"] or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in response["tool_calls"]
                ],
            }
            messages.append(assistant_msg)

            # Execute each tool call
            if tool_executor:
                for tc in response["tool_calls"]:
                    try:
                        result = await tool_executor(tc["name"], tc["arguments"])
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, default=str),
                        })
                    except Exception as e:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({
                                "error": str(e),
                                "error_type": type(e).__name__,
                            }, default=str),
                        })

        # Max iterations reached
        final_msg = (
            "I've reached the maximum number of tool-calling steps. "
            "Please try breaking your request into smaller steps."
        )
        messages.append({"role": "assistant", "content": final_msg})
        return final_msg, messages
