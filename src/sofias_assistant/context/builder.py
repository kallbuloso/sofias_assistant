"""Deterministic Core-owned context projection without inference or I/O."""

from collections.abc import Sequence

from sofias_assistant.ai.contracts import (
    AIMessage,
    AIMessageRole,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
)
from sofias_assistant.context.models import ContextProjection, CoreSystemContext
from sofias_assistant.conversation.models import Turn, TurnStatus


class ContextLocalityError(ValueError):
    """Raised when mandatory context cannot safely reach the selected target."""


class ContextBuilder:
    """Build system, selected historical, and current messages in memory."""

    def __init__(
        self,
        *,
        system_context: CoreSystemContext,
        max_recent_turns: int,
    ) -> None:
        if not isinstance(system_context, CoreSystemContext):
            raise ValueError("system_context must be a CoreSystemContext")
        if isinstance(max_recent_turns, bool) or not isinstance(max_recent_turns, int):
            raise ValueError(
                "max_recent_turns must be an integer greater than or equal to zero"
            )
        if max_recent_turns < 0:
            raise ValueError(
                "max_recent_turns must be an integer greater than or equal to zero"
            )
        self._system_context = system_context
        self._max_recent_turns = max_recent_turns

    def build(
        self,
        *,
        current_turn: Turn,
        conversation_turns: Sequence[Turn],
        locality: DataLocality,
        model: ModelDescriptor,
    ) -> ContextProjection:
        """Return a bounded, causally ordered projection for a selected model."""
        self._validate_inputs(current_turn, conversation_turns, locality, model)
        cloud_target = model.execution_location is ExecutionLocation.CLOUD
        self._validate_mandatory_cloud_sources(current_turn, cloud_target)
        historical_turns = self._select_historical_turns(
            current_turn=current_turn,
            conversation_turns=conversation_turns,
            cloud_target=cloud_target,
        )

        messages = [
            AIMessage(role=AIMessageRole.SYSTEM, text=self._system_context.text)
        ]
        for turn in historical_turns:
            if turn.assistant_text is None:
                raise ValueError("a completed historical turn requires assistant_text")
            messages.extend(
                (
                    AIMessage(role=AIMessageRole.USER, text=turn.user_text),
                    AIMessage(role=AIMessageRole.ASSISTANT, text=turn.assistant_text),
                )
            )
        messages.append(AIMessage(role=AIMessageRole.USER, text=current_turn.user_text))

        source_eligibility = (
            self._system_context.cloud_context_eligible,
            current_turn.cloud_context_eligible,
            *(turn.cloud_context_eligible for turn in historical_turns),
        )
        return ContextProjection(
            messages=tuple(messages),
            cloud_context_eligible=all(source_eligibility),
        )

    def _validate_inputs(
        self,
        current_turn: Turn,
        conversation_turns: Sequence[Turn],
        locality: DataLocality,
        model: ModelDescriptor,
    ) -> None:
        if not isinstance(current_turn, Turn):
            raise ValueError("current_turn must be a Turn")
        if current_turn.status is not TurnStatus.PROCESSING:
            raise ValueError("current_turn must be processing")
        if not isinstance(locality, DataLocality):
            raise ValueError("locality must be a DataLocality")
        if not isinstance(model, ModelDescriptor):
            raise ValueError("model must be a ModelDescriptor")
        if locality is DataLocality.LOCAL_ONLY and (
            model.execution_location is ExecutionLocation.CLOUD
        ):
            raise ContextLocalityError(
                "LOCAL_ONLY is incompatible with a cloud execution target"
            )
        for turn in conversation_turns:
            if not isinstance(turn, Turn):
                raise ValueError("conversation_turns must contain Turn values")
            if turn.conversation_id != current_turn.conversation_id:
                raise ValueError(
                    "conversation_turns must belong to current_turn conversation"
                )

    def _validate_mandatory_cloud_sources(
        self, current_turn: Turn, cloud_target: bool
    ) -> None:
        if not cloud_target:
            return
        if not self._system_context.cloud_context_eligible:
            raise ContextLocalityError(
                "system context is not eligible for a cloud execution target"
            )
        if not current_turn.cloud_context_eligible:
            raise ContextLocalityError(
                "current turn is not eligible for a cloud execution target"
            )

    def _select_historical_turns(
        self,
        *,
        current_turn: Turn,
        conversation_turns: Sequence[Turn],
        cloud_target: bool,
    ) -> tuple[Turn, ...]:
        eligible = [
            turn
            for turn in conversation_turns
            if turn.sequence < current_turn.sequence
            and turn.status is TurnStatus.COMPLETED
            and (not cloud_target or turn.cloud_context_eligible)
        ]
        eligible.sort(key=lambda turn: turn.sequence)
        if self._max_recent_turns == 0:
            return ()
        return tuple(eligible[-self._max_recent_turns :])
