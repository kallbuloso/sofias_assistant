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


class ContextBudgetExceededError(ValueError):
    """Raised when mandatory context exceeds the selected input budget."""


class ContextBuilder:
    """Build system, selected historical, and current messages in memory."""

    def __init__(
        self,
        *,
        system_context: CoreSystemContext,
        max_recent_turns: int,
        max_estimated_input_tokens: int,
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
        if (
            isinstance(max_estimated_input_tokens, bool)
            or not isinstance(max_estimated_input_tokens, int)
            or max_estimated_input_tokens <= 0
        ):
            raise ValueError(
                "max_estimated_input_tokens must be an integer greater than zero"
            )
        self._system_context = system_context
        self._max_recent_turns = max_recent_turns
        self._max_estimated_input_tokens = max_estimated_input_tokens

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
        mandatory_messages = (
            AIMessage(role=AIMessageRole.SYSTEM, text=self._system_context.text),
            AIMessage(role=AIMessageRole.USER, text=current_turn.user_text),
        )
        effective_budget = self._effective_budget(model)
        mandatory_estimate = self._estimate_messages(mandatory_messages)
        if mandatory_estimate > effective_budget:
            raise ContextBudgetExceededError(
                "Mandatory context exceeds the selected model input budget"
            )
        historical_candidates = self._select_historical_turns(
            current_turn=current_turn,
            conversation_turns=conversation_turns,
            cloud_target=cloud_target,
        )
        historical_turns = self._select_budgeted_historical_turns(
            historical_candidates,
            remaining_budget=effective_budget - mandatory_estimate,
        )

        messages = [mandatory_messages[0]]
        for turn in historical_turns:
            if turn.assistant_text is None:
                raise ValueError("a completed historical turn requires assistant_text")
            messages.extend(
                (
                    AIMessage(role=AIMessageRole.USER, text=turn.user_text),
                    AIMessage(role=AIMessageRole.ASSISTANT, text=turn.assistant_text),
                )
            )
        messages.append(mandatory_messages[1])

        source_eligibility = (
            self._system_context.cloud_context_eligible,
            current_turn.cloud_context_eligible,
            *(turn.cloud_context_eligible for turn in historical_turns),
        )
        return ContextProjection(
            messages=tuple(messages),
            cloud_context_eligible=all(source_eligibility),
        )

    def _effective_budget(self, model: ModelDescriptor) -> int:
        if model.context_window is None:
            return self._max_estimated_input_tokens
        return min(self._max_estimated_input_tokens, model.context_window)

    @staticmethod
    def _estimate_message_tokens(message: AIMessage) -> int:
        """Return a deterministic UTF-8 framing heuristic, not provider tokens."""
        return (
            len(message.role.value.encode("utf-8"))
            + len(message.text.encode("utf-8"))
            + 1
        )

    @classmethod
    def _estimate_messages(cls, messages: Sequence[AIMessage]) -> int:
        return sum(cls._estimate_message_tokens(message) for message in messages)

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

    def _select_budgeted_historical_turns(
        self,
        candidates: Sequence[Turn],
        *,
        remaining_budget: int,
    ) -> tuple[Turn, ...]:
        selected_newest_first: list[Turn] = []
        for turn in reversed(candidates):
            if turn.assistant_text is None:
                raise ValueError("a completed historical turn requires assistant_text")
            turn_messages = (
                AIMessage(role=AIMessageRole.USER, text=turn.user_text),
                AIMessage(role=AIMessageRole.ASSISTANT, text=turn.assistant_text),
            )
            estimate = self._estimate_messages(turn_messages)
            if estimate > remaining_budget:
                break
            selected_newest_first.append(turn)
            remaining_budget -= estimate
        return tuple(reversed(selected_newest_first))
