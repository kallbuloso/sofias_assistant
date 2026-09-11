"""Integration evidence for the provider-neutral realtime conversation runtime."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.ai.contracts import (
    AudioEncoding,
    AudioFormat,
    AudioInputFrame,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ProviderError,
    ProviderErrorCategory,
    RealtimeInteractionId,
    RealtimeSessionId,
)
from sofias_assistant.ai.registry import (
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.conversation.coordination import (
    ConversationActivityConflictError,
    ConversationActivityCoordinator,
)
from sofias_assistant.conversation.events import (
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
)
from sofias_assistant.conversation.models import TurnInputModality, TurnStatus
from sofias_assistant.conversation.realtime_events import (
    ConversationRealtimeSessionFailed,
    RealtimeAssistantAudioChunk,
    RealtimeAssistantTranscriptPartial,
    RealtimeInteractionFailed,
    RealtimeSessionClosed,
    RealtimeUserTranscriptFinal,
)
from sofias_assistant.conversation.realtime_models import (
    REALTIME_ASSISTANT_TRANSCRIPT_MAX_BYTES,
    REALTIME_AUDIO_FRAME_MAX_BYTES,
    REALTIME_EVENT_QUEUE_MAX_ITEMS,
    REALTIME_TEXT_EVENT_MAX_BYTES,
    RETIRED_INTERACTION_LIMIT,
    InteractionGeneration,
)
from sofias_assistant.conversation.realtime_runtime import (
    InvalidRealtimeStateError,
    OpenRealtimeSessionCommand,
    RealtimeConversationRuntime,
    RealtimeSessionNotFoundError,
)
from sofias_assistant.conversation.runtime import (
    SendTextCommand,
    TextConversationRuntime,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.ai import FakeTextSuccess, ScriptedFakeProvider
from tests.support.realtime import (
    FakeAssistantAudioChunk,
    FakeAssistantTranscriptFinal,
    FakeAssistantTranscriptPartial,
    FakeRealtimeBarrier,
    FakeRealtimeCompleted,
    FakeRealtimeConsumerCancellation,
    FakeRealtimeFailed,
    FakeRealtimePause,
    FakeRealtimeScript,
    FakeRealtimeSessionFailed,
    FakeSignaledAssistantAudioChunk,
    FakeUnknownInteractionEvent,
    FakeUserTranscriptFinal,
    FakeWrongSessionEvent,
    ScriptedFakeRealtimeProvider,
)


def _format() -> AudioFormat:
    return AudioFormat(AudioEncoding.PCM16, 24_000, 1)


def _descriptor(name: str = "realtime") -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity("fake", name),
        capabilities=frozenset(
            {
                Capability.REALTIME,
                Capability.AUDIO_INPUT,
                Capability.AUDIO_OUTPUT,
                Capability.TEXT_GENERATION,
            }
        ),
        execution_location=ExecutionLocation.LOCAL,
        context_window=4096,
    )


async def _runtime(
    tmp_path: Path,
    realtime: ScriptedFakeRealtimeProvider,
    text: ScriptedFakeProvider | None = None,
) -> tuple[
    RealtimeConversationRuntime,
    TextConversationRuntime,
    Callable[[], SqlAlchemyUnitOfWork],
    AsyncEngine,
]:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await asyncio.to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    factory = create_session_factory(engine)
    text_provider = text or ScriptedFakeProvider()
    registry = ModelRegistry()
    registry.register(
        ModelRegistration(
            _descriptor(),
            ProviderBinding(realtime=realtime, text_generation=text_provider),
        )
    )
    router = CapabilityRouter(registry)
    builder = ContextBuilder(
        system_context=CoreSystemContext("System", True),
        max_recent_turns=1,
        max_estimated_input_tokens=1000,
    )
    coordinator = ConversationActivityCoordinator()

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory)

    return (
        RealtimeConversationRuntime(
            uow_factory=uow_factory,
            router=router,
            context_builder=builder,
            activity_coordinator=coordinator,
        ),
        TextConversationRuntime(
            uow_factory=uow_factory,
            router=router,
            context_builder=builder,
            activity_coordinator=coordinator,
        ),
        uow_factory,
        engine,
    )


async def _events(
    runtime: RealtimeConversationRuntime, session_id: object
) -> list[object]:
    result: list[object] = []
    async for event in runtime.events(session_id):  # type: ignore[arg-type]
        result.append(event)
        if isinstance(event, (ConversationTurnCompleted, ConversationTurnFailed)):
            return result
    return result


@pytest.mark.asyncio
async def test_voice_success_is_ephemeral_until_final_transcript_and_sequences_audio(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeAssistantAudioChunk(b"out", _format()),
                    FakeRealtimePause(release),
                    FakeUserTranscriptFinal("hello"),
                    FakeAssistantTranscriptFinal("hi"),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert session.provider_generation == 1
        stream = runtime.events(session.id)
        opened = await anext(stream)
        assert opened.realtime_session_id == session.id  # type: ignore[union-attr]
        await runtime.start_interaction(session.id)
        await runtime.send_audio(session.id, b"one")
        await runtime.send_audio(session.id, b"two")
        await runtime.commit_interaction(session.id)
        await anext(stream)  # interaction started
        output = await anext(stream)
        assert isinstance(output, RealtimeAssistantAudioChunk)
        assert fake.sessions()[0].frames()[0].sequence == 0
        assert fake.sessions()[0].frames()[1].sequence == 1
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
        release.set()
        events: list[object] = [opened, output]
        async for event in stream:
            events.append(event)
            if isinstance(event, ConversationTurnCompleted):
                break
        assert any(isinstance(event, ConversationTurnStarted) for event in events)
        assert isinstance(events[-1], ConversationTurnCompleted)
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert [
            (turn.input_modality, turn.status, turn.user_text, turn.assistant_text)
            for turn in turns
        ] == [(TurnInputModality.VOICE, TurnStatus.COMPLETED, "hello", "hi")]
        assert session.state.value == "IDLE"
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_audio_frame_bound_is_exact_and_rejection_preserves_state(
    tmp_path: Path,
) -> None:
    hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(hold),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)

        exact = b"a" * REALTIME_AUDIO_FRAME_MAX_BYTES
        await runtime.send_audio(session.id, exact)
        with pytest.raises(ValueError, match="realtime safety limit"):
            await runtime.send_audio(
                session.id, b"a" * (REALTIME_AUDIO_FRAME_MAX_BYTES + 1)
            )

        assert session.active_interaction is not None
        assert session.active_interaction.id == interaction_id
        assert session.active_interaction.next_input_sequence == 1
        assert fake.sessions()[0].frames() == (AudioInputFrame(0, exact),)

        await runtime.send_audio(session.id, b"after-rejection")
        assert session.active_interaction.next_input_sequence == 2
        assert fake.sessions()[0].frames()[-1] == AudioInputFrame(1, b"after-rejection")
        await runtime.close_session(session.id)
    finally:
        hold.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_audio_chunk_exact_bound_is_emitted_intact(
    tmp_path: Path,
) -> None:
    hold = asyncio.Event()
    exact = b"a" * REALTIME_AUDIO_FRAME_MAX_BYTES
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (FakeAssistantAudioChunk(exact, _format()), FakeRealtimePause(hold))
            ),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        received_audio: RealtimeAssistantAudioChunk | None = None
        while received_audio is None:
            event = await anext(stream)
            if isinstance(event, RealtimeAssistantAudioChunk):
                received_audio = event
        assert received_audio.audio == exact
        await runtime.close_session(session.id)
    finally:
        hold.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_audio_chunk_over_bound_fails_without_emitting_audio(
    tmp_path: Path,
) -> None:
    oversized = b"a" * (REALTIME_AUDIO_FRAME_MAX_BYTES + 1)
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeAssistantAudioChunk(oversized, _format()),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        received = [event async for event in stream]
        assert not any(
            isinstance(event, RealtimeAssistantAudioChunk) for event in received
        )
        assert any(
            isinstance(event, ConversationRealtimeSessionFailed) for event in received
        )
        assert session.state.value == "FAILED"
        assert oversized not in repr(received).encode()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_transcript_final_uses_utf8_byte_limit_before_turn_creation(
    tmp_path: Path,
) -> None:
    text = "é" * (REALTIME_TEXT_EVENT_MAX_BYTES // 2 + 1)
    assert len(text) < REALTIME_TEXT_EVENT_MAX_BYTES
    assert len(text.encode("utf-8")) > REALTIME_TEXT_EVENT_MAX_BYTES
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeUserTranscriptFinal(text),)),)
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        received = [event async for event in stream]
        assert not any(isinstance(event, ConversationTurnStarted) for event in received)
        assert not any(
            isinstance(event, RealtimeUserTranscriptFinal) for event in received
        )
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
        assert text not in repr(received)
        assert session.state.value == "FAILED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_assistant_partial_cumulative_limit_is_exact_then_fails_on_next_byte(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    fragment = "a" * REALTIME_TEXT_EVENT_MAX_BYTES
    assert REALTIME_ASSISTANT_TRANSCRIPT_MAX_BYTES % len(fragment.encode()) == 0
    fragments = REALTIME_ASSISTANT_TRANSCRIPT_MAX_BYTES // len(fragment.encode())
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                tuple(
                    FakeAssistantTranscriptPartial(fragment) for _ in range(fragments)
                )
                + (
                    FakeRealtimeBarrier(entered, release),
                    FakeAssistantTranscriptPartial("b"),
                )
            ),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        partials = 0
        while partials < fragments:
            event = await anext(stream)
            if isinstance(event, RealtimeAssistantTranscriptPartial):
                partials += 1
        assert session.active_interaction is not None
        assert (
            session.active_interaction.assistant_transcript_bytes
            == REALTIME_ASSISTANT_TRANSCRIPT_MAX_BYTES
        )
        await entered.wait()
        release.set()
        received = [event async for event in stream]
        assert not any(
            isinstance(event, RealtimeAssistantTranscriptPartial) and event.text == "b"
            for event in received
        )
        assert session.state.value == "FAILED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_oversized_assistant_final_fails_processing_turn_preserving_partial(
    tmp_path: Path,
) -> None:
    oversized = "f" * (REALTIME_TEXT_EVENT_MAX_BYTES + 1)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("user"),
                    FakeAssistantTranscriptPartial("partial"),
                    FakeAssistantTranscriptFinal(oversized),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        started = False
        partial = False
        while not (started and partial):
            event = await anext(stream)
            started = started or isinstance(event, ConversationTurnStarted)
            partial = partial or (
                isinstance(event, RealtimeAssistantTranscriptPartial)
                and event.text == "partial"
            )
        received = [event async for event in stream]
        assert not any(
            isinstance(event, ConversationTurnCompleted) for event in received
        )
        failed = [
            event for event in received if isinstance(event, ConversationTurnFailed)
        ]
        assert len(failed) == 1
        assert failed[0].turn.error_category == "provider_protocol_error"
        assert failed[0].turn.assistant_text == "partial"
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
        assert turns[0].assistant_text == "partial"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_oversized_response_failure_message_becomes_protocol_failure(
    tmp_path: Path,
) -> None:
    marker = "SDK_SECRET_INTERNAL_"
    error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        marker * (REALTIME_TEXT_EVENT_MAX_BYTES // len(marker) + 1),
        False,
    )
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (FakeUserTranscriptFinal("user"), FakeRealtimeFailed(error))
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        received = [event async for event in stream]
        failed = [
            event for event in received if isinstance(event, ConversationTurnFailed)
        ]
        assert len(failed) == 1
        assert failed[0].turn.error_category == "provider_protocol_error"
        assert marker not in repr(received)
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert marker not in repr(turns[0])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_oversized_session_failure_message_is_redacted_as_protocol_failure(
    tmp_path: Path,
) -> None:
    marker = "SDK_SECRET_INTERNAL_"
    error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        marker * (REALTIME_TEXT_EVENT_MAX_BYTES // len(marker) + 1),
        False,
    )
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimeSessionFailed(error),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        received = [event async for event in stream]
        failures = [
            event
            for event in received
            if isinstance(event, ConversationRealtimeSessionFailed)
        ]
        assert len(failures) == 1
        assert marker not in repr(received)
        assert session.state.value == "FAILED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_realtime_event_queue_uses_bounded_core_capacity(
    tmp_path: Path,
) -> None:
    hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(hold),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        assert queue.maxsize == REALTIME_EVENT_QUEUE_MAX_ITEMS
        while not queue.full():
            queue.put_nowait(object())
        assert queue.qsize() == REALTIME_EVENT_QUEUE_MAX_ITEMS
        with pytest.raises(asyncio.QueueFull):
            queue.put_nowait(object())
        while not queue.empty():
            queue.get_nowait()
        await runtime.close_session(session.id)
    finally:
        hold.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_terminal_event_waits_for_capacity_and_end_marker_is_fifo(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        while not queue.full():
            queue.put_nowait(object())

        terminal = ConversationRealtimeSessionFailed(session.id, "terminal delivery")
        terminal_task = asyncio.create_task(
            runtime._emit(session, terminal, terminal=True)
        )
        assert terminal_task.done() is False
        queue.get_nowait()
        await terminal_task
        end_task = asyncio.create_task(runtime._end_events(session))
        received = [event async for event in stream]
        await end_task
        assert terminal in received
        assert received.index(terminal) == len(received) - 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_failure_preserves_terminal_order_under_saturation(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                    FakeRealtimePause(release),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)
        release.set()
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        while not queue.full():
            queue.put_nowait(object())
        await fake.sessions()[0].emit_session_failure(error)
        received = [event async for event in stream]
        terminals = [
            event
            for event in received
            if isinstance(
                event, (ConversationTurnFailed, ConversationRealtimeSessionFailed)
            )
        ]
        assert [type(event) for event in terminals] == [
            ConversationTurnFailed,
            ConversationRealtimeSessionFailed,
        ]
        assert session.state.value == "FAILED"
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_close_breaks_blocked_event_delivery_without_queue_full_heuristic(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        while not queue.full():
            queue.put_nowait(object())
        blocked = asyncio.create_task(
            runtime._emit(session, RealtimeSessionClosed(session.id))
        )
        close_task = asyncio.create_task(runtime.close_session(session.id))
        await session.event_delivery_shutdown_requested.wait()
        received = [event async for event in stream]
        await close_task
        await blocked
        assert any(isinstance(event, RealtimeSessionClosed) for event in received)
        assert session.state.value == "CLOSED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_consumer_abandonment_releases_blocked_producer(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        while not queue.full():
            queue.put_nowait(object())
        blocked = asyncio.create_task(
            runtime._emit(session, RealtimeSessionClosed(session.id))
        )
        await stream.aclose()  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="delivery"):
            await blocked
        await runtime.close_session(session.id)
        assert session.state.value == "CLOSED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_close_all_completes_with_saturated_event_queue(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        queue = session.event_queue
        assert isinstance(queue, asyncio.Queue)
        while not queue.full():
            queue.put_nowait(object())
        close_all_task = asyncio.create_task(runtime.close_all())
        received = [event async for event in stream]
        await close_all_task
        assert any(isinstance(event, RealtimeSessionClosed) for event in received)
        assert session.state.value == "CLOSED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_session_is_removed_after_event_stream_finishes(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await fake.sessions()[0].end_event_stream()
        await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert session.id not in runtime._sessions
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_closed_session_is_removed_after_event_stream_finishes(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        close_task = asyncio.create_task(runtime.close_session(session.id))
        received = [event async for event in stream]
        await close_task
        assert any(isinstance(event, RealtimeSessionClosed) for event in received)
        assert session.id not in runtime._sessions
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_abandoned_consumer_session_is_removed_after_terminalization(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await stream.aclose()  # type: ignore[attr-defined]
        await runtime.close_session(session.id)
        assert session.id not in runtime._sessions
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_terminal_sessions_do_not_accumulate_registry_state(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        for _ in range(3):
            session = await runtime.open_session(
                OpenRealtimeSessionCommand(
                    conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
                )
            )
            stream = runtime.events(session.id)
            await anext(stream)
            close_task = asyncio.create_task(runtime.close_session(session.id))
            _ = [event async for event in stream]
            await close_task
            assert len(runtime._sessions) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failures_do_not_leave_a_voice_lease_or_processing_turn(
    tmp_path: Path,
) -> None:
    error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE, "unavailable", False
    )
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimeFailed(error),)),)
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert session.provider_generation == 1
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        failure = await anext(stream)
        assert failure.safe_message == "unavailable"  # type: ignore[union-attr]
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
        assert session.provider_context_stale is True
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_initial_provider_install_has_generation_one_and_one_consumer(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (FakeRealtimeBarrier(entered, release),),
            ),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert session.provider_generation == 1
        assert session.provider_session is fake.sessions()[0]

        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await entered.wait()

        assert fake.sessions()[0].events_consumers == 1
        await runtime.cancel_interaction(session.id, interaction_id)
        await runtime.close_session(session.id)
        release.set()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ("event", "end", "exception"))
async def test_detached_old_provider_consumer_cannot_affect_reseeded_session(
    tmp_path: Path, outcome: str
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "old lost", False)
    cancellation = FakeRealtimeConsumerCancellation(
        entered,
        release,
        event=FakeRealtimeSessionFailed(error) if outcome == "event" else None,
        error_message="old stream failed" if outcome == "exception" else None,
    )
    new_hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("old input"),
                    FakeAssistantTranscriptFinal("old answer"),
                    FakeRealtimeCompleted(),
                )
            ),
            FakeRealtimeScript((FakeRealtimePause(new_hold),)),
        ),
        consumer_cancellations=(cancellation,),
    )
    text = ScriptedFakeProvider(text_scripts=(FakeTextSuccess("text answer"),))
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake, text)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        while not isinstance(await anext(stream), ConversationTurnCompleted):
            pass
        await text_runtime.send_text(
            SendTextCommand(conversation.id, "text", DataLocality.LOCAL_ONLY, True)
        )

        replacement = asyncio.create_task(runtime.start_interaction(session.id))
        await entered.wait()
        assert session.provider_session is None
        assert session.consumer_task is None
        assert session.provider_generation == 1

        release.set()
        new_id = await replacement
        started = await anext(stream)
        assert started.realtime_interaction_id == new_id  # type: ignore[union-attr]
        assert session.provider_generation == 2
        assert session.provider_session is fake.sessions()[1]
        assert session.event_stream_closed is False
        assert session.state.value == "ACTIVE"
        assert fake.sessions()[0].close_calls == 1
        assert [
            provider_session.events_consumers for provider_session in fake.sessions()
        ] == [
            1,
            1,
        ]

        await runtime.cancel_interaction(session.id, new_id)
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_current_provider_stream_end_remains_authoritative(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)

        await fake.sessions()[0].end_event_stream()
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        failures = [
            event
            for event in received
            if isinstance(event, ConversationRealtimeSessionFailed)
        ]
        assert len(failures) == 1
        assert (
            failures[0].safe_message == "Realtime provider session ended unexpectedly"
        )
        assert fake.sessions()[0].close_calls == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failure_after_voice_materialization_marks_turn_failed(
    tmp_path: Path,
) -> None:
    error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE, "unavailable", False
    )
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (FakeUserTranscriptFinal("hello"), FakeRealtimeFailed(error))
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        await anext(stream)
        started = await anext(stream)
        assert isinstance(started, ConversationTurnStarted)
        failed = await anext(stream)
        assert isinstance(failed, ConversationTurnFailed)
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
        assert session.provider_context_stale is True
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_loss_fails_processing_turn_and_allows_a_new_core_session(
    tmp_path: Path,
) -> None:
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (FakeUserTranscriptFinal("hello"), FakeRealtimeSessionFailed(error))
            ),
            FakeRealtimeScript(()),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        received: list[object] = []
        async for event in stream:
            received.append(event)
        assert any(isinstance(event, ConversationTurnFailed) for event in received)
        assert isinstance(received[-1], ConversationRealtimeSessionFailed)
        assert session.state.value == "FAILED"
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
        replacement = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert replacement.id != session.id
        await runtime.close_session(replacement.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_idle_current_session_failure_is_terminal_and_releases_conversation(
    tmp_path: Path,
) -> None:
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider()
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)

        await fake.sessions()[0].emit_session_failure(error)
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert fake.sessions()[0].close_calls == 1
        assert [
            event
            for event in received
            if isinstance(event, ConversationRealtimeSessionFailed)
        ] and len(
            [
                event
                for event in received
                if isinstance(event, ConversationRealtimeSessionFailed)
            ]
        ) == 1
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []

        replacement = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert replacement.id != session.id
        await runtime.close_session(replacement.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pre_transcript_session_loss_retires_without_creating_turn(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeSessionFailed(error),
                    FakeUserTranscriptFinal("late transcript"),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await entered.wait()

        release.set()
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert session.active_interaction is None
        assert (
            session.classify_interaction(interaction_id)
            is InteractionGeneration.RETIRED_KNOWN
        )
        assert fake.sessions()[0].interrupts() == ()
        assert fake.sessions()[0].close_calls == 1
        assert not any(
            isinstance(
                event,
                (
                    RealtimeInteractionFailed,
                    ConversationTurnFailed,
                    ConversationTurnInterrupted,
                ),
            )
            for event in received
        )
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_transcript_session_loss_fails_once_and_preserves_partial(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeSessionFailed(error),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        started = await anext(stream)
        assert isinstance(started, ConversationTurnStarted)
        await anext(stream)
        await entered.wait()

        async with factory() as uow:
            processing = await uow.turns.list_for_conversation(conversation.id)
        assert processing[0].status is TurnStatus.PROCESSING

        release.set()
        received = [event async for event in stream]

        assert [type(event) for event in received] == [
            ConversationTurnFailed,
            ConversationRealtimeSessionFailed,
        ]
        assert session.state.value == "FAILED"
        assert session.active_interaction is None
        assert (
            session.classify_interaction(interaction_id)
            is InteractionGeneration.RETIRED_KNOWN
        )
        assert fake.sessions()[0].interrupts() == ()
        assert fake.sessions()[0].close_calls == 1
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
        assert turns[0].assistant_text == "partial"
        assert turns[0].error_category == "provider_session_failed"
        assert turns[0].provider_id == "fake"
        assert turns[0].model_id == "realtime"
        assert turns[0].finished_at is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_close_wins_over_concurrent_session_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    close_terminalized = asyncio.Event()
    release_close = asyncio.Event()
    failure_attempted = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)

        terminalize_turn = runtime._terminalize_turn

        async def hold_close_terminalization(*args: object, **kwargs: object) -> object:
            if kwargs.get("interrupted") is True:
                close_terminalized.set()
                await release_close.wait()
            return await terminalize_turn(*args, **kwargs)  # type: ignore[arg-type]

        fail_current_provider_session = runtime._fail_current_provider_session

        async def signal_failure_attempt(*args: object, **kwargs: object) -> None:
            failure_attempted.set()
            await fail_current_provider_session(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(runtime, "_terminalize_turn", hold_close_terminalization)
        monkeypatch.setattr(
            runtime, "_fail_current_provider_session", signal_failure_attempt
        )

        close_task = asyncio.create_task(runtime.close_session(session.id))
        await close_terminalized.wait()
        await fake.sessions()[0].emit_session_failure(error)
        await failure_attempted.wait()
        release_close.set()
        await close_task
        received = [event async for event in stream]

        assert session.state.value == "CLOSED"
        assert session.synced_context_revision == 0
        assert fake.sessions()[0].close_calls == 1
        assert (
            sum(isinstance(event, ConversationTurnInterrupted) for event in received)
            == 1
        )
        assert sum(isinstance(event, RealtimeSessionClosed) for event in received) == 1
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 0
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 0
        )
        assert (
            sum(isinstance(event, ConversationTurnCompleted) for event in received) == 0
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "partial"
    finally:
        release_close.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_loss_wins_over_concurrent_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure_terminalized = asyncio.Event()
    release_failure = asyncio.Event()
    close_attempted = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)

        terminalize_turn = runtime._terminalize_turn

        async def hold_failure_terminalization(
            *args: object, **kwargs: object
        ) -> object:
            if kwargs.get("interrupted", False) is False:
                failure_terminalized.set()
                await release_failure.wait()
            return await terminalize_turn(*args, **kwargs)  # type: ignore[arg-type]

        close_session = runtime.close_session

        async def signal_close_attempt(realtime_session_id: RealtimeSessionId) -> None:
            close_attempted.set()
            await close_session(realtime_session_id)

        monkeypatch.setattr(runtime, "_terminalize_turn", hold_failure_terminalization)
        monkeypatch.setattr(runtime, "close_session", signal_close_attempt)

        await fake.sessions()[0].emit_session_failure(error)
        await failure_terminalized.wait()
        close_task = asyncio.create_task(runtime.close_session(session.id))
        await close_attempted.wait()
        release_failure.set()
        await close_task
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert session.synced_context_revision == 0
        assert fake.sessions()[0].close_calls == 1
        assert fake.sessions()[0].interrupts() == ()
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 1
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        assert (
            sum(isinstance(event, ConversationTurnInterrupted) for event in received)
            == 0
        )
        assert sum(isinstance(event, RealtimeSessionClosed) for event in received) == 0
        assert (
            sum(isinstance(event, ConversationTurnCompleted) for event in received) == 0
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.FAILED
    finally:
        release_failure.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_close_pre_transcript_creates_no_turn(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(asyncio.Event()),)),)
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)

        await runtime.close_session(session.id)
        received = [event async for event in stream]

        assert session.state.value == "CLOSED"
        assert sum(isinstance(event, RealtimeSessionClosed) for event in received) == 1
        assert (
            sum(isinstance(event, ConversationTurnInterrupted) for event in received)
            == 0
        )
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_completion_wins_over_later_session_loss_without_rewriting_turn(
    tmp_path: Path,
) -> None:
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptFinal("final answer"),
                    FakeRealtimeCompleted(),
                )
            ),
            FakeRealtimeScript(()),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        observed: list[object] = []
        while not any(
            isinstance(event, ConversationTurnCompleted) for event in observed
        ):
            observed.append(await anext(stream))

        assert session.active_interaction is None
        assert session.synced_context_revision == 1
        assert (
            sum(isinstance(event, ConversationTurnCompleted) for event in observed) == 1
        )

        await fake.sessions()[0].emit_session_failure(error)
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert session.synced_context_revision == 1
        assert fake.sessions()[0].interrupts() == ()
        assert fake.sessions()[0].close_calls == 1
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 0
        assert (
            sum(isinstance(event, ConversationTurnInterrupted) for event in received)
            == 0
        )
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.COMPLETED
        assert turns[0].assistant_text == "final answer"

        replacement = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert replacement.id != session.id
        assert interaction_id not in fake.sessions()[0].interrupts()
        await runtime.close_session(replacement.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_loss_wins_over_completion_and_late_completion_is_discarded(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    after_late_completion = asyncio.Event()
    release_after_late_completion = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptFinal("final answer"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeSessionFailed(error),
                    FakeRealtimeCompleted(),
                    FakeRealtimeBarrier(
                        after_late_completion, release_after_late_completion
                    ),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)
        await entered.wait()

        release.set()
        received = [event async for event in stream]
        await after_late_completion.wait()
        release_after_late_completion.set()

        assert session.state.value == "FAILED"
        assert session.synced_context_revision == 0
        assert session.active_interaction is None
        assert (
            session.classify_interaction(interaction_id)
            is InteractionGeneration.RETIRED_KNOWN
        )
        assert fake.sessions()[0].interrupts() == ()
        assert fake.sessions()[0].close_calls == 1
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 1
        assert (
            sum(isinstance(event, ConversationTurnCompleted) for event in received) == 0
        )
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.FAILED
    finally:
        release_after_late_completion.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupt_wins_over_later_session_loss_without_rewriting_turn(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeSessionFailed(error),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)
        await entered.wait()

        await runtime.interrupt_interaction(session.id, interaction_id)
        interrupted = await anext(stream)
        assert isinstance(interrupted, ConversationTurnInterrupted)
        release.set()
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert session.synced_context_revision == 0
        assert fake.sessions()[0].interrupts() == (interaction_id,)
        assert fake.sessions()[0].close_calls == 1
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 0
        assert (
            sum(isinstance(event, ConversationTurnCompleted) for event in received) == 0
        )
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "partial"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_loss_wins_over_interrupt_and_rejects_late_interrupt(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeSessionFailed(error),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)
        await entered.wait()

        release.set()
        received = [event async for event in stream]
        with pytest.raises((InvalidRealtimeStateError, RealtimeSessionNotFoundError)):
            await runtime.interrupt_interaction(session.id, interaction_id)

        assert session.state.value == "FAILED"
        assert session.synced_context_revision == 0
        assert fake.sessions()[0].interrupts() == ()
        assert fake.sessions()[0].close_calls == 1
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 1
        assert (
            sum(isinstance(event, ConversationTurnInterrupted) for event in received)
            == 0
        )
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.FAILED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_loss_wins_over_automatic_barge_in(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeSessionFailed(error),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        old_interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await entered.wait()

        release.set()
        received = [event async for event in stream]
        with pytest.raises((InvalidRealtimeStateError, RealtimeSessionNotFoundError)):
            await runtime.start_interaction(session.id)

        assert session.state.value == "FAILED"
        assert session.active_interaction is None
        assert fake.sessions()[0].started_interactions() == (old_interaction_id,)
        assert fake.sessions()[0].interrupts() == ()
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 1
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_current_stream_exception_uses_safe_session_failure_semantics(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeAssistantTranscriptPartial("partial"),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)
        await anext(stream)
        await anext(stream)

        await fake.sessions()[0].fail_event_stream("SDK SECRET INTERNAL")
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert isinstance(received[0], ConversationTurnFailed)
        assert isinstance(received[1], ConversationRealtimeSessionFailed)
        assert all(
            "SDK SECRET INTERNAL" not in event.safe_message
            for event in received
            if isinstance(event, ConversationRealtimeSessionFailed)
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
        assert turns[0].error_category == "provider_session_failed"
        assert "SDK SECRET INTERNAL" not in (turns[0].error_message or "")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_current_session_failures_terminalize_once(
    tmp_path: Path,
) -> None:
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "lost", False)
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeRealtimeSessionFailed(error),
                    FakeRealtimeSessionFailed(error),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        received = [event async for event in stream]

        assert session.state.value == "FAILED"
        assert sum(isinstance(event, ConversationTurnFailed) for event in received) == 1
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 1
        )
        assert fake.sessions()[0].close_calls == 1
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.FAILED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_closed_session_ignores_late_current_provider_failure(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    error = ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "late", False)
    fake = ScriptedFakeRealtimeProvider(
        consumer_cancellations=(
            FakeRealtimeConsumerCancellation(
                entered,
                release,
                event=FakeRealtimeSessionFailed(error),
            ),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)

        close_task = asyncio.create_task(runtime.close_session(session.id))
        await entered.wait()
        release.set()
        await close_task
        received = [event async for event in stream]

        assert session.state.value == "CLOSED"
        assert (
            sum(
                isinstance(event, ConversationRealtimeSessionFailed)
                for event in received
            )
            == 0
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_voice_conflicts_with_text_and_idle_text_causes_reseed(
    tmp_path: Path,
) -> None:
    pause = asyncio.Event()
    realtime = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeRealtimePause(pause),
                    FakeUserTranscriptFinal("voice one"),
                    FakeAssistantTranscriptFinal("one"),
                    FakeRealtimeCompleted(),
                )
            ),
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice two"),
                    FakeAssistantTranscriptFinal("two"),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    text = ScriptedFakeProvider(text_scripts=(FakeTextSuccess("text answer"),))
    runtime, text_runtime, _, engine = await _runtime(tmp_path, realtime, text)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        assert session.provider_generation == 1
        stream = runtime.events(session.id)
        await runtime.start_interaction(session.id)
        with pytest.raises(ConversationActivityConflictError):
            await text_runtime.send_text(
                SendTextCommand(
                    conversation.id, "blocked", DataLocality.LOCAL_ONLY, True
                )
            )
        pause.set()
        async for event in stream:
            if isinstance(event, ConversationTurnCompleted):
                break
        await text_runtime.send_text(
            SendTextCommand(conversation.id, "text", DataLocality.LOCAL_ONLY, True)
        )
        await runtime.start_interaction(session.id)
        assert session.provider_generation == 2
        await anext(stream)
        await anext(stream)
        assert len(realtime.opens()) == 2
        assert (
            realtime.opens()[0].request.realtime_session_id
            == realtime.opens()[1].request.realtime_session_id
            == session.id
        )
        messages = realtime.opens()[1].request.context_seed.messages
        assert [(message.role.value, message.text) for message in messages] == [
            ("system", "System"),
            ("user", "text"),
            ("assistant", "text answer"),
        ]
        assert [
            provider_session.events_consumers
            for provider_session in realtime.sessions()
        ] == [
            1,
            1,
        ]
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_close_completes_when_the_abandoned_application_stream_is_full(
    tmp_path: Path,
) -> None:
    blocked = asyncio.Event()
    audio_items = tuple(FakeAssistantAudioChunk(b"a", _format()) for _ in range(127))
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                audio_items
                + (FakeSignaledAssistantAudioChunk(blocked, b"b", _format()),)
            ),
        )
    )
    text = ScriptedFakeProvider(text_scripts=(FakeTextSuccess("unblocked"),))
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake, text)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)  # Claim, then abandon, the only application consumer.
        await runtime.start_interaction(session.id)
        await blocked.wait()

        await runtime.close_session(session.id)

        assert session.state.value == "CLOSED"
        assert fake.sessions()[0].close_calls == 1
        assert fake.sessions()[0].events_consumers == 1
        result = await text_runtime.send_text(
            SendTextCommand(
                conversation.id, "after close", DataLocality.LOCAL_ONLY, True
            )
        )
        assert result.turn.status is TurnStatus.COMPLETED
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupt_committed_input_before_transcript_releases_interaction(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)

        await runtime.interrupt_interaction(session.id, interaction_id)

        assert fake.sessions()[0].interrupts() == (interaction_id,)
        assert session.active_interaction is None
        assert session.state is session.state.IDLE
        assert session.provider_context_stale is True
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupt_after_transcript_interrupts_processing_turn_once(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("hello"),
                    FakeAssistantTranscriptPartial("partial answer"),
                    FakeRealtimePause(release),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)  # user transcript final
        started = await anext(stream)
        assert isinstance(started, ConversationTurnStarted)
        await anext(stream)  # assistant transcript partial

        await runtime.interrupt_interaction(session.id, interaction_id)
        interrupted = await anext(stream)

        assert isinstance(interrupted, ConversationTurnInterrupted)
        assert interrupted.turn.status is TurnStatus.INTERRUPTED
        assert interrupted.turn.assistant_text == "partial answer"
        assert fake.sessions()[0].interrupts() == (interaction_id,)
        assert session.active_interaction is None
        assert session.state is session.state.IDLE
        assert session.provider_context_stale is True
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "partial answer"
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupt_before_commit_is_rejected_without_provider_call(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        with pytest.raises(InvalidRealtimeStateError):
            await runtime.interrupt_interaction(session.id, interaction_id)
        assert fake.sessions()[0].interrupts() == ()
        assert session.active_interaction is not None
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_before_commit_releases_interaction_without_turn(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)

        await runtime.cancel_interaction(session.id, interaction_id)

        assert fake.sessions()[0].interrupts() == (interaction_id,)
        assert session.active_interaction is None
        assert session.state is session.state.IDLE
        assert session.provider_context_stale is False
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_after_commit_is_rejected_without_interrupt(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        with pytest.raises(InvalidRealtimeStateError):
            await runtime.cancel_interaction(session.id, interaction_id)
        assert fake.sessions()[0].interrupts() == ()
        assert session.active_interaction is not None
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["interrupt", "cancel"])
async def test_wrong_interaction_correlation_is_rejected(
    tmp_path: Path, operation: str
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        wrong_id = RealtimeInteractionId(uuid4())
        with pytest.raises(InvalidRealtimeStateError):
            if operation == "interrupt":
                await runtime.interrupt_interaction(session.id, wrong_id)
            else:
                await runtime.cancel_interaction(session.id, wrong_id)
        assert fake.sessions()[0].interrupts() == ()
        assert session.active_interaction is not None
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["interrupt", "cancel"])
async def test_unknown_session_correlation_is_rejected(
    tmp_path: Path, operation: str
) -> None:
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(asyncio.Event()),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        with pytest.raises(RealtimeSessionNotFoundError):
            unknown_session_id = RealtimeSessionId(uuid4())
            if operation == "interrupt":
                await runtime.interrupt_interaction(unknown_session_id, interaction_id)
            else:
                await runtime.cancel_interaction(unknown_session_id, interaction_id)
        assert fake.sessions()[0].interrupts() == ()
        assert session.active_interaction is not None
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_interrupt_is_rejected_without_duplicate_provider_call(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await runtime.interrupt_interaction(session.id, interaction_id)
        with pytest.raises(InvalidRealtimeStateError):
            await runtime.interrupt_interaction(session.id, interaction_id)
        assert fake.sessions()[0].interrupts() == (interaction_id,)
        assert list(session.retired_interactions) == [(interaction_id, 1)]
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_cancel_is_rejected_without_duplicate_provider_call(
    tmp_path: Path,
) -> None:
    release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(release),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.cancel_interaction(session.id, interaction_id)
        with pytest.raises(InvalidRealtimeStateError):
            await runtime.cancel_interaction(session.id, interaction_id)
        assert fake.sessions()[0].interrupts() == (interaction_id,)
        assert list(session.retired_interactions) == [(interaction_id, 1)]
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_interaction_can_start_after_interrupt_and_cancel(
    tmp_path: Path,
) -> None:
    first_release = asyncio.Event()
    second_release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript((FakeRealtimePause(first_release),)),
            FakeRealtimeScript((FakeRealtimePause(second_release),)),
            FakeRealtimeScript((FakeRealtimePause(asyncio.Event()),)),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        first_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await runtime.interrupt_interaction(session.id, first_id)
        second_id = await runtime.start_interaction(session.id)
        await anext(stream)
        assert second_id != first_id
        await runtime.cancel_interaction(session.id, second_id)
        assert session.state is session.state.IDLE
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interaction_epochs_are_monotonic_and_classification_is_explicit(
    tmp_path: Path,
) -> None:
    pause = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        tuple(FakeRealtimeScript((FakeRealtimePause(pause),)) for _ in range(3))
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)

        interaction_a = await runtime.start_interaction(session.id)
        await anext(stream)
        assert session.active_interaction is not None
        assert session.active_interaction.response_epoch == 1
        await runtime.cancel_interaction(session.id, interaction_a)
        assert (
            session.classify_interaction(interaction_a)
            is InteractionGeneration.RETIRED_KNOWN
        )

        interaction_b = await runtime.start_interaction(session.id)
        await anext(stream)
        assert session.active_interaction is not None
        assert session.active_interaction.response_epoch == 2
        assert (
            session.classify_interaction(interaction_b) is InteractionGeneration.ACTIVE
        )
        assert (
            session.classify_interaction(RealtimeInteractionId(uuid4()))
            is InteractionGeneration.UNKNOWN
        )
        await runtime.cancel_interaction(session.id, interaction_b)

        interaction_c = await runtime.start_interaction(session.id)
        await anext(stream)
        assert session.active_interaction is not None
        assert session.active_interaction.response_epoch == 3
        await runtime.cancel_interaction(session.id, interaction_c)
        assert session.response_epoch == 3
        assert [epoch for _, epoch in session.retired_interactions] == [1, 2, 3]
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_retired_interactions_are_bounded_and_oldest_ids_are_evicted(
    tmp_path: Path,
) -> None:
    pause = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        tuple(
            FakeRealtimeScript((FakeRealtimePause(pause),))
            for _ in range(RETIRED_INTERACTION_LIMIT + 1)
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_ids: list[RealtimeInteractionId] = []
        for _ in range(RETIRED_INTERACTION_LIMIT + 1):
            interaction_id = await runtime.start_interaction(session.id)
            interaction_ids.append(interaction_id)
            await anext(stream)
            await runtime.cancel_interaction(session.id, interaction_id)

        assert len(session.retired_interactions) == RETIRED_INTERACTION_LIMIT
        assert (
            session.classify_interaction(interaction_ids[0])
            is InteractionGeneration.UNKNOWN
        )
        for interaction_id in interaction_ids[1:]:
            assert (
                session.classify_interaction(interaction_id)
                is InteractionGeneration.RETIRED_KNOWN
            )
        assert len(session.retired_interaction_ids) == RETIRED_INTERACTION_LIMIT
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupt_wins_and_late_completion_is_discarded_before_new_interaction(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    after_late_event = asyncio.Event()
    release_after_late_event = asyncio.Event()
    hold_new = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("old input"),
                    FakeAssistantTranscriptFinal("old answer"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeCompleted(),
                    FakeRealtimeBarrier(after_late_event, release_after_late_event),
                )
            ),
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("new input"),
                    FakeAssistantTranscriptFinal("new answer"),
                    FakeRealtimeCompleted(),
                    FakeRealtimePause(hold_new),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        old_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)  # old user transcript
        await anext(stream)  # old TurnStarted
        await anext(stream)  # old assistant transcript
        await entered.wait()

        await runtime.interrupt_interaction(session.id, old_id)
        interrupted = await anext(stream)
        assert isinstance(interrupted, ConversationTurnInterrupted)
        assert interrupted.turn.status is TurnStatus.INTERRUPTED
        assert fake.sessions()[0].interrupts() == (old_id,)
        assert session.synced_context_revision == 0

        release.set()
        await after_late_event.wait()
        assert session.state.value == "IDLE"
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.INTERRUPTED

        release_after_late_event.set()
        new_id = await runtime.start_interaction(session.id)
        started = await anext(stream)
        assert started.realtime_interaction_id == new_id  # type: ignore[union-attr]
        completed = False
        while not completed:
            event = await anext(stream)
            completed = isinstance(event, ConversationTurnCompleted)
        assert completed
    finally:
        await runtime.close_session(session.id)
        hold_new.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_completion_wins_and_later_interrupt_cannot_rewrite_turn(
    tmp_path: Path,
) -> None:
    hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("input"),
                    FakeAssistantTranscriptFinal("answer"),
                    FakeRealtimeCompleted(),
                    FakeRealtimePause(hold),
                )
            ),
            FakeRealtimeScript(()),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        completed = False
        while not completed:
            completed = isinstance(await anext(stream), ConversationTurnCompleted)

        assert session.synced_context_revision == 1
        with pytest.raises(InvalidRealtimeStateError):
            await runtime.interrupt_interaction(session.id, interaction_id)
        assert fake.sessions()[0].interrupts() == ()
        replacement_id = await runtime.start_interaction(session.id)
        replacement_started = await anext(stream)
        assert replacement_started.realtime_interaction_id == replacement_id  # type: ignore[union-attr]
        assert replacement_id != interaction_id
        await runtime.cancel_interaction(session.id, replacement_id)
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.COMPLETED
        await runtime.close_session(session.id)
        hold.set()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_late_audio_and_transcripts_from_retired_interaction_are_dropped(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    after_late_events = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("input"),
                    FakeAssistantTranscriptPartial("before "),
                    FakeRealtimeBarrier(entered, release),
                    FakeUserTranscriptFinal("late user"),
                    FakeAssistantAudioChunk(b"late-audio", _format()),
                    FakeAssistantTranscriptPartial("late partial"),
                    FakeAssistantTranscriptFinal("late final"),
                    FakeRealtimeCompleted(),
                    FakeRealtimeBarrier(after_late_events, asyncio.Event()),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)  # user transcript
        await anext(stream)  # TurnStarted
        await anext(stream)  # assistant partial before interruption
        await entered.wait()

        await runtime.interrupt_interaction(session.id, interaction_id)
        interrupted = await anext(stream)
        assert isinstance(interrupted, ConversationTurnInterrupted)
        release.set()
        await after_late_events.wait()

        assert session.state.value == "IDLE"
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "before "
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_late_response_failure_after_interrupt_is_dropped(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    after_failure = asyncio.Event()
    error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE, "late failure", False
    )
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("input"),
                    FakeAssistantTranscriptFinal("answer"),
                    FakeRealtimeBarrier(entered, release),
                    FakeRealtimeFailed(error),
                    FakeRealtimeBarrier(after_failure, asyncio.Event()),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        interaction_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)  # user transcript
        await anext(stream)  # TurnStarted
        await anext(stream)  # assistant transcript
        await entered.wait()

        await runtime.interrupt_interaction(session.id, interaction_id)
        interrupted = await anext(stream)
        assert isinstance(interrupted, ConversationTurnInterrupted)
        release.set()
        await after_failure.wait()

        assert session.state.value == "IDLE"
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.INTERRUPTED
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_interaction_event_remains_protocol_failure(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("voice input"),
                    FakeUnknownInteractionEvent("unknown"),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        received = [event async for event in stream]
        assert session.state.value == "FAILED"
        assert any(
            isinstance(event, ConversationRealtimeSessionFailed) for event in received
        )
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert turns[0].status is TurnStatus.FAILED
        assert turns[0].error_category == "provider_protocol_error"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interaction_event_with_wrong_session_id_remains_protocol_failure(
    tmp_path: Path,
) -> None:
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeWrongSessionEvent("wrong session"),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        received = [event async for event in stream]
        assert session.state.value == "FAILED"
        assert any(
            isinstance(event, ConversationRealtimeSessionFailed) for event in received
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_start_while_uncommitted_interaction_is_rejected_without_interrupt(
    tmp_path: Path,
) -> None:
    hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimePause(hold),)),)
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        old_id = await runtime.start_interaction(session.id)
        await anext(stream)
        with pytest.raises(InvalidRealtimeStateError):
            await runtime.start_interaction(session.id)
        assert fake.sessions()[0].interrupts() == ()
        assert session.active_interaction is not None
        assert session.active_interaction.id == old_id
        assert session.state.value == "ACTIVE"
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pre_transcript_start_automatically_replaces_committed_interaction(
    tmp_path: Path,
) -> None:
    old_hold = asyncio.Event()
    new_hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript((FakeRealtimePause(old_hold),)),
            FakeRealtimeScript((FakeRealtimePause(new_hold),)),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        old_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)

        new_id = await runtime.start_interaction(session.id)
        started = await anext(stream)
        assert started.realtime_interaction_id == new_id  # type: ignore[union-attr]
        assert new_id != old_id
        assert session.active_interaction is not None
        assert session.active_interaction.response_epoch == 2
        assert session.active_interaction.id == new_id
        assert fake.sessions()[0].interrupts() == (old_id,)
        assert fake.sessions()[0].started_interactions() == (old_id,)
        assert fake.sessions()[1].started_interactions() == (new_id,)
        assert (
            session.classify_interaction(old_id) is InteractionGeneration.RETIRED_KNOWN
        )
        async with factory() as uow:
            assert await uow.turns.list_for_conversation(conversation.id) == []
        await runtime.cancel_interaction(session.id, new_id)
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_transcript_start_replaces_processing_turn_and_preserves_partial(
    tmp_path: Path,
) -> None:
    old_entered = asyncio.Event()
    old_release = asyncio.Event()
    new_hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("old input"),
                    FakeAssistantTranscriptPartial("partial "),
                    FakeRealtimeBarrier(old_entered, old_release),
                )
            ),
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("new input"),
                    FakeAssistantTranscriptFinal("new answer"),
                    FakeRealtimeCompleted(),
                    FakeRealtimePause(new_hold),
                )
            ),
        )
    )
    runtime, text_runtime, factory, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        old_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        await anext(stream)  # user transcript
        await anext(stream)  # TurnStarted
        await anext(stream)  # assistant partial
        await old_entered.wait()

        new_id = await runtime.start_interaction(session.id)
        interrupted = await anext(stream)
        started = await anext(stream)
        assert isinstance(interrupted, ConversationTurnInterrupted)
        assert interrupted.turn.status is TurnStatus.INTERRUPTED
        assert interrupted.turn.assistant_text == "partial "
        assert started.realtime_interaction_id == new_id  # type: ignore[union-attr]
        assert new_id != old_id
        assert session.active_interaction is not None
        assert session.active_interaction.response_epoch == 2
        assert fake.sessions()[0].interrupts() == (old_id,)
        completed = False
        while not completed:
            completed = isinstance(await anext(stream), ConversationTurnCompleted)
        async with factory() as uow:
            turns = await uow.turns.list_for_conversation(conversation.id)
        assert [turn.status for turn in turns] == [
            TurnStatus.INTERRUPTED,
            TurnStatus.COMPLETED,
        ]
        assert turns[0].assistant_text == "partial "
        assert turns[1].assistant_text == "new answer"
        new_hold.set()
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_replacement_keeps_voice_lease_while_new_provider_start_is_blocked(
    tmp_path: Path,
) -> None:
    old_hold = asyncio.Event()
    new_started = asyncio.Event()
    new_release = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript((FakeRealtimePause(old_hold),)),
            FakeRealtimeScript(
                (FakeRealtimePause(asyncio.Event()),),
                start_barrier=FakeRealtimeBarrier(new_started, new_release),
            ),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)

        replacement = asyncio.create_task(runtime.start_interaction(session.id))
        await new_started.wait()
        with pytest.raises(ConversationActivityConflictError):
            await text_runtime.send_text(
                SendTextCommand(
                    conversation.id, "blocked", DataLocality.LOCAL_ONLY, True
                )
            )
        new_release.set()
        new_id = await replacement
        started = await anext(stream)
        assert started.realtime_interaction_id == new_id  # type: ignore[union-attr]
        await runtime.cancel_interaction(session.id, new_id)
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_replacement_start_failure_releases_lease_and_leaves_idle_session(
    tmp_path: Path,
) -> None:
    old_hold = asyncio.Event()
    retry_hold = asyncio.Event()
    fake = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript((FakeRealtimePause(old_hold),)),
            FakeRealtimeScript((), start_error="new start failed"),
            FakeRealtimeScript((FakeRealtimePause(retry_hold),)),
        )
    )
    runtime, text_runtime, _, engine = await _runtime(tmp_path, fake)
    try:
        conversation = await text_runtime.create_conversation()
        session = await runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation.id, DataLocality.LOCAL_ONLY, True, _format(), _format()
            )
        )
        stream = runtime.events(session.id)
        await anext(stream)
        old_id = await runtime.start_interaction(session.id)
        await anext(stream)
        await runtime.commit_interaction(session.id)
        with pytest.raises(RuntimeError, match="new start failed"):
            await runtime.start_interaction(session.id)
        assert session.active_interaction is None
        assert session.state.value == "IDLE"
        assert fake.sessions()[0].interrupts() == (old_id,)

        retry_id = await runtime.start_interaction(session.id)
        started = await anext(stream)
        assert started.realtime_interaction_id == retry_id  # type: ignore[union-attr]
        await runtime.cancel_interaction(session.id, retry_id)
        await runtime.close_session(session.id)
    finally:
        await engine.dispose()
