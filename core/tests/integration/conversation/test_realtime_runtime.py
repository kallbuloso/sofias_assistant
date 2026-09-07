"""Integration evidence for the provider-neutral realtime conversation runtime."""

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.ai.contracts import (
    AudioEncoding,
    AudioFormat,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ProviderError,
    ProviderErrorCategory,
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
    ConversationTurnStarted,
)
from sofias_assistant.conversation.models import TurnInputModality, TurnStatus
from sofias_assistant.conversation.realtime_events import (
    ConversationRealtimeSessionFailed,
    RealtimeAssistantAudioChunk,
)
from sofias_assistant.conversation.realtime_runtime import (
    OpenRealtimeSessionCommand,
    RealtimeConversationRuntime,
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
    FakeRealtimeCompleted,
    FakeRealtimeFailed,
    FakeRealtimePause,
    FakeRealtimeScript,
    FakeRealtimeSessionFailed,
    FakeSignaledAssistantAudioChunk,
    FakeUserTranscriptFinal,
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
