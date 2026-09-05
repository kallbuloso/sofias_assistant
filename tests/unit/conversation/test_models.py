"""Unit tests for immutable Core-owned conversation snapshots."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)

CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000001")
TURN_ID = UUID("00000000-0000-0000-0000-000000000002")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000003")
CREATED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def processing_turn(**changes: object) -> Turn:
    values: dict[str, object] = {
        "id": TURN_ID,
        "conversation_id": CONVERSATION_ID,
        "sequence": 1,
        "status": TurnStatus.PROCESSING,
        "input_modality": TurnInputModality.TEXT,
        "user_text": "  preserve this text  ",
        "assistant_text": None,
        "ai_request_id": None,
        "provider_id": None,
        "model_id": None,
        "provider_request_id": None,
        "provider_session_id": None,
        "error_category": None,
        "error_message": None,
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT,
        "finished_at": None,
    }
    values.update(changes)
    return Turn(**values)  # type: ignore[arg-type]


def test_conversation_normalizes_aware_timestamps_and_rejects_invalid_order() -> None:
    offset = timezone(timedelta(hours=-3))
    conversation = Conversation(
        id=CONVERSATION_ID,
        created_at=datetime(2026, 9, 4, 9, 0, tzinfo=offset),
        updated_at=datetime(2026, 9, 4, 9, 1, tzinfo=offset),
    )

    assert conversation.created_at == CREATED_AT
    assert conversation.updated_at == CREATED_AT + timedelta(minutes=1)
    assert conversation.created_at.tzinfo is UTC
    with pytest.raises(ValueError, match="timezone-aware"):
        Conversation(CONVERSATION_ID, datetime(2026, 9, 4, 12, 0), CREATED_AT)
    with pytest.raises(ValueError, match="updated_at"):
        Conversation(CONVERSATION_ID, CREATED_AT, CREATED_AT - timedelta(seconds=1))


def test_turn_status_and_input_modality_are_exactly_the_text_baseline() -> None:
    assert set(TurnStatus) == {
        TurnStatus.PROCESSING,
        TurnStatus.COMPLETED,
        TurnStatus.INTERRUPTED,
        TurnStatus.FAILED,
    }
    assert set(TurnInputModality) == {TurnInputModality.TEXT}


@pytest.mark.parametrize("sequence", [0, -1, True])
def test_turn_rejects_invalid_sequence(sequence: int) -> None:
    with pytest.raises(ValueError, match="sequence"):
        processing_turn(sequence=sequence)


@pytest.mark.parametrize("user_text", ["", " \t\n "])
def test_turn_rejects_empty_or_whitespace_user_text(user_text: str) -> None:
    with pytest.raises(ValueError, match="user_text"):
        processing_turn(user_text=user_text)


def test_processing_turn_preserves_text_and_requires_no_output_or_error() -> None:
    turn = processing_turn()
    assert turn.user_text == "  preserve this text  "
    assert turn.assistant_text is None
    with pytest.raises(ValueError, match="processing turn"):
        processing_turn(assistant_text="partial")
    with pytest.raises(ValueError, match="processing turn"):
        processing_turn(error_message="failure")
    with pytest.raises(ValueError, match="processing turn"):
        processing_turn(finished_at=CREATED_AT)


def test_completed_interrupted_and_failed_turn_invariants() -> None:
    finished_at = CREATED_AT + timedelta(seconds=1)
    completed = processing_turn().complete(
        assistant_text="",
        updated_at=finished_at,
        finished_at=finished_at,
    )
    assert completed.status is TurnStatus.COMPLETED
    assert completed.assistant_text == ""

    interrupted = processing_turn().interrupt(
        assistant_text="partial",
        updated_at=finished_at,
        finished_at=finished_at,
    )
    assert interrupted.status is TurnStatus.INTERRUPTED
    assert interrupted.assistant_text == "partial"

    failed = processing_turn().fail(
        assistant_text=None,
        error_category=None,
        error_message="safe provider failure",
        updated_at=finished_at,
        finished_at=finished_at,
    )
    assert failed.status is TurnStatus.FAILED

    with pytest.raises(ValueError, match="completed turn requires"):
        processing_turn(
            status=TurnStatus.COMPLETED,
            finished_at=finished_at,
        )
    with pytest.raises(ValueError, match="error_message"):
        processing_turn(status=TurnStatus.FAILED, finished_at=finished_at)


def test_turn_rejects_invalid_timestamp_ordering() -> None:
    finished_at = CREATED_AT + timedelta(seconds=1)
    with pytest.raises(ValueError, match="finished_at"):
        processing_turn(
            status=TurnStatus.INTERRUPTED,
            finished_at=CREATED_AT - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="updated_at"):
        processing_turn(
            status=TurnStatus.INTERRUPTED,
            updated_at=CREATED_AT,
            finished_at=finished_at,
        )


def test_turn_provider_correlation_requires_complete_non_blank_pairing() -> None:
    correlated = processing_turn(
        ai_request_id=REQUEST_ID,
        provider_id="provider",
        model_id="model",
        provider_request_id="request",
        provider_session_id="session",
    )
    assert correlated.ai_request_id == REQUEST_ID
    with pytest.raises(ValueError, match="provided together"):
        processing_turn(provider_id="provider")
    with pytest.raises(ValueError, match="provider_id"):
        processing_turn(provider_id=" ", model_id="model")
    with pytest.raises(ValueError, match="require provider_id"):
        processing_turn(provider_request_id="request")


def test_turn_transitions_return_new_immutable_terminal_snapshots() -> None:
    processing = processing_turn()
    finished_at = CREATED_AT + timedelta(seconds=1)
    completed = processing.complete(
        assistant_text="answer",
        updated_at=finished_at,
        finished_at=finished_at,
    )

    assert processing.status is TurnStatus.PROCESSING
    assert completed.status is TurnStatus.COMPLETED
    with pytest.raises(FrozenInstanceError):
        completed.status = TurnStatus.PROCESSING  # type: ignore[misc]
    with pytest.raises(ValueError, match="only a processing turn"):
        completed.interrupt(
            assistant_text=None,
            updated_at=finished_at,
            finished_at=finished_at,
        )
