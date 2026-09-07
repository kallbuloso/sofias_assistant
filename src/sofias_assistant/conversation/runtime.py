"""Core-owned non-streaming text conversation application runtime."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sofias_assistant.ai.contracts import (
    AIRequest,
    AIRequestRequirements,
    Capability,
    DataLocality,
    ModelIdentity,
    ProviderInvocationError,
    TextResponse,
)
from sofias_assistant.ai.routing import CapabilityRouter, RoutingError
from sofias_assistant.context.builder import (
    ContextBudgetExceededError,
    ContextBuilder,
    ContextLocalityError,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork


class ConversationNotFoundError(RuntimeError):
    """Raised when text is submitted for an absent Core-owned Conversation."""


class TurnFinalizationConflictError(RuntimeError):
    """Raised when a persisted turn cannot safely transition from PROCESSING."""


@dataclass(frozen=True, slots=True)
class SendTextCommand:
    """Core-owned input for one textual operation within a Conversation."""

    conversation_id: UUID
    text: str
    locality: DataLocality
    cloud_context_eligible: bool
    model_override: ModelIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, UUID):
            raise ValueError("conversation_id must be a UUID")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must not be blank")
        if not isinstance(self.locality, DataLocality):
            raise ValueError("locality must be a DataLocality")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be a bool")
        if self.model_override is not None and not isinstance(
            self.model_override, ModelIdentity
        ):
            raise ValueError("model_override must be a ModelIdentity when provided")


@dataclass(frozen=True, slots=True)
class TextTurnResult:
    """Terminal durable snapshots returned for one non-streaming text operation."""

    conversation: Conversation
    turn: Turn

    def __post_init__(self) -> None:
        if not isinstance(self.conversation, Conversation):
            raise ValueError("conversation must be a Conversation")
        if not isinstance(self.turn, Turn):
            raise ValueError("turn must be a Turn")
        if self.turn.status not in (TurnStatus.COMPLETED, TurnStatus.FAILED):
            raise ValueError("turn must be completed or failed")


class TextConversationRuntime:
    """Coordinate durable text turns without holding a UoW across inference.

    Per-Conversation asyncio locks serialize non-streaming processing only in
    this runtime/Core process. The boundary relies on Slice 01's single-Core
    Operational Store ownership; it is neither distributed locking nor
    protection from external writers. Streaming/realtime may revisit this
    granularity in a later subpass.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        router: CapabilityRouter,
        context_builder: ContextBuilder,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._router = router
        self._context_builder = context_builder
        self._clock = clock or _utc_now
        self._id_factory = id_factory or uuid4
        self._conversation_locks: dict[UUID, asyncio.Lock] = {}

    async def create_conversation(self) -> Conversation:
        """Create and durably persist one Core-owned Conversation."""
        timestamp = self._current_utc_time()
        conversation = Conversation(
            id=self._new_uuid(), created_at=timestamp, updated_at=timestamp
        )
        async with self._uow_factory() as unit_of_work:
            unit_of_work.conversations.add(conversation)
            await unit_of_work.commit()
        return conversation

    async def send_text(self, command: SendTextCommand) -> TextTurnResult:
        """Persist, project, infer, and terminalize one textual Turn."""
        if not isinstance(command, SendTextCommand):
            raise ValueError("command must be a SendTextCommand")
        lock = self._conversation_locks.setdefault(
            command.conversation_id, asyncio.Lock()
        )
        async with lock:
            return await self._send_text_locked(command)

    async def _send_text_locked(self, command: SendTextCommand) -> TextTurnResult:
        conversation, processing_turn = await self._persist_processing_turn(command)
        requirements = AIRequestRequirements(
            required_capabilities=frozenset({Capability.TEXT_GENERATION}),
            preferred_capabilities=frozenset(),
            locality=command.locality,
        )
        try:
            route = self._router.route(
                requirements, model_override=command.model_override
            )
        except RoutingError:
            return await self._finalize_failure(
                conversation_id=conversation.id,
                turn_id=processing_turn.id,
                error_category="routing_error",
                error_message="No compatible text model is available",
            )

        persisted_turn, conversation_turns = await self._load_context_snapshots(
            conversation_id=conversation.id,
            turn_id=processing_turn.id,
        )
        try:
            projection = self._context_builder.build(
                current_turn=persisted_turn,
                conversation_turns=conversation_turns,
                locality=command.locality,
                model=route.descriptor,
            )
        except ContextBudgetExceededError:
            return await self._finalize_failure(
                conversation_id=conversation.id,
                turn_id=processing_turn.id,
                error_category="context_limit_exceeded",
                error_message="Context exceeds the selected model input budget",
            )
        except ContextLocalityError:
            return await self._finalize_failure(
                conversation_id=conversation.id,
                turn_id=processing_turn.id,
                error_category="context_locality_error",
                error_message="Context is not eligible for the selected execution target",
            )

        request = AIRequest(request_id=self._new_uuid(), messages=projection.messages)
        text_provider = route.binding.text_generation
        if text_provider is None:
            raise RuntimeError("Selected text-generation route has no text provider")
        try:
            response = await text_provider.generate_text(
                model=route.descriptor.identity,
                request=request,
            )
        except ProviderInvocationError as error:
            return await self._finalize_failure(
                conversation_id=conversation.id,
                turn_id=processing_turn.id,
                error_category=error.error.category.value,
                error_message=error.error.safe_message,
                ai_request_id=request.request_id,
                model=route.descriptor.identity,
                cloud_context_eligible=projection.cloud_context_eligible,
            )

        if not self._response_matches_route(
            response, request, route.descriptor.identity
        ):
            return await self._finalize_failure(
                conversation_id=conversation.id,
                turn_id=processing_turn.id,
                error_category="provider_protocol_error",
                error_message="Provider response did not match the selected request",
                ai_request_id=request.request_id,
                model=route.descriptor.identity,
                cloud_context_eligible=projection.cloud_context_eligible,
            )
        if response.tool_calls:
            return await self._finalize_failure(
                conversation_id=conversation.id,
                turn_id=processing_turn.id,
                error_category="tool_call_unsupported",
                error_message="Tool calls are not supported for text conversations",
                assistant_text=response.text,
                ai_request_id=request.request_id,
                model=route.descriptor.identity,
                provider_request_id=response.metadata.provider_request_id,
                provider_session_id=response.metadata.provider_session_id,
                cloud_context_eligible=projection.cloud_context_eligible,
            )
        return await self._finalize_success(
            conversation_id=conversation.id,
            turn_id=processing_turn.id,
            response=response,
            ai_request_id=request.request_id,
            model=route.descriptor.identity,
            cloud_context_eligible=projection.cloud_context_eligible,
        )

    async def _persist_processing_turn(
        self, command: SendTextCommand
    ) -> tuple[Conversation, Turn]:
        timestamp = self._current_utc_time()
        async with self._uow_factory() as unit_of_work:
            conversation = await unit_of_work.conversations.get_by_id(
                command.conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError("Conversation was not found")
            turn = Turn(
                id=self._new_uuid(),
                conversation_id=conversation.id,
                sequence=await unit_of_work.turns.next_sequence(conversation.id),
                status=TurnStatus.PROCESSING,
                input_modality=TurnInputModality.TEXT,
                cloud_context_eligible=command.cloud_context_eligible,
                user_text=command.text,
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
            updated_conversation = replace(conversation, updated_at=timestamp)
            unit_of_work.turns.add(turn)
            await unit_of_work.conversations.save(updated_conversation)
            await unit_of_work.commit()
        return updated_conversation, turn

    async def _load_context_snapshots(
        self, *, conversation_id: UUID, turn_id: UUID
    ) -> tuple[Turn, list[Turn]]:
        async with self._uow_factory() as unit_of_work:
            current_turn = await unit_of_work.turns.get_by_id(turn_id)
            if current_turn is None or current_turn.status is not TurnStatus.PROCESSING:
                raise TurnFinalizationConflictError(
                    "Processing turn was not available for context projection"
                )
            turns = await unit_of_work.turns.list_for_conversation(conversation_id)
        return current_turn, turns

    async def _finalize_success(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        response: TextResponse,
        ai_request_id: UUID,
        model: ModelIdentity,
        cloud_context_eligible: bool,
    ) -> TextTurnResult:
        timestamp = self._current_utc_time()
        async with self._uow_factory() as unit_of_work:
            turn, conversation = await self._load_processing_for_finalization(
                unit_of_work, conversation_id, turn_id
            )
            completed_turn = turn.complete(
                assistant_text=response.text,
                updated_at=timestamp,
                finished_at=timestamp,
                ai_request_id=ai_request_id,
                provider_id=model.provider_id,
                model_id=model.model_id,
                provider_request_id=response.metadata.provider_request_id,
                provider_session_id=response.metadata.provider_session_id,
                cloud_context_eligible=cloud_context_eligible,
            )
            updated_conversation = replace(conversation, updated_at=timestamp)
            await unit_of_work.turns.save(completed_turn)
            await unit_of_work.conversations.save(updated_conversation)
            await unit_of_work.commit()
        return TextTurnResult(updated_conversation, completed_turn)

    async def _finalize_failure(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        error_category: str,
        error_message: str,
        assistant_text: str | None = None,
        ai_request_id: UUID | None = None,
        model: ModelIdentity | None = None,
        provider_request_id: str | None = None,
        provider_session_id: str | None = None,
        cloud_context_eligible: bool | None = None,
    ) -> TextTurnResult:
        timestamp = self._current_utc_time()
        async with self._uow_factory() as unit_of_work:
            turn, conversation = await self._load_processing_for_finalization(
                unit_of_work, conversation_id, turn_id
            )
            failed_turn = turn.fail(
                assistant_text=assistant_text,
                error_category=error_category,
                error_message=error_message,
                updated_at=timestamp,
                finished_at=timestamp,
                ai_request_id=ai_request_id,
                provider_id=model.provider_id if model is not None else None,
                model_id=model.model_id if model is not None else None,
                provider_request_id=provider_request_id,
                provider_session_id=provider_session_id,
                cloud_context_eligible=cloud_context_eligible,
            )
            updated_conversation = replace(conversation, updated_at=timestamp)
            await unit_of_work.turns.save(failed_turn)
            await unit_of_work.conversations.save(updated_conversation)
            await unit_of_work.commit()
        return TextTurnResult(updated_conversation, failed_turn)

    async def _load_processing_for_finalization(
        self,
        unit_of_work: SqlAlchemyUnitOfWork,
        conversation_id: UUID,
        turn_id: UUID,
    ) -> tuple[Turn, Conversation]:
        turn = await unit_of_work.turns.get_by_id(turn_id)
        if turn is None or turn.status is not TurnStatus.PROCESSING:
            raise TurnFinalizationConflictError(
                "Processing turn was not available for finalization"
            )
        conversation = await unit_of_work.conversations.get_by_id(conversation_id)
        if conversation is None:
            raise TurnFinalizationConflictError(
                "Conversation was not available for finalization"
            )
        return turn, conversation

    @staticmethod
    def _response_matches_route(
        response: TextResponse,
        request: AIRequest,
        model: ModelIdentity,
    ) -> bool:
        return (
            response.metadata.request_id == request.request_id
            and response.metadata.model == model
        )

    def _current_utc_time(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(
                "Conversation runtime clock must return timezone-aware datetime"
            )
        return timestamp.astimezone(UTC)

    def _new_uuid(self) -> UUID:
        value = self._id_factory()
        if not isinstance(value, UUID):
            raise ValueError("Conversation runtime id_factory must return a UUID")
        return value


def _utc_now() -> datetime:
    return datetime.now(UTC)
