"""Provider-neutral realtime conversation runtime; no transport or SDK concerns."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    AssistantAudioChunk,
    AssistantTranscriptFinal,
    AssistantTranscriptPartial,
    AudioFormat,
    AudioInputFrame,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelIdentity,
    ProviderInvocationError,
    RealtimeInteractionId,
    RealtimeResponseCompleted,
    RealtimeResponseFailed,
    RealtimeSessionFailed,
    RealtimeSessionId,
    UserTranscriptFinal,
    UserTranscriptPartial,
)
from sofias_assistant.ai.providers import RealtimeProviderSession
from sofias_assistant.ai.routing import CapabilityRouter, RoutingError
from sofias_assistant.context.builder import ContextBuilder, ContextLocalityError
from sofias_assistant.conversation.coordination import (
    ConversationActivityCoordinator,
    ConversationActivityLease,
)
from sofias_assistant.conversation.events import (
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)
from sofias_assistant.conversation.realtime_events import (
    ConversationRealtimeSessionFailed,
    RealtimeAssistantAudioChunk,
    RealtimeAssistantTranscriptFinal,
    RealtimeAssistantTranscriptPartial,
    RealtimeConversationEvent,
    RealtimeInteractionFailed,
    RealtimeInteractionStarted,
    RealtimeSessionClosed,
    RealtimeSessionOpened,
    RealtimeUserTranscriptFinal,
    RealtimeUserTranscriptPartial,
)
from sofias_assistant.conversation.realtime_models import (
    REALTIME_ASSISTANT_TRANSCRIPT_MAX_BYTES,
    REALTIME_AUDIO_FRAME_MAX_BYTES,
    REALTIME_EVENT_QUEUE_MAX_ITEMS,
    REALTIME_TEXT_EVENT_MAX_BYTES,
    InteractionGeneration,
    RealtimeInteraction,
    RealtimeSession,
    RealtimeSessionState,
)
from sofias_assistant.conversation.runtime import ConversationNotFoundError
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork


class RealtimeSessionConflictError(RuntimeError):
    pass


class RealtimeSessionNotFoundError(RuntimeError):
    pass


class InvalidRealtimeStateError(RuntimeError):
    pass


class RealtimeProtocolError(RuntimeError):
    pass


class _EventDeliveryStopped(RuntimeError):
    """Internal signal that a blocked normal event cannot be delivered."""


@dataclass(frozen=True, slots=True)
class OpenRealtimeSessionCommand:
    conversation_id: UUID
    locality: DataLocality
    cloud_context_eligible: bool
    input_audio_format: AudioFormat
    output_audio_format: AudioFormat
    model_override: ModelIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.conversation_id, UUID):
            raise ValueError("conversation_id must be a UUID")
        if not isinstance(self.locality, DataLocality):
            raise ValueError("locality must be DataLocality")
        if not isinstance(self.cloud_context_eligible, bool):
            raise ValueError("cloud_context_eligible must be bool")
        if not isinstance(self.input_audio_format, AudioFormat) or not isinstance(
            self.output_audio_format, AudioFormat
        ):
            raise ValueError("audio formats must be AudioFormat")
        if self.model_override is not None and not isinstance(
            self.model_override, ModelIdentity
        ):
            raise ValueError("model_override must be ModelIdentity")


_END = object()
_RESOURCE_LIMIT_MESSAGE = "Realtime provider event exceeded resource limits"

type _InteractionProviderEvent = (
    UserTranscriptPartial
    | UserTranscriptFinal
    | AssistantAudioChunk
    | AssistantTranscriptPartial
    | AssistantTranscriptFinal
    | RealtimeResponseCompleted
    | RealtimeResponseFailed
)


class RealtimeConversationRuntime:
    """Own transient Core sessions while persisting only final voice Turns."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        router: CapabilityRouter,
        context_builder: ContextBuilder,
        activity_coordinator: ConversationActivityCoordinator,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._uow_factory, self._router, self._context_builder = (
            uow_factory,
            router,
            context_builder,
        )
        self._coordinator = activity_coordinator
        self._clock, self._id_factory = (
            clock or (lambda: datetime.now(UTC)),
            id_factory or uuid4,
        )
        self._sessions: dict[RealtimeSessionId, RealtimeSession] = {}
        self._conversation_sessions: dict[UUID, RealtimeSessionId] = {}
        self._sessions_gate = asyncio.Lock()

    async def open_session(
        self, command: OpenRealtimeSessionCommand
    ) -> RealtimeSession:
        if not isinstance(command, OpenRealtimeSessionCommand):
            raise ValueError("command must be OpenRealtimeSessionCommand")
        async with self._sessions_gate:
            if command.conversation_id in self._conversation_sessions:
                raise RealtimeSessionConflictError(
                    "A realtime session is already open for this conversation"
                )
            session_id = RealtimeSessionId(self._id_factory())
            lease = await self._coordinator.acquire_voice_activity(
                command.conversation_id
            )
            try:
                route, turns = await self._route_and_load(command)
                seed = self._context_builder.build_realtime_seed(
                    conversation_id=command.conversation_id,
                    conversation_turns=turns,
                    locality=command.locality,
                    model=route.descriptor,
                )
                if (
                    route.descriptor.execution_location is ExecutionLocation.CLOUD
                    and not command.cloud_context_eligible
                ):
                    raise ContextLocalityError(
                        "Voice input is not eligible for a cloud execution target"
                    )
                revision = await self._coordinator.context_revision(
                    command.conversation_id
                )
                provider = route.binding.realtime
                if provider is None:
                    raise RuntimeError(
                        "Selected realtime route has no realtime provider"
                    )
                from sofias_assistant.ai.contracts import RealtimeSessionRequest

                provider_session = await provider.open_realtime_session(
                    model=route.descriptor.identity,
                    request=RealtimeSessionRequest(
                        session_id,
                        command.input_audio_format,
                        command.output_audio_format,
                        seed,
                    ),
                )
                session = RealtimeSession(
                    session_id,
                    command.conversation_id,
                    route.descriptor.identity,
                    command.input_audio_format,
                    command.output_audio_format,
                    command.locality,
                    command.cloud_context_eligible,
                    revision,
                    event_queue=asyncio.Queue(maxsize=REALTIME_EVENT_QUEUE_MAX_ITEMS),
                )
                self._sessions[session_id] = session
                self._conversation_sessions[command.conversation_id] = session_id
                self._install_provider_session(session, provider_session)
                await self._emit(
                    session,
                    RealtimeSessionOpened(
                        session.id, session.conversation_id, session.model
                    ),
                )
                return session
            except ProviderInvocationError as error:
                raise InvalidRealtimeStateError(
                    "Realtime provider could not open a session"
                ) from error
            finally:
                await lease.release()

    async def start_interaction(
        self, realtime_session_id: RealtimeSessionId
    ) -> RealtimeInteractionId:
        session = self._session(realtime_session_id)
        async with self._coordinator.voice_transition(session.conversation_id):
            active = session.active_interaction
            lease: ConversationActivityLease | None = None
            if session.state is RealtimeSessionState.IDLE and active is None:
                lease = await self._coordinator.acquire_voice_activity(
                    session.conversation_id
                )
            elif session.state is RealtimeSessionState.ACTIVE and active is not None:
                if not active.input_committed:
                    raise InvalidRealtimeStateError(
                        "Realtime input must be committed before barge-in"
                    )
                lease = active.lease
                await self._retire_active_interaction(
                    session, active, cancel=False, release_lease=False
                )
            else:
                raise InvalidRealtimeStateError("Realtime session is not idle")

            assert lease is not None
            try:
                if (
                    session.provider_context_stale
                    or session.synced_context_revision
                    != await self._coordinator.context_revision(session.conversation_id)
                ):
                    await self._reseed_provider(session)
                interaction_id = RealtimeInteractionId(self._id_factory())
                response_epoch = session.next_response_epoch()
                interaction = RealtimeInteraction(
                    interaction_id,
                    lease,
                    session.cloud_context_eligible,
                    response_epoch,
                )
                provider = self._provider(session)
                await provider.start_interaction(realtime_interaction_id=interaction_id)
                session.active_interaction, session.state = (
                    interaction,
                    RealtimeSessionState.ACTIVE,
                )
                await self._emit(
                    session, RealtimeInteractionStarted(session.id, interaction_id)
                )
                return interaction_id
            except BaseException:
                await self._close_provider(session)
                session.active_interaction = None
                session.state = RealtimeSessionState.IDLE
                session.provider_context_stale = True
                await lease.release()
                raise

    async def send_audio(
        self, realtime_session_id: RealtimeSessionId, audio: bytes
    ) -> None:
        session, interaction = self._active(realtime_session_id)
        if not isinstance(audio, bytes) or not audio:
            raise ValueError("audio must be non-empty bytes")
        if len(audio) > REALTIME_AUDIO_FRAME_MAX_BYTES:
            raise ValueError("audio frame exceeds the realtime safety limit")
        if interaction.input_committed:
            raise InvalidRealtimeStateError("Realtime interaction input is committed")
        frame = AudioInputFrame(interaction.next_input_sequence, audio)
        await self._provider(session).send_audio(frame=frame)
        interaction.next_input_sequence += 1

    async def commit_interaction(self, realtime_session_id: RealtimeSessionId) -> None:
        session, interaction = self._active(realtime_session_id)
        if interaction.input_committed:
            raise InvalidRealtimeStateError("Realtime interaction input is committed")
        interaction.input_committed = True
        await self._provider(session).commit_interaction(
            realtime_interaction_id=interaction.id
        )

    async def interrupt_interaction(
        self,
        realtime_session_id: RealtimeSessionId,
        realtime_interaction_id: RealtimeInteractionId,
    ) -> None:
        """Stop a committed response and retire its active interaction."""

        await self._retire_interaction(
            realtime_session_id,
            realtime_interaction_id,
            cancel=False,
        )

    async def cancel_interaction(
        self,
        realtime_session_id: RealtimeSessionId,
        realtime_interaction_id: RealtimeInteractionId,
    ) -> None:
        """Cancel an uncommitted input interaction without creating a Turn."""

        await self._retire_interaction(
            realtime_session_id,
            realtime_interaction_id,
            cancel=True,
        )

    async def events(
        self, realtime_session_id: RealtimeSessionId
    ) -> AsyncIterator[RealtimeConversationEvent]:
        session = self._session(realtime_session_id)
        if session.event_consumer_claimed:
            raise InvalidRealtimeStateError(
                "Realtime session event stream already has a consumer"
            )
        session.event_consumer_claimed = True
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        try:
            while True:
                if session.event_stream_closed and queue.empty():
                    return
                session.event_consumer_waiting.set()
                try:
                    event = await queue.get()
                finally:
                    session.event_consumer_waiting.clear()
                if event is _END:
                    return
                yield event
        finally:
            session.event_delivery_stopped.set()
            await self._cleanup_terminal_session_if_releasable(session)

    async def _retire_interaction(
        self,
        realtime_session_id: RealtimeSessionId,
        realtime_interaction_id: RealtimeInteractionId,
        *,
        cancel: bool,
    ) -> None:
        session = self._session(realtime_session_id)
        async with self._coordinator.voice_transition(session.conversation_id):
            active = session.active_interaction
            if active is None or active.id != realtime_interaction_id:
                raise InvalidRealtimeStateError(
                    "Realtime interaction is not the active interaction"
                )
            await self._retire_active_interaction(
                session, active, cancel=cancel, release_lease=True
            )

    async def _retire_active_interaction(
        self,
        session: RealtimeSession,
        active: RealtimeInteraction,
        *,
        cancel: bool,
        release_lease: bool,
    ) -> None:
        if cancel and active.input_committed:
            raise InvalidRealtimeStateError(
                "Committed realtime input cannot be cancelled"
            )
        if not cancel and not active.input_committed:
            raise InvalidRealtimeStateError(
                "Realtime input must be committed before interruption"
            )

        await self._provider(session).interrupt(realtime_interaction_id=active.id)
        if active.durable_turn_id is not None:
            conversation, turn = await self._terminalize_turn(
                session,
                active,
                "interrupted",
                "Realtime interaction was interrupted",
                interrupted=True,
            )
            await self._emit(
                session,
                ConversationTurnInterrupted(conversation, turn),
                terminal=True,
            )
        session.provider_context_stale = session.provider_context_stale or not cancel
        session.retire_interaction(active)
        session.active_interaction = None
        session.state = RealtimeSessionState.IDLE
        if release_lease:
            await active.lease.release()

    async def close_session(self, realtime_session_id: RealtimeSessionId) -> None:
        session = self._session(realtime_session_id)
        session.event_delivery_shutdown_requested.set()
        session.event_delivery_close_requested.set()
        async with self._coordinator.voice_transition(session.conversation_id):
            if session.state in (
                RealtimeSessionState.CLOSED,
                RealtimeSessionState.FAILED,
            ):
                return
            interaction = session.active_interaction
            if interaction is not None:
                if interaction.durable_turn_id is not None:
                    conversation, turn = await self._terminalize_turn(
                        session,
                        interaction,
                        "interrupted",
                        "Realtime session was closed",
                        interrupted=True,
                    )
                    await self._emit(
                        session,
                        ConversationTurnInterrupted(conversation, turn),
                        terminal=True,
                    )
                await self._release_interaction(session)
            await self._close_provider(session)
            session.state = RealtimeSessionState.CLOSED
            await self._emit(session, RealtimeSessionClosed(session.id), terminal=True)
            await self._end_events(session)
            async with self._sessions_gate:
                self._conversation_sessions.pop(session.conversation_id, None)

    async def close_all(self) -> None:
        for session_id in tuple(self._sessions):
            await self.close_session(session_id)

    async def _route_and_load(self, command: OpenRealtimeSessionCommand):
        async with self._uow_factory() as uow:
            conversation = await uow.conversations.get_by_id(command.conversation_id)
            if conversation is None:
                raise ConversationNotFoundError("Conversation was not found")
            turns = await uow.turns.list_for_conversation(command.conversation_id)
        requirements = AIRequestRequirements(
            frozenset(
                {Capability.REALTIME, Capability.AUDIO_INPUT, Capability.AUDIO_OUTPUT}
            ),
            frozenset(),
            command.locality,
        )
        try:
            route = self._router.route(
                requirements, model_override=command.model_override
            )
        except RoutingError as error:
            raise InvalidRealtimeStateError(
                "No compatible realtime model is available"
            ) from error
        return route, turns

    async def _reseed_provider(self, session: RealtimeSession) -> None:
        await self._close_provider(session)
        command = OpenRealtimeSessionCommand(
            session.conversation_id,
            session.locality,
            session.cloud_context_eligible,
            session.input_audio_format,
            session.output_audio_format,
            session.model,
        )
        route, turns = await self._route_and_load(command)
        seed = self._context_builder.build_realtime_seed(
            conversation_id=session.conversation_id,
            conversation_turns=turns,
            locality=session.locality,
            model=route.descriptor,
        )
        provider = route.binding.realtime
        if provider is None:
            raise RuntimeError("Selected realtime route has no realtime provider")
        from sofias_assistant.ai.contracts import RealtimeSessionRequest

        provider_session = await provider.open_realtime_session(
            model=session.model,
            request=RealtimeSessionRequest(
                session.id,
                session.input_audio_format,
                session.output_audio_format,
                seed,
            ),
        )
        self._install_provider_session(session, provider_session)
        session.synced_context_revision = await self._coordinator.context_revision(
            session.conversation_id
        )
        session.provider_context_stale = False

    def _install_provider_session(
        self, session: RealtimeSession, provider_session: RealtimeProviderSession
    ) -> None:
        if session.provider_session is not None or session.consumer_task is not None:
            raise InvalidRealtimeStateError(
                "Realtime provider session ownership is already installed"
            )
        session.provider_generation += 1
        provider_generation = session.provider_generation
        session.provider_session = provider_session
        session.consumer_task = asyncio.create_task(
            self._consume_provider_events(
                session, provider_session, provider_generation
            )
        )

    def _is_current_provider(
        self,
        session: RealtimeSession,
        provider_session: RealtimeProviderSession,
        provider_generation: int,
    ) -> bool:
        return (
            session.provider_generation == provider_generation
            and session.provider_session is provider_session
        )

    async def _consume_provider_events(
        self,
        session: RealtimeSession,
        provider_session: RealtimeProviderSession,
        provider_generation: int,
    ) -> None:
        try:
            async for event in provider_session.events():
                await self._handle_provider_event(
                    session, event, provider_session, provider_generation
                )
            if self._is_current_provider(
                session, provider_session, provider_generation
            ) and session.state not in (
                RealtimeSessionState.CLOSED,
                RealtimeSessionState.FAILED,
            ):
                await self._fail_current_provider_session(
                    session,
                    provider_session,
                    provider_generation,
                    "Realtime provider session ended unexpectedly",
                )
        except asyncio.CancelledError:
            raise
        except _EventDeliveryStopped:
            return
        except BaseException:
            if self._is_current_provider(
                session, provider_session, provider_generation
            ) and session.state not in (
                RealtimeSessionState.CLOSED,
                RealtimeSessionState.FAILED,
            ):
                await self._fail_current_provider_session(
                    session,
                    provider_session,
                    provider_generation,
                    "Realtime provider session failed",
                )

    async def _handle_provider_event(
        self,
        session: RealtimeSession,
        event: object,
        provider_session: RealtimeProviderSession,
        provider_generation: int,
    ) -> None:
        if not self._is_current_provider(
            session, provider_session, provider_generation
        ):
            return
        if not isinstance(
            event,
            (
                UserTranscriptPartial,
                UserTranscriptFinal,
                AssistantAudioChunk,
                AssistantTranscriptPartial,
                AssistantTranscriptFinal,
                RealtimeResponseCompleted,
                RealtimeResponseFailed,
                RealtimeSessionFailed,
            ),
        ):
            await self._protocol_failure_from_provider(
                session,
                provider_session,
                provider_generation,
                "Provider emitted an unsupported event",
            )
            return
        if isinstance(event, RealtimeSessionFailed):
            if event.realtime_session_id != session.id:
                return await self._protocol_failure_from_provider(
                    session,
                    provider_session,
                    provider_generation,
                    "Provider session correlation failed",
                )
            if self._provider_event_resource_violation(event) is not None:
                await self._protocol_failure_from_provider(
                    session,
                    provider_session,
                    provider_generation,
                    _RESOURCE_LIMIT_MESSAGE,
                )
                return
            await self._fail_current_provider_session(
                session,
                provider_session,
                provider_generation,
                event.error.safe_message,
            )
            return
        async with self._coordinator.voice_transition(session.conversation_id):
            if not self._is_current_provider(
                session, provider_session, provider_generation
            ):
                return
            if self._provider_event_resource_violation(event) is not None:
                await self._protocol_failure_locked(session, _RESOURCE_LIMIT_MESSAGE)
                return
            await self._handle_interaction_event(session, event)

    async def _handle_interaction_event(
        self, session: RealtimeSession, event: _InteractionProviderEvent
    ) -> None:
        if not hasattr(event, "realtime_interaction_id"):
            await self._protocol_failure_locked(
                session, "Provider emitted an event outside an active interaction"
            )
            return
        if event.realtime_session_id != session.id:
            await self._protocol_failure_locked(
                session, "Provider session correlation failed"
            )
            return
        generation = session.classify_interaction(event.realtime_interaction_id)
        if generation is InteractionGeneration.RETIRED_KNOWN:
            return
        if generation is InteractionGeneration.UNKNOWN:
            await self._protocol_failure_locked(
                session, "Provider event correlation failed"
            )
            return
        interaction = session.active_interaction
        if interaction is None or event.sequence <= interaction.last_provider_sequence:
            await self._protocol_failure_locked(
                session, "Provider event ordering or correlation failed"
            )
            return
        interaction.last_provider_sequence = event.sequence
        if isinstance(event, UserTranscriptPartial):
            await self._emit(
                session,
                RealtimeUserTranscriptPartial(
                    session.id, interaction.id, event.sequence, event.text
                ),
            )
            return
        if isinstance(event, UserTranscriptFinal):
            if interaction.user_transcript_final is not None or not event.text.strip():
                return await self._protocol_failure_locked(
                    session, "Provider user transcript was invalid"
                )
            interaction.user_transcript_final = event.text
            conversation, turn = await self._persist_voice_turn(
                session, interaction, event.text
            )
            await self._emit(
                session,
                RealtimeUserTranscriptFinal(
                    session.id, interaction.id, event.sequence, event.text
                ),
            )
            await self._emit(session, ConversationTurnStarted(conversation, turn))
            return
        if isinstance(event, AssistantAudioChunk):
            await self._emit(
                session,
                RealtimeAssistantAudioChunk(
                    session.id,
                    interaction.id,
                    event.sequence,
                    event.audio,
                    event.audio_format,
                ),
            )
            return
        if isinstance(event, AssistantTranscriptPartial):
            fragment_bytes = len(event.text.encode("utf-8"))
            if (
                interaction.assistant_transcript_bytes + fragment_bytes
                > REALTIME_ASSISTANT_TRANSCRIPT_MAX_BYTES
            ):
                await self._protocol_failure_locked(session, _RESOURCE_LIMIT_MESSAGE)
                return
            interaction.assistant_transcript += event.text
            interaction.assistant_transcript_bytes += fragment_bytes
            await self._emit(
                session,
                RealtimeAssistantTranscriptPartial(
                    session.id, interaction.id, event.sequence, event.text
                ),
            )
            return
        if isinstance(event, AssistantTranscriptFinal):
            interaction.assistant_transcript_final = event.text
            await self._emit(
                session,
                RealtimeAssistantTranscriptFinal(
                    session.id, interaction.id, event.sequence, event.text
                ),
            )
            return
        if isinstance(event, RealtimeResponseFailed):
            await self._fail_interaction(
                session,
                interaction,
                event.error.category.value,
                event.error.safe_message,
            )
            return
        if isinstance(event, RealtimeResponseCompleted):
            if (
                interaction.user_transcript_final is None
                or interaction.durable_turn_id is None
                or interaction.assistant_transcript_final is None
            ):
                return await self._protocol_failure_locked(
                    session, "Provider completed before required transcripts"
                )
            conversation, turn = await self._complete_turn(session, interaction)
            await self._emit(
                session, ConversationTurnCompleted(conversation, turn), terminal=True
            )
            session.synced_context_revision = (
                await self._coordinator.mark_context_changed(session.conversation_id)
            )
            await self._release_interaction(session)
            return
        await self._protocol_failure_locked(
            session, "Provider emitted an unsupported event"
        )

    @staticmethod
    def _provider_event_resource_violation(event: object) -> str | None:
        if isinstance(event, AssistantAudioChunk):
            if len(event.audio) > REALTIME_AUDIO_FRAME_MAX_BYTES:
                return _RESOURCE_LIMIT_MESSAGE
        elif isinstance(
            event,
            (
                UserTranscriptPartial,
                UserTranscriptFinal,
                AssistantTranscriptPartial,
                AssistantTranscriptFinal,
            ),
        ):
            if len(event.text.encode("utf-8")) > REALTIME_TEXT_EVENT_MAX_BYTES:
                return _RESOURCE_LIMIT_MESSAGE
        elif isinstance(event, (RealtimeResponseFailed, RealtimeSessionFailed)):
            if (
                len(event.error.safe_message.encode("utf-8"))
                > REALTIME_TEXT_EVENT_MAX_BYTES
            ):
                return _RESOURCE_LIMIT_MESSAGE
        return None

    async def _persist_voice_turn(
        self, session: RealtimeSession, interaction: RealtimeInteraction, text: str
    ) -> tuple[Conversation, Turn]:
        timestamp = self._time()
        async with self._uow_factory() as uow:
            conversation = await uow.conversations.get_by_id(session.conversation_id)
            if conversation is None:
                raise ConversationNotFoundError("Conversation was not found")
            turn = Turn(
                self._id_factory(),
                conversation.id,
                await uow.turns.next_sequence(conversation.id),
                TurnStatus.PROCESSING,
                TurnInputModality.VOICE,
                session.cloud_context_eligible
                and interaction.input_cloud_context_eligible,
                text,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                timestamp,
                timestamp,
                None,
            )
            conversation = replace(conversation, updated_at=timestamp)
            uow.turns.add(turn)
            await uow.conversations.save(conversation)
            await uow.commit()
        interaction.durable_turn_id = turn.id
        return conversation, turn

    async def _complete_turn(
        self, session: RealtimeSession, interaction: RealtimeInteraction
    ) -> tuple[Conversation, Turn]:
        timestamp = self._time()
        async with self._uow_factory() as uow:
            if interaction.durable_turn_id is None:
                raise RealtimeProtocolError("Processing voice turn is unavailable")
            turn = await uow.turns.get_by_id(interaction.durable_turn_id)
            conversation = await uow.conversations.get_by_id(session.conversation_id)
            if turn is None or conversation is None:
                raise RealtimeProtocolError("Processing voice turn is unavailable")
            turn = turn.complete(
                assistant_text=interaction.assistant_transcript_final or "",
                updated_at=timestamp,
                finished_at=timestamp,
                provider_id=session.model.provider_id,
                model_id=session.model.model_id,
            )
            conversation = replace(conversation, updated_at=timestamp)
            await uow.turns.save(turn)
            await uow.conversations.save(conversation)
            await uow.commit()
        return conversation, turn

    async def _terminalize_turn(
        self,
        session: RealtimeSession,
        interaction: RealtimeInteraction,
        category: str,
        message: str,
        *,
        interrupted: bool = False,
    ) -> tuple[Conversation, Turn]:
        timestamp = self._time()
        text = interaction.assistant_transcript or None
        async with self._uow_factory() as uow:
            if interaction.durable_turn_id is None:
                raise RealtimeProtocolError("Processing voice turn is unavailable")
            turn = await uow.turns.get_by_id(interaction.durable_turn_id)
            conversation = await uow.conversations.get_by_id(session.conversation_id)
            if turn is None or conversation is None:
                raise RealtimeProtocolError("Processing voice turn is unavailable")
            turn = (
                turn.interrupt(
                    assistant_text=text,
                    updated_at=timestamp,
                    finished_at=timestamp,
                    provider_id=session.model.provider_id,
                    model_id=session.model.model_id,
                )
                if interrupted
                else turn.fail(
                    error_message=message,
                    error_category=category,
                    assistant_text=text,
                    updated_at=timestamp,
                    finished_at=timestamp,
                    provider_id=session.model.provider_id,
                    model_id=session.model.model_id,
                )
            )
            conversation = replace(conversation, updated_at=timestamp)
            await uow.turns.save(turn)
            await uow.conversations.save(conversation)
            await uow.commit()
        return conversation, turn

    async def _fail_interaction(
        self,
        session: RealtimeSession,
        interaction: RealtimeInteraction,
        category: str,
        message: str,
    ) -> None:
        if interaction.durable_turn_id is None:
            await self._emit(
                session,
                RealtimeInteractionFailed(session.id, interaction.id, message),
                terminal=True,
            )
        else:
            conversation, turn = await self._terminalize_turn(
                session, interaction, category, message
            )
            await self._emit(
                session, ConversationTurnFailed(conversation, turn), terminal=True
            )
        session.provider_context_stale = True
        await self._release_interaction(session)

    async def _protocol_failure_from_provider(
        self,
        session: RealtimeSession,
        provider_session: RealtimeProviderSession,
        provider_generation: int,
        message: str,
    ) -> None:
        async with self._coordinator.voice_transition(session.conversation_id):
            if not self._is_current_provider(
                session, provider_session, provider_generation
            ):
                return
            await self._protocol_failure_locked(session, message)

    async def _protocol_failure_locked(
        self, session: RealtimeSession, message: str
    ) -> None:
        if session.state in (RealtimeSessionState.CLOSED, RealtimeSessionState.FAILED):
            return
        interaction = session.active_interaction
        if interaction is not None:
            session.retire_interaction(interaction)
            await self._fail_interaction(
                session, interaction, "provider_protocol_error", message
            )
        await self._fail_session_locked(session, message)

    async def _fail_current_provider_session(
        self,
        session: RealtimeSession,
        provider_session: RealtimeProviderSession,
        provider_generation: int,
        message: str,
    ) -> None:
        async with self._coordinator.voice_transition(session.conversation_id):
            if not self._is_current_provider(
                session, provider_session, provider_generation
            ):
                return
            await self._fail_session_locked(session, message)

    async def _fail_session_locked(
        self, session: RealtimeSession, message: str
    ) -> None:
        if session.state in (RealtimeSessionState.CLOSED, RealtimeSessionState.FAILED):
            return
        interaction = session.active_interaction
        if interaction is not None:
            if interaction.durable_turn_id is not None:
                conversation, turn = await self._terminalize_turn(
                    session, interaction, "provider_session_failed", message
                )
                await self._emit(
                    session, ConversationTurnFailed(conversation, turn), terminal=True
                )
            session.retire_interaction(interaction)
            await self._release_interaction(session)
        session.state = RealtimeSessionState.FAILED
        await self._close_provider(session)
        await self._emit(
            session,
            ConversationRealtimeSessionFailed(session.id, message),
            terminal=True,
        )
        await self._end_events(session)
        async with self._sessions_gate:
            self._conversation_sessions.pop(session.conversation_id, None)

    async def _release_interaction(self, session: RealtimeSession) -> None:
        interaction = session.active_interaction
        if interaction is not None:
            await interaction.lease.release()
        session.active_interaction = None
        if session.state is RealtimeSessionState.ACTIVE:
            session.state = RealtimeSessionState.IDLE

    async def _close_provider(self, session: RealtimeSession) -> None:
        provider = session.provider_session
        task = session.consumer_task
        provider_generation = session.provider_generation
        provider_session = self._provider(session) if provider is not None else None
        if provider_session is not None and self._is_current_provider(
            session, provider_session, provider_generation
        ):
            session.provider_session = None
            session.consumer_task = None
        elif provider_session is None and session.consumer_task is task:
            session.consumer_task = None
        if (
            isinstance(task, asyncio.Task)
            and task is not asyncio.current_task()
            and not task.done()
        ):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if provider_session is not None:
            await provider_session.close()

    async def _emit(
        self,
        session: RealtimeSession,
        event: RealtimeConversationEvent,
        *,
        terminal: bool = False,
    ) -> None:
        await self._enqueue_event(session, event, terminal=terminal)

    async def _end_events(self, session: RealtimeSession) -> None:
        session.event_stream_closed = True
        session.event_delivery_shutdown_requested.set()
        await self._enqueue_event(session, _END, terminal=True)
        await self._cleanup_terminal_session_if_releasable(session)

    async def _enqueue_event(
        self,
        session: RealtimeSession,
        event: RealtimeConversationEvent | object,
        *,
        terminal: bool,
    ) -> None:
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        if session.event_delivery_stopped.is_set():
            if not terminal:
                raise _EventDeliveryStopped("event delivery stopped")
            return
        if terminal and not session.event_consumer_claimed:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(event)
            return
        try:
            queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass
        if terminal and session.event_delivery_close_requested.is_set():
            return

        put_task = asyncio.create_task(queue.put(event))
        signal = (
            session.event_delivery_stopped
            if terminal
            else session.event_delivery_shutdown_requested
        )
        signal_task = asyncio.create_task(signal.wait())
        done, _ = await asyncio.wait(
            (put_task, signal_task), return_when=asyncio.FIRST_COMPLETED
        )
        if put_task in done:
            signal_task.cancel()
            with suppress(asyncio.CancelledError):
                await signal_task
            return
        put_task.cancel()
        with suppress(asyncio.CancelledError):
            await put_task
        if terminal:
            return
        raise _EventDeliveryStopped("event delivery stopped")

    async def _cleanup_terminal_session_if_releasable(
        self, session: RealtimeSession
    ) -> None:
        if (
            session.state
            not in (RealtimeSessionState.CLOSED, RealtimeSessionState.FAILED)
            or not session.event_stream_closed
            or not session.event_delivery_stopped.is_set()
        ):
            return
        async with self._sessions_gate:
            if (
                self._sessions.get(session.id) is session
                and session.state
                in (RealtimeSessionState.CLOSED, RealtimeSessionState.FAILED)
                and session.event_stream_closed
                and session.event_delivery_stopped.is_set()
            ):
                self._sessions.pop(session.id, None)

    def _provider(self, session: RealtimeSession) -> RealtimeProviderSession:
        provider = session.provider_session
        if provider is None:
            raise InvalidRealtimeStateError("Realtime provider session is unavailable")
        return provider  # type: ignore[return-value]

    def _session(self, session_id: RealtimeSessionId) -> RealtimeSession:
        if not isinstance(session_id, UUID):
            raise ValueError("realtime_session_id must be a UUID")
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise RealtimeSessionNotFoundError(
                "Realtime session was not found"
            ) from error

    def _active(
        self, session_id: RealtimeSessionId
    ) -> tuple[RealtimeSession, RealtimeInteraction]:
        session = self._session(session_id)
        interaction = session.active_interaction
        if session.state is not RealtimeSessionState.ACTIVE or interaction is None:
            raise InvalidRealtimeStateError(
                "Realtime session has no active interaction"
            )
        return session, interaction

    def _time(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return timezone-aware datetime")
        return value.astimezone(UTC)
