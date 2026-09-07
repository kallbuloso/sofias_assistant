"""Integration tests for Core-owned non-streaming-provider text streams."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.ai.contracts import (
    AIRequest,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ProviderCompleted,
    ProviderError,
    ProviderErrorCategory,
    ProviderInvocationError,
    ProviderResponseMetadata,
    ProviderStreamEvent,
    TextDelta,
    TextResponse,
    ToolCallProposal,
    UsageMetadata,
)
from sofias_assistant.ai.providers import TextGenerationProvider, TextStreamingProvider
from sofias_assistant.ai.registry import (
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.conversation.events import (
    ConversationTextDelta,
    ConversationToolCallProposed,
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnStarted,
    ConversationUsageUpdated,
)
from sofias_assistant.conversation.models import Turn, TurnStatus
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
from tests.support.ai import (
    FakeStreamCompleted,
    FakeStreamFailed,
    FakeStreamScript,
    FakeTextDelta,
    FakeToolCall,
    FakeUsageUpdate,
    ScriptedFakeProvider,
)


@dataclass
class SequenceClock:
    current: datetime = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def descriptor(*, capabilities: frozenset[Capability]) -> ModelDescriptor:
    return ModelDescriptor(
        identity=ModelIdentity("fake", "stream"),
        capabilities=capabilities,
        execution_location=ExecutionLocation.LOCAL,
        context_window=4096,
    )


async def runtime_for(
    tmp_path: Path,
    provider: TextStreamingProvider | TextGenerationProvider,
    *,
    capabilities: frozenset[Capability] = frozenset({Capability.TEXT_STREAMING}),
    uow_factory_override: Callable[[], SqlAlchemyUnitOfWork] | None = None,
) -> tuple[TextConversationRuntime, Callable[[], SqlAlchemyUnitOfWork], AsyncEngine]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await asyncio.to_thread(upgrade_to_head, database_url)
    engine = create_async_engine(database_url)
    session_factory = create_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    registry = ModelRegistry()
    registry.register(
        ModelRegistration(
            descriptor=descriptor(capabilities=capabilities),
            binding=ProviderBinding(
                text_generation=(
                    cast(TextGenerationProvider, provider)
                    if Capability.TEXT_GENERATION in capabilities
                    else None
                ),
                text_streaming=(
                    cast(TextStreamingProvider, provider)
                    if Capability.TEXT_STREAMING in capabilities
                    else None
                ),
            ),
        )
    )
    return (
        TextConversationRuntime(
            uow_factory=uow_factory_override or uow_factory,
            router=CapabilityRouter(registry),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext("System", True),
                max_recent_turns=10,
                max_estimated_input_tokens=10_000,
            ),
            clock=SequenceClock(),
        ),
        uow_factory,
        engine,
    )


async def load_turns(
    factory: Callable[[], SqlAlchemyUnitOfWork], conversation_id: UUID
) -> list[Turn]:
    async with factory() as unit_of_work:
        return await unit_of_work.turns.list_for_conversation(conversation_id)


async def collect(iterator: AsyncIterator[object]) -> list[object]:
    return [event async for event in iterator]


@pytest.mark.asyncio
async def test_stream_success_emits_ordered_events_and_persists_exact_final_text(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider(
        stream_scripts=[
            FakeStreamScript(
                items=(
                    FakeTextDelta("hello"),
                    FakeUsageUpdate(UsageMetadata(output_tokens=1)),
                    FakeTextDelta(" world"),
                    FakeStreamCompleted(UsageMetadata(output_tokens=2)),
                ),
                provider_request_id="provider-request",
                provider_session_id="provider-session",
            )
        ]
    )
    runtime, factory, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        events = await collect(
            runtime.stream_text(
                SendTextCommand(
                    conversation.id, "request", DataLocality.LOCAL_ONLY, True
                )
            )
        )
        assert [type(event) for event in events] == [
            ConversationTurnStarted,
            ConversationTextDelta,
            ConversationUsageUpdated,
            ConversationTextDelta,
            ConversationTurnCompleted,
        ]
        completed = events[-1]
        assert isinstance(completed, ConversationTurnCompleted)
        assert completed.turn.assistant_text == "hello world"
        assert completed.turn.provider_request_id == "provider-request"
        assert (await load_turns(factory, conversation.id))[0] == completed.turn
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_stream_starts_after_processing_commit_and_uow_close(
    tmp_path: Path,
) -> None:
    tracker = StreamUowTracker()
    provider = ObservingStreamingProvider(tracker)
    runtime, raw_factory, engine = await runtime_for(
        tmp_path,
        provider,
        uow_factory_override=tracker.factory,
    )
    tracker.raw_factory = raw_factory
    try:
        conversation = await runtime.create_conversation()
        provider.conversation_id = conversation.id
        await collect(
            runtime.stream_text(
                SendTextCommand(
                    conversation.id, "request", DataLocality.LOCAL_ONLY, True
                )
            )
        )
        assert provider.observed_processing is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_zero_deltas_and_provider_failure_preserve_terminal_semantics(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider(
        stream_scripts=[
            FakeStreamScript(items=(FakeStreamCompleted(),)),
            FakeStreamScript(
                items=(
                    FakeTextDelta("partial"),
                    FakeStreamFailed(
                        ProviderError(
                            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                            "provider unavailable",
                            retryable=False,
                        )
                    ),
                )
            ),
        ]
    )
    runtime, _, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        first = await collect(
            runtime.stream_text(
                SendTextCommand(conversation.id, "one", DataLocality.LOCAL_ONLY, True)
            )
        )
        second = await collect(
            runtime.stream_text(
                SendTextCommand(conversation.id, "two", DataLocality.LOCAL_ONLY, True)
            )
        )
        assert isinstance(first[-1], ConversationTurnCompleted)
        assert first[-1].turn.assistant_text == ""
        assert isinstance(second[-1], ConversationTurnFailed)
        assert second[-1].turn.assistant_text == "partial"
        assert second[-1].turn.error_category == "provider_unavailable"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tool_proposal_is_inert_and_later_text_is_not_persisted(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider(
        stream_scripts=[
            FakeStreamScript(
                items=(
                    FakeTextDelta("before"),
                    FakeToolCall(ToolCallProposal("call", "tool", {})),
                    FakeTextDelta("after"),
                    FakeStreamCompleted(),
                )
            )
        ]
    )
    runtime, _, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        events = await collect(
            runtime.stream_text(
                SendTextCommand(
                    conversation.id, "request", DataLocality.LOCAL_ONLY, True
                )
            )
        )
        assert any(isinstance(event, ConversationToolCallProposed) for event in events)
        assert not any(
            isinstance(event, ConversationTextDelta) and event.text == "after"
            for event in events
        )
        assert isinstance(events[-1], ConversationTurnFailed)
        assert events[-1].turn.error_category == "tool_call_unsupported"
        assert events[-1].turn.assistant_text == "before"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_deltas"),
    [
        ("metadata_mismatch", ["before"]),
        ("correlation_change", ["before"]),
        ("no_terminal", ["partial"]),
        ("after_terminal", []),
    ],
)
async def test_protocol_violations_discard_untrusted_provider_correlation(
    tmp_path: Path, mode: str, expected_deltas: list[str]
) -> None:
    provider = MalformedStreamProvider(mode=mode)
    runtime, _, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        events = await collect(
            runtime.stream_text(
                SendTextCommand(
                    conversation.id, "request", DataLocality.LOCAL_ONLY, True
                )
            )
        )
        failed = events[-1]
        assert isinstance(failed, ConversationTurnFailed)
        assert failed.turn.error_category == "provider_protocol_error"
        assert [
            event.text for event in events if isinstance(event, ConversationTextDelta)
        ] == expected_deltas
        assert failed.turn.assistant_text == ("".join(expected_deltas) or None)
        assert failed.turn.provider_request_id is None
        assert failed.turn.provider_session_id is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_and_explicit_close_persist_interrupted_partial_turns(
    tmp_path: Path,
) -> None:
    provider = BlockingStreamProvider()
    runtime, factory, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        iterator = runtime.stream_text(
            SendTextCommand(conversation.id, "request", DataLocality.LOCAL_ONLY, True)
        )
        assert isinstance(await anext(iterator), ConversationTurnStarted)
        assert isinstance(await anext(iterator), ConversationTextDelta)
        turns = await load_turns(factory, conversation.id)
        assert turns[0].status is TurnStatus.PROCESSING
        assert turns[0].assistant_text is None
        await cast(AsyncGenerator[object], iterator).aclose()
        turns = await load_turns(factory, conversation.id)
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "partial"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_cancellation_persists_interruption_and_reraises(
    tmp_path: Path,
) -> None:
    provider = BlockingStreamProvider()
    runtime, factory, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        task = asyncio.create_task(
            collect(
                runtime.stream_text(
                    SendTextCommand(
                        conversation.id, "request", DataLocality.LOCAL_ONLY, True
                    )
                )
            )
        )
        await provider.waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        turns = await load_turns(factory, conversation.id)
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "partial"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_after_protocol_violation_discards_provider_ids(
    tmp_path: Path,
) -> None:
    provider = ProtocolBlockingProvider()
    runtime, factory, engine = await runtime_for(tmp_path, provider)
    try:
        conversation = await runtime.create_conversation()
        task = asyncio.create_task(
            collect(
                runtime.stream_text(
                    SendTextCommand(
                        conversation.id, "request", DataLocality.LOCAL_ONLY, True
                    )
                )
            )
        )
        await provider.blocked.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        turns = await load_turns(factory, conversation.id)
        assert turns[0].status is TurnStatus.INTERRUPTED
        assert turns[0].assistant_text == "before"
        assert turns[0].provider_id == "fake"
        assert turns[0].model_id == "stream"
        assert turns[0].provider_request_id is None
        assert turns[0].provider_session_id is None

        follow_up = runtime.stream_text(
            SendTextCommand(conversation.id, "follow-up", DataLocality.LOCAL_ONLY, True)
        )
        assert isinstance(await anext(follow_up), ConversationTurnStarted)
        await cast(AsyncGenerator[object], follow_up).aclose()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_normalized_provider_invocation_error_preserves_partial_text(
    tmp_path: Path,
) -> None:
    runtime, _, engine = await runtime_for(tmp_path, RaisingStreamProvider())
    try:
        conversation = await runtime.create_conversation()
        events = await collect(
            runtime.stream_text(
                SendTextCommand(
                    conversation.id, "request", DataLocality.LOCAL_ONLY, True
                )
            )
        )
        failed = events[-1]
        assert isinstance(failed, ConversationTurnFailed)
        assert failed.turn.error_category == "timeout"
        assert failed.turn.error_message == "provider timed out"
        assert failed.turn.assistant_text == "partial"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stream_requires_streaming_capability_and_does_not_use_generation_only_model(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider()
    runtime, _, engine = await runtime_for(
        tmp_path, provider, capabilities=frozenset({Capability.TEXT_GENERATION})
    )
    try:
        conversation = await runtime.create_conversation()
        events = await collect(
            runtime.stream_text(
                SendTextCommand(
                    conversation.id, "request", DataLocality.LOCAL_ONLY, True
                )
            )
        )
        assert isinstance(events[0], ConversationTurnStarted)
        assert isinstance(events[-1], ConversationTurnFailed)
        assert events[-1].turn.error_category == "routing_error"
        assert provider.invocations() == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stream_and_non_stream_work_share_the_same_conversation_lock(
    tmp_path: Path,
) -> None:
    provider = DualBlockingProvider()
    runtime, _, engine = await runtime_for(
        tmp_path,
        provider,
        capabilities=frozenset({Capability.TEXT_GENERATION, Capability.TEXT_STREAMING}),
    )
    try:
        conversation = await runtime.create_conversation()
        stream_task = asyncio.create_task(
            collect(
                runtime.stream_text(
                    SendTextCommand(
                        conversation.id, "stream", DataLocality.LOCAL_ONLY, True
                    )
                )
            )
        )
        await provider.stream_waiting.wait()
        submit_started = asyncio.Event()

        async def submit_text() -> object:
            submit_started.set()
            return await runtime.send_text(
                SendTextCommand(conversation.id, "next", DataLocality.LOCAL_ONLY, True)
            )

        text_task = asyncio.create_task(submit_text())
        await submit_started.wait()
        assert provider.text_calls == 0
        provider.release.set()
        await asyncio.gather(stream_task, text_task)
        assert provider.text_calls == 1
    finally:
        await engine.dispose()


class BlockingStreamProvider:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.waiting = asyncio.Event()

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        metadata = ProviderResponseMetadata(request.request_id, model)
        yield TextDelta(metadata, "partial")
        self.waiting.set()
        await self.release.wait()
        yield ProviderCompleted(metadata)


class MalformedStreamProvider:
    def __init__(self, *, mode: str) -> None:
        self._mode = mode

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        if self._mode == "metadata_mismatch":
            valid = ProviderResponseMetadata(
                request.request_id, model, "trusted", "session"
            )
            yield TextDelta(valid, "before")
            yield TextDelta(
                ProviderResponseMetadata(uuid4(), model, "untrusted", "session"), "bad"
            )
            yield TextDelta(valid, "after")
            yield ProviderCompleted(valid)
            return
        if self._mode == "correlation_change":
            metadata = ProviderResponseMetadata(
                request.request_id, model, "first", None
            )
            yield TextDelta(
                metadata,
                "before",
            )
            yield ProviderCompleted(
                ProviderResponseMetadata(request.request_id, model, "second", None)
            )
            yield TextDelta(metadata, "after")
            yield ProviderCompleted(metadata)
            return
        if self._mode == "no_terminal":
            yield TextDelta(
                ProviderResponseMetadata(request.request_id, model), "partial"
            )
            return
        if self._mode == "after_terminal":
            metadata = ProviderResponseMetadata(request.request_id, model)
            yield ProviderCompleted(metadata)
            yield TextDelta(metadata, "late")
            return
        raise AssertionError("unsupported malformed stream mode")


class RaisingStreamProvider:
    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        metadata = ProviderResponseMetadata(request.request_id, model, "request", None)
        yield TextDelta(metadata, "partial")
        raise ProviderInvocationError(
            ProviderError(ProviderErrorCategory.TIMEOUT, "provider timed out", False)
        )


class ProtocolBlockingProvider:
    def __init__(self) -> None:
        self.blocked = asyncio.Event()
        self._calls = 0

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        self._calls += 1
        metadata = ProviderResponseMetadata(
            request.request_id, model, "trusted", "session"
        )
        if self._calls > 1:
            yield ProviderCompleted(metadata)
            return
        yield TextDelta(metadata, "before")
        yield TextDelta(
            ProviderResponseMetadata(uuid4(), model, "bad", "session"), "bad"
        )
        self.blocked.set()
        await asyncio.Event().wait()


class DualBlockingProvider:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.stream_waiting = asyncio.Event()
        self.text_calls = 0

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        self.text_calls += 1
        return TextResponse(
            "answer", ProviderResponseMetadata(request.request_id, model)
        )

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        metadata = ProviderResponseMetadata(request.request_id, model)
        self.stream_waiting.set()
        await self.release.wait()
        yield ProviderCompleted(metadata)


@dataclass
class StreamUowTracker:
    raw_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None
    active: int = 0

    def factory(self) -> SqlAlchemyUnitOfWork:
        if self.raw_factory is None:
            raise AssertionError("raw UoW factory is not configured")
        return cast(SqlAlchemyUnitOfWork, TrackingStreamUow(self.raw_factory(), self))


class TrackingStreamUow:
    def __init__(self, inner: SqlAlchemyUnitOfWork, tracker: StreamUowTracker) -> None:
        self._inner = inner
        self._tracker = tracker

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        entered = await self._inner.__aenter__()
        self._tracker.active += 1
        return entered

    async def __aexit__(self, *args: object) -> None:
        try:
            await self._inner.__aexit__(*args)
        finally:
            self._tracker.active -= 1


class ObservingStreamingProvider:
    def __init__(self, tracker: StreamUowTracker) -> None:
        self._tracker = tracker
        self.conversation_id: UUID | None = None
        self.observed_processing = False

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        assert self._tracker.active == 0
        assert self._tracker.raw_factory is not None
        assert self.conversation_id is not None
        async with self._tracker.raw_factory() as unit_of_work:
            turns = await unit_of_work.turns.list_for_conversation(self.conversation_id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.PROCESSING
        self.observed_processing = True
        yield ProviderCompleted(ProviderResponseMetadata(request.request_id, model))
