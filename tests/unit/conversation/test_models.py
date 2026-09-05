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
        "cloud_context_eligible": False,
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


@pytest.mark.parametrize("eligible", [0, 1, None, "true"])
def test_turn_rejects_non_bool_cloud_context_eligibility(eligible: object) -> None:
    with pytest.raises(ValueError, match="cloud_context_eligible"):
        processing_turn(cloud_context_eligible=eligible)


def test_turn_accepts_explicit_cloud_context_eligibility_values() -> None:
    assert processing_turn(cloud_context_eligible=True).cloud_context_eligible is True
    assert processing_turn(cloud_context_eligible=False).cloud_context_eligible is False


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


def test_interrupt_adds_correlation_without_mutating_source() -> None:
    processing = processing_turn()
    finished_at = CREATED_AT + timedelta(seconds=1)

    interrupted = processing.interrupt(
        assistant_text="partial",
        updated_at=finished_at,
        finished_at=finished_at,
        ai_request_id=REQUEST_ID,
        provider_id="provider",
        model_id="model",
        provider_request_id="provider-request",
        provider_session_id="provider-session",
    )

    assert interrupted.status is TurnStatus.INTERRUPTED
    assert interrupted.ai_request_id == REQUEST_ID
    assert interrupted.provider_id == "provider"
    assert interrupted.model_id == "model"
    assert interrupted.provider_request_id == "provider-request"
    assert interrupted.provider_session_id == "provider-session"
    assert processing.status is TurnStatus.PROCESSING
    assert processing.ai_request_id is None
    assert processing.provider_id is None


def test_fail_transition_adds_provider_correlation_without_mutating_source() -> None:
    processing = processing_turn()
    finished_at = CREATED_AT + timedelta(seconds=1)

    failed = processing.fail(
        assistant_text="partial",
        error_category="provider_unavailable",
        error_message="safe provider failure",
        updated_at=finished_at,
        finished_at=finished_at,
        ai_request_id=REQUEST_ID,
        provider_id="provider",
        model_id="model",
        provider_request_id="provider-request",
        provider_session_id="provider-session",
    )

    assert failed.status is TurnStatus.FAILED
    assert failed.error_category == "provider_unavailable"
    assert failed.error_message == "safe provider failure"
    assert failed.ai_request_id == REQUEST_ID
    assert failed.provider_id == "provider"
    assert failed.model_id == "model"
    assert failed.provider_request_id == "provider-request"
    assert failed.provider_session_id == "provider-session"
    assert processing.status is TurnStatus.PROCESSING
    assert processing.error_message is None
    assert processing.provider_id is None


def test_terminal_transitions_reuse_provider_correlation_invariants() -> None:
    finished_at = CREATED_AT + timedelta(seconds=1)
    with pytest.raises(ValueError, match="provided together"):
        processing_turn().interrupt(
            assistant_text=None,
            updated_at=finished_at,
            finished_at=finished_at,
            provider_id="provider",
        )
    with pytest.raises(ValueError, match="require provider_id"):
        processing_turn().fail(
            assistant_text=None,
            error_category=None,
            error_message="safe failure",
            updated_at=finished_at,
            finished_at=finished_at,
            provider_request_id="request",
        )
    with pytest.raises(ValueError, match="provider_id"):
        processing_turn().interrupt(
            assistant_text=None,
            updated_at=finished_at,
            finished_at=finished_at,
            provider_id="",
            model_id="model",
        )
    with pytest.raises(ValueError, match="provider_session_id"):
        processing_turn().fail(
            assistant_text=None,
            error_category=None,
            error_message="safe failure",
            updated_at=finished_at,
            finished_at=finished_at,
            provider_id="provider",
            model_id="model",
            provider_session_id=" ",
        )


def test_terminal_transitions_preserve_cloud_context_eligibility() -> None:
    processing = processing_turn(cloud_context_eligible=True)
    finished_at = CREATED_AT + timedelta(seconds=1)
    completed = processing.complete(
        assistant_text="answer", updated_at=finished_at, finished_at=finished_at
    )
    interrupted = processing.interrupt(
        assistant_text=None, updated_at=finished_at, finished_at=finished_at
    )
    failed = processing.fail(
        assistant_text=None,
        error_category=None,
        error_message="safe failure",
        updated_at=finished_at,
        finished_at=finished_at,
    )

    assert completed.cloud_context_eligible is True
    assert interrupted.cloud_context_eligible is True
    assert failed.cloud_context_eligible is True
    assert processing.cloud_context_eligible is True
