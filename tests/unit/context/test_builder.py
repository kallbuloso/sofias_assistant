"""Unit tests for deterministic, Core-owned context projection."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from sofias_assistant.ai.contracts import (
    AIMessage,
    AIMessageRole,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
)
from sofias_assistant.context.builder import ContextBuilder, ContextLocalityError
from sofias_assistant.context.models import ContextProjection, CoreSystemContext
from sofias_assistant.conversation.models import Turn, TurnInputModality, TurnStatus

CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000101")
OTHER_CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000102")
CREATED_AT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def system_context(
    *, eligible: bool = True, text: str = "System principles"
) -> CoreSystemContext:
    return CoreSystemContext(text=text, cloud_context_eligible=eligible)


def model(location: ExecutionLocation) -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity(provider_id="test", model_id=location.value),
        capabilities=frozenset({Capability.TEXT_GENERATION}),
        execution_location=location,
        context_window=4096,
    )


def turn(
    sequence: int,
    *,
    status: TurnStatus,
    eligible: bool = True,
    conversation_id: UUID = CONVERSATION_ID,
    user_text: str | None = None,
    assistant_text: str | None = None,
) -> Turn:
    finished_at = (
        CREATED_AT + timedelta(seconds=sequence)
        if status is not TurnStatus.PROCESSING
        else None
    )
    if status is TurnStatus.COMPLETED and assistant_text is None:
        assistant_text = f"assistant {sequence}"
    if status is TurnStatus.FAILED:
        error_message = "safe failure"
    else:
        error_message = None
    return Turn(
        id=UUID(f"00000000-0000-0000-0000-{sequence:012d}"),
        conversation_id=conversation_id,
        sequence=sequence,
        status=status,
        input_modality=TurnInputModality.TEXT,
        cloud_context_eligible=eligible,
        user_text=user_text if user_text is not None else f"user {sequence}",
        assistant_text=assistant_text,
        ai_request_id=None,
        provider_id=None,
        model_id=None,
        provider_request_id=None,
        provider_session_id=None,
        error_category=None,
        error_message=error_message,
        created_at=CREATED_AT,
        updated_at=finished_at or CREATED_AT,
        finished_at=finished_at,
    )


def current_turn(*, eligible: bool = True, user_text: str | None = None) -> Turn:
    return turn(
        10, status=TurnStatus.PROCESSING, eligible=eligible, user_text=user_text
    )


def message_pairs(projection: ContextProjection) -> list[tuple[AIMessageRole, str]]:
    return [(message.role, message.text) for message in projection.messages]


def test_core_system_context_validates_and_preserves_exact_text() -> None:
    context = system_context(text="  exact system text  ")
    assert context.text == "  exact system text  "
    with pytest.raises(ValueError, match="text"):
        system_context(text=" \t")
    with pytest.raises(ValueError, match="cloud_context_eligible"):
        CoreSystemContext(text="system", cloud_context_eligible=cast(bool, 1))


def test_context_projection_is_immutable_and_validates_contract() -> None:
    projection = ContextProjection(
        messages=(AIMessage(role=AIMessageRole.SYSTEM, text="system"),),
        cloud_context_eligible=True,
    )
    with pytest.raises(FrozenInstanceError):
        projection.cloud_context_eligible = False  # type: ignore[misc]
    with pytest.raises(ValueError, match="messages"):
        ContextProjection(messages=(), cloud_context_eligible=True)
    with pytest.raises(ValueError, match="cloud_context_eligible"):
        ContextProjection(
            messages=(AIMessage(role=AIMessageRole.SYSTEM, text="system"),),
            cloud_context_eligible=cast(bool, "true"),
        )


def test_builder_orders_system_history_and_current_independent_of_input_order() -> None:
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=2)
    projection = builder.build(
        current_turn=current_turn(),
        conversation_turns=(
            turn(2, status=TurnStatus.COMPLETED),
            current_turn(),
            turn(1, status=TurnStatus.COMPLETED),
        ),
        locality=DataLocality.CLOUD_ALLOWED,
        model=model(ExecutionLocation.LOCAL),
    )

    assert message_pairs(projection) == [
        (AIMessageRole.SYSTEM, "System principles"),
        (AIMessageRole.USER, "user 1"),
        (AIMessageRole.ASSISTANT, "assistant 1"),
        (AIMessageRole.USER, "user 2"),
        (AIMessageRole.ASSISTANT, "assistant 2"),
        (AIMessageRole.USER, "user 10"),
    ]


def test_builder_selects_most_recent_bounded_completed_history() -> None:
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=2)
    projection = builder.build(
        current_turn=current_turn(),
        conversation_turns=tuple(
            turn(sequence, status=TurnStatus.COMPLETED) for sequence in range(1, 6)
        ),
        locality=DataLocality.CLOUD_ALLOWED,
        model=model(ExecutionLocation.LOCAL),
    )

    assert message_pairs(projection) == [
        (AIMessageRole.SYSTEM, "System principles"),
        (AIMessageRole.USER, "user 4"),
        (AIMessageRole.ASSISTANT, "assistant 4"),
        (AIMessageRole.USER, "user 5"),
        (AIMessageRole.ASSISTANT, "assistant 5"),
        (AIMessageRole.USER, "user 10"),
    ]


def test_zero_recent_turn_bound_projects_only_system_and_current() -> None:
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=0)
    projection = builder.build(
        current_turn=current_turn(),
        conversation_turns=(turn(1, status=TurnStatus.COMPLETED),),
        locality=DataLocality.CLOUD_ALLOWED,
        model=model(ExecutionLocation.LOCAL),
    )
    assert message_pairs(projection) == [
        (AIMessageRole.SYSTEM, "System principles"),
        (AIMessageRole.USER, "user 10"),
    ]


def test_builder_excludes_non_completed_and_non_causal_history() -> None:
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=5)
    projection = builder.build(
        current_turn=current_turn(),
        conversation_turns=(
            turn(1, status=TurnStatus.COMPLETED),
            turn(2, status=TurnStatus.PROCESSING),
            turn(3, status=TurnStatus.INTERRUPTED),
            turn(4, status=TurnStatus.FAILED),
            turn(10, status=TurnStatus.COMPLETED),
            turn(11, status=TurnStatus.COMPLETED),
        ),
        locality=DataLocality.CLOUD_ALLOWED,
        model=model(ExecutionLocation.LOCAL),
    )
    assert message_pairs(projection) == [
        (AIMessageRole.SYSTEM, "System principles"),
        (AIMessageRole.USER, "user 1"),
        (AIMessageRole.ASSISTANT, "assistant 1"),
        (AIMessageRole.USER, "user 10"),
    ]


def test_builder_rejects_cross_conversation_and_non_processing_current_turn() -> None:
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=2)
    with pytest.raises(ValueError, match="conversation"):
        builder.build(
            current_turn=current_turn(),
            conversation_turns=(
                turn(
                    1,
                    status=TurnStatus.COMPLETED,
                    conversation_id=OTHER_CONVERSATION_ID,
                ),
            ),
            locality=DataLocality.CLOUD_ALLOWED,
            model=model(ExecutionLocation.LOCAL),
        )
    with pytest.raises(ValueError, match="processing"):
        builder.build(
            current_turn=turn(10, status=TurnStatus.COMPLETED),
            conversation_turns=(),
            locality=DataLocality.CLOUD_ALLOWED,
            model=model(ExecutionLocation.LOCAL),
        )


def test_local_target_includes_ineligible_sources_and_aggregates_false() -> None:
    builder = ContextBuilder(
        system_context=system_context(eligible=False), max_recent_turns=2
    )
    projection = builder.build(
        current_turn=current_turn(eligible=False),
        conversation_turns=(turn(1, status=TurnStatus.COMPLETED, eligible=False),),
        locality=DataLocality.LOCAL_ONLY,
        model=model(ExecutionLocation.LOCAL),
    )
    assert (AIMessageRole.USER, "user 1") in message_pairs(projection)
    assert projection.cloud_context_eligible is False


def test_cloud_target_excludes_ineligible_history_without_contaminating_aggregate() -> (
    None
):
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=2)
    projection = builder.build(
        current_turn=current_turn(),
        conversation_turns=(
            turn(1, status=TurnStatus.COMPLETED, eligible=False),
            turn(2, status=TurnStatus.COMPLETED, eligible=True),
        ),
        locality=DataLocality.CLOUD_ALLOWED,
        model=model(ExecutionLocation.CLOUD),
    )
    assert message_pairs(projection) == [
        (AIMessageRole.SYSTEM, "System principles"),
        (AIMessageRole.USER, "user 2"),
        (AIMessageRole.ASSISTANT, "assistant 2"),
        (AIMessageRole.USER, "user 10"),
    ]
    assert projection.cloud_context_eligible is True


@pytest.mark.parametrize("mandatory_source", ["system", "current"])
def test_cloud_target_fails_closed_for_ineligible_mandatory_sources(
    mandatory_source: str,
) -> None:
    builder = ContextBuilder(
        system_context=system_context(eligible=mandatory_source != "system"),
        max_recent_turns=1,
    )
    with pytest.raises(ContextLocalityError, match="eligible"):
        builder.build(
            current_turn=current_turn(eligible=mandatory_source != "current"),
            conversation_turns=(),
            locality=DataLocality.CLOUD_ALLOWED,
            model=model(ExecutionLocation.CLOUD),
        )


def test_local_only_cloud_target_fails_closed_before_projection() -> None:
    builder = ContextBuilder(system_context=system_context(), max_recent_turns=1)
    with pytest.raises(ContextLocalityError, match="LOCAL_ONLY"):
        builder.build(
            current_turn=current_turn(),
            conversation_turns=(),
            locality=DataLocality.LOCAL_ONLY,
            model=model(ExecutionLocation.CLOUD),
        )


@pytest.mark.parametrize(
    ("locality", "location"),
    [
        (DataLocality.LOCAL_ONLY, ExecutionLocation.LOCAL),
        (DataLocality.CLOUD_ALLOWED, ExecutionLocation.LOCAL),
        (DataLocality.CLOUD_ALLOWED, ExecutionLocation.CLOUD),
        (DataLocality.CLOUD_PREFERRED, ExecutionLocation.LOCAL),
        (DataLocality.CLOUD_PREFERRED, ExecutionLocation.CLOUD),
    ],
)
def test_allowed_locality_and_target_combinations_build_projection(
    locality: DataLocality,
    location: ExecutionLocation,
) -> None:
    projection = ContextBuilder(
        system_context=system_context(), max_recent_turns=1
    ).build(
        current_turn=current_turn(),
        conversation_turns=(),
        locality=locality,
        model=model(location),
    )
    assert projection.cloud_context_eligible is True


def test_builder_preserves_exact_source_text() -> None:
    builder = ContextBuilder(
        system_context=system_context(text="  system exact  "), max_recent_turns=1
    )
    projection = builder.build(
        current_turn=current_turn(user_text="  current exact  "),
        conversation_turns=(
            turn(
                1,
                status=TurnStatus.COMPLETED,
                user_text="  history user exact  ",
                assistant_text="  history assistant exact  ",
            ),
        ),
        locality=DataLocality.CLOUD_ALLOWED,
        model=model(ExecutionLocation.LOCAL),
    )
    assert message_pairs(projection) == [
        (AIMessageRole.SYSTEM, "  system exact  "),
        (AIMessageRole.USER, "  history user exact  "),
        (AIMessageRole.ASSISTANT, "  history assistant exact  "),
        (AIMessageRole.USER, "  current exact  "),
    ]


@pytest.mark.parametrize("max_recent_turns", [-1, True, cast(int, "1")])
def test_builder_rejects_invalid_recent_turn_bound(max_recent_turns: int) -> None:
    with pytest.raises(ValueError, match="max_recent_turns"):
        ContextBuilder(
            system_context=system_context(), max_recent_turns=max_recent_turns
        )
