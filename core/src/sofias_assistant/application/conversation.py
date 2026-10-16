"""Direct Desktop conversation application service.

This module is intentionally transport-free. It translates Core conversation
events into the small UI-facing records needed by the Desktop while preserving
the durable error category/message already owned by the Conversation runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sofias_assistant.conversation.events import (
    ConversationStreamEvent,
    ConversationTextDelta,
    ConversationToolCallProposed,
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
    ConversationUsageUpdated,
)
from sofias_assistant.conversation.runtime import SendTextCommand, TextConversationRuntime


class ConversationService:
    """Application-facing Conversation operations for the Desktop."""

    def __init__(self, runtime: TextConversationRuntime) -> None:
        self._runtime = runtime

    async def create_conversation_id(self):
        conversation = await self._runtime.create_conversation()
        return conversation.id

    async def stream_text(
        self, command: SendTextCommand
    ) -> AsyncIterator[dict[str, object]]:
        async for event in self._runtime.stream_text(command):
            yield _to_ui_record(event)


def _to_ui_record(event: ConversationStreamEvent) -> dict[str, object]:
    if isinstance(event, ConversationTurnStarted):
        return {
            "type": "turn_started",
            "conversation_id": event.conversation.id,
            "turn_id": event.turn.id,
        }
    if isinstance(event, ConversationTextDelta):
        return {
            "type": "text_delta",
            "conversation_id": event.conversation_id,
            "turn_id": event.turn_id,
            "text": event.text,
        }
    if isinstance(event, ConversationUsageUpdated):
        return {
            "type": "usage_updated",
            "conversation_id": event.conversation_id,
            "turn_id": event.turn_id,
            "input_tokens": event.usage.input_tokens,
            "output_tokens": event.usage.output_tokens,
            "cached_tokens": event.usage.cached_tokens,
        }
    if isinstance(event, ConversationToolCallProposed):
        return {
            "type": "tool_call_proposed",
            "conversation_id": event.conversation_id,
            "turn_id": event.turn_id,
            "tool_name": event.proposal.name,
        }
    if isinstance(event, ConversationTurnCompleted):
        return {
            "type": "turn_completed",
            "conversation_id": event.conversation.id,
            "turn_id": event.turn.id,
        }
    if isinstance(event, ConversationTurnFailed):
        return {
            "type": "turn_failed",
            "conversation_id": event.conversation.id,
            "turn_id": event.turn.id,
            "error_code": event.turn.error_category or "conversation_failed",
            "error_message": event.turn.error_message or "Conversation turn failed",
        }
    if isinstance(event, ConversationTurnInterrupted):
        return {
            "type": "turn_interrupted",
            "conversation_id": event.conversation.id,
            "turn_id": event.turn.id,
            "error_code": event.turn.error_category or "conversation_interrupted",
            "error_message": event.turn.error_message or "Conversation turn interrupted",
        }
    raise AssertionError(f"Unhandled conversation event: {type(event).__name__}")
