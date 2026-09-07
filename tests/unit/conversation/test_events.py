"""Unit tests for immutable Core-owned streaming event contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sofias_assistant.ai.contracts import ModelIdentity, UsageMetadata
from sofias_assistant.conversation.events import (
    ConversationTextDelta,
    ConversationTurnCompleted,
    ConversationTurnStarted,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)


def processing_snapshots() -> tuple[Conversation, Turn]:
    timestamp = datetime(2026, 9, 7, tzinfo=UTC)
    conversation = Conversation(id=uuid4(), created_at=timestamp, updated_at=timestamp)
    turn = Turn(
        id=uuid4(),
        conversation_id=conversation.id,
        sequence=1,
        status=TurnStatus.PROCESSING,
        input_modality=TurnInputModality.TEXT,
        cloud_context_eligible=True,
        user_text="request",
        assistant_text=None,
        ai_request_id=None,
        provider_id=None,
        model_id=None,
        provider_request_id=None,
        provider_session_id=None,
        error_category=None,
        error_message=None,
        created_at=timestamp,
        updated_at=timestamp,
        finished_at=None,
    )
    return conversation, turn


def test_started_and_delta_events_validate_core_identity_and_are_immutable() -> None:
    conversation, turn = processing_snapshots()
    started = ConversationTurnStarted(conversation, turn)
    delta = ConversationTextDelta(
        conversation.id,
        turn.id,
        uuid4(),
        ModelIdentity("fake", "stream"),
        "",
    )
    assert started.turn is turn
    assert delta.text == ""
    with pytest.raises(ValueError, match="processing"):
        ConversationTurnStarted(
            conversation,
            replace(
                turn,
                status=TurnStatus.FAILED,
                finished_at=turn.updated_at,
                error_message="safe",
            ),
        )
    with pytest.raises(AttributeError):
        delta.text = "changed"  # type: ignore[misc]


def test_completed_event_requires_a_matching_completed_turn() -> None:
    conversation, turn = processing_snapshots()
    completed = turn.complete(
        assistant_text="answer",
        updated_at=turn.updated_at,
        finished_at=turn.updated_at,
    )
    event = ConversationTurnCompleted(
        conversation, completed, UsageMetadata(input_tokens=1)
    )
    assert event.turn.status is TurnStatus.COMPLETED
    with pytest.raises(ValueError, match="COMPLETED"):
        ConversationTurnCompleted(conversation, turn)
