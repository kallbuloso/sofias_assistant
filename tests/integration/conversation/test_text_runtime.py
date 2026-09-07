"""Integration tests for the Core-owned non-streaming text runtime."""

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    ProviderError,
    ProviderErrorCategory,
    ProviderResponseMetadata,
    TextResponse,
    ToolCallProposal,
)
from sofias_assistant.ai.providers import TextGenerationProvider
from sofias_assistant.ai.registry import (
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.conversation.models import Conversation, Turn, TurnStatus
from sofias_assistant.conversation.runtime import (
    ConversationNotFoundError,
    SendTextCommand,
    TextConversationRuntime,
    TextTurnResult,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.ai import FakeProviderFailure, FakeTextSuccess, ScriptedFakeProvider


@dataclass
class SequenceClock:
    """Deterministic UTC clock that advances by one second per call."""

    current: datetime = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"


def identity(name: str) -> ModelIdentity:
    return ModelIdentity(provider_id="fake", model_id=name)


def descriptor(name: str, location: ExecutionLocation) -> ModelDescriptor:
    return ModelDescriptor(
        identity=identity(name),
        capabilities=frozenset({Capability.TEXT_GENERATION}),
        execution_location=location,
        context_window=4096,
    )


async def create_runtime(
    tmp_path: Path,
    registrations: Iterable[tuple[ModelDescriptor, TextGenerationProvider]],
    *,
    system_cloud_eligible: bool = True,
    max_recent_turns: int = 10,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None,
) -> tuple[
    TextConversationRuntime,
    Callable[[], SqlAlchemyUnitOfWork],
    AsyncEngine,
    CapabilityRouter,
    ContextBuilder,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    url = database_url(tmp_path)
    await asyncio.to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)

    def raw_uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    registry = ModelRegistry()
    for registered_descriptor, provider in registrations:
        registry.register(
            ModelRegistration(
                descriptor=registered_descriptor,
                binding=ProviderBinding(text_generation=provider),
            )
        )
    router = CapabilityRouter(registry)
    context_builder = ContextBuilder(
        system_context=CoreSystemContext(
            text="System principles",
            cloud_context_eligible=system_cloud_eligible,
        ),
        max_recent_turns=max_recent_turns,
    )
    runtime = TextConversationRuntime(
        uow_factory=uow_factory or raw_uow_factory,
        router=router,
        context_builder=context_builder,
        clock=SequenceClock(),
    )
    return runtime, raw_uow_factory, engine, router, context_builder


async def load_conversation_and_turns(
    factory: Callable[[], SqlAlchemyUnitOfWork], conversation_id: UUID
) -> tuple[Conversation, list[Turn]]:
    async with factory() as unit_of_work:
        conversation = await unit_of_work.conversations.get_by_id(conversation_id)
        turns = await unit_of_work.turns.list_for_conversation(conversation_id)
    assert conversation is not None
    return conversation, turns


@pytest.mark.asyncio
async def test_create_conversation_is_durable(tmp_path: Path) -> None:
    provider = ScriptedFakeProvider()
    runtime, factory, engine, _, _ = await create_runtime(
        tmp_path, [(descriptor("local", ExecutionLocation.LOCAL), provider)]
    )
    try:
        created = await runtime.create_conversation()
        persisted, turns = await load_conversation_and_turns(factory, created.id)
        assert persisted == created
        assert turns == []
        assert provider.invocations() == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_successful_turn_is_processing_before_inference_and_completed_after(
    tmp_path: Path,
) -> None:
    tracker = UowTracker()
    provider = ObservingProvider(tracker)
    runtime, raw_factory, engine, _, _ = await create_runtime(
        tmp_path,
        [(descriptor("local", ExecutionLocation.LOCAL), provider)],
        uow_factory=tracker.factory_placeholder,
    )
    tracker.raw_factory = raw_factory
    try:
        conversation = await runtime.create_conversation()
        provider.conversation_id = conversation.id
        result = await runtime.send_text(
            SendTextCommand(
                conversation_id=conversation.id,
                text="  exact user text  ",
                locality=DataLocality.LOCAL_ONLY,
                cloud_context_eligible=True,
            )
        )
        assert provider.observed_processing is True
        assert result.turn.status is TurnStatus.COMPLETED
        assert result.turn.user_text == "  exact user text  "
        assert result.turn.assistant_text == "answer"
        assert result.turn.ai_request_id is not None
        assert result.turn.provider_id == "fake"
        assert result.turn.model_id == "local"
        assert result.turn.provider_request_id == "provider-request"
        assert result.turn.provider_session_id == "provider-session"
        assert result.conversation.updated_at > conversation.updated_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_continue_after_runtime_reconstruction_uses_completed_core_history(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider(
        text_scripts=[
            FakeTextSuccess("first", provider_session_id="discardable-session"),
            FakeTextSuccess("second"),
        ]
    )
    registrations = [(descriptor("local", ExecutionLocation.LOCAL), provider)]
    runtime, factory, engine, router, context_builder = await create_runtime(
        tmp_path, registrations
    )
    try:
        conversation = await runtime.create_conversation()
        first = await runtime.send_text(
            SendTextCommand(
                conversation.id, "first user", DataLocality.LOCAL_ONLY, True
            )
        )
        recreated = TextConversationRuntime(
            uow_factory=factory,
            router=router,
            context_builder=context_builder,
            clock=SequenceClock(),
        )
        second = await recreated.send_text(
            SendTextCommand(
                conversation.id, "second user", DataLocality.LOCAL_ONLY, True
            )
        )
        assert second.conversation.id == conversation.id
        assert second.turn.sequence == 2
        request = provider.invocations()[1].request
        assert [(message.role.value, message.text) for message in request.messages] == [
            ("system", "System principles"),
            ("user", "first user"),
            ("assistant", "first"),
            ("user", "second user"),
        ]
        assert first.turn.provider_session_id == "discardable-session"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_model_override_substitutes_provider_model_without_changing_conversation(
    tmp_path: Path,
) -> None:
    first_provider = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("a")])
    second_provider = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("b")])
    first_descriptor = descriptor("a", ExecutionLocation.LOCAL)
    second_descriptor = descriptor("b", ExecutionLocation.LOCAL)
    runtime, _, engine, _, _ = await create_runtime(
        tmp_path,
        [(first_descriptor, first_provider), (second_descriptor, second_provider)],
    )
    try:
        conversation = await runtime.create_conversation()
        first = await runtime.send_text(
            SendTextCommand(conversation.id, "one", DataLocality.LOCAL_ONLY, True)
        )
        second = await runtime.send_text(
            SendTextCommand(
                conversation.id,
                "two",
                DataLocality.LOCAL_ONLY,
                True,
                model_override=second_descriptor.identity,
            )
        )
        assert first.turn.provider_id == "fake"
        assert first.turn.model_id == "a"
        assert second.turn.model_id == "b"
        assert second.conversation.id == conversation.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_normalized_provider_failure_preserves_conversation_and_failed_history_is_excluded(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider(
        text_scripts=[
            FakeProviderFailure(
                ProviderError(
                    ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                    "provider unavailable",
                    retryable=False,
                )
            ),
            FakeTextSuccess("recovered"),
        ]
    )
    runtime, _, engine, _, _ = await create_runtime(
        tmp_path, [(descriptor("local", ExecutionLocation.LOCAL), provider)]
    )
    try:
        conversation = await runtime.create_conversation()
        failed = await runtime.send_text(
            SendTextCommand(
                conversation.id, "failed user", DataLocality.LOCAL_ONLY, True
            )
        )
        completed = await runtime.send_text(
            SendTextCommand(conversation.id, "next user", DataLocality.LOCAL_ONLY, True)
        )
        assert failed.turn.status is TurnStatus.FAILED
        assert failed.turn.error_category == "provider_unavailable"
        assert failed.turn.error_message == "provider unavailable"
        assert completed.turn.status is TurnStatus.COMPLETED
        assert [
            (message.role.value, message.text)
            for message in provider.invocations()[1].request.messages
        ] == [
            ("system", "System principles"),
            ("user", "next user"),
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_routing_and_context_locality_failures_do_not_invoke_provider(
    tmp_path: Path,
) -> None:
    no_provider_runtime, _, no_provider_engine, _, _ = await create_runtime(
        tmp_path, []
    )
    cloud_provider = ScriptedFakeProvider()
    locality_runtime, _, locality_engine, _, _ = await create_runtime(
        tmp_path / "locality",
        [(descriptor("cloud", ExecutionLocation.CLOUD), cloud_provider)],
    )
    try:
        routing_conversation = await no_provider_runtime.create_conversation()
        routing_result = await no_provider_runtime.send_text(
            SendTextCommand(
                routing_conversation.id, "route", DataLocality.LOCAL_ONLY, True
            )
        )
        assert routing_result.turn.error_category == "routing_error"

        locality_conversation = await locality_runtime.create_conversation()
        locality_result = await locality_runtime.send_text(
            SendTextCommand(
                locality_conversation.id,
                "restricted",
                DataLocality.CLOUD_ALLOWED,
                False,
            )
        )
        assert locality_result.turn.error_category == "context_locality_error"
        assert cloud_provider.invocations() == ()
    finally:
        await no_provider_engine.dispose()
        await locality_engine.dispose()


@pytest.mark.asyncio
async def test_projection_egress_can_narrow_terminal_turn_eligibility(
    tmp_path: Path,
) -> None:
    provider = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("answer")])
    runtime, _, engine, _, _ = await create_runtime(
        tmp_path,
        [(descriptor("local", ExecutionLocation.LOCAL), provider)],
        system_cloud_eligible=False,
    )
    try:
        conversation = await runtime.create_conversation()
        result = await runtime.send_text(
            SendTextCommand(conversation.id, "request", DataLocality.LOCAL_ONLY, True)
        )
        assert result.turn.status is TurnStatus.COMPLETED
        assert result.turn.cloud_context_eligible is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_protocol_mismatch_and_tool_call_do_not_complete_turn(
    tmp_path: Path,
) -> None:
    mismatch_provider = MismatchedProvider()
    tool_provider = ScriptedFakeProvider(
        text_scripts=[
            FakeTextSuccess(
                "partial",
                tool_calls=(ToolCallProposal("call", "tool", {}),),
                provider_request_id="trusted-request",
                provider_session_id="trusted-session",
            )
        ]
    )
    mismatch_runtime, _, mismatch_engine, _, _ = await create_runtime(
        tmp_path,
        [(descriptor("local", ExecutionLocation.LOCAL), mismatch_provider)],
    )
    tool_runtime, _, tool_engine, _, _ = await create_runtime(
        tmp_path / "tool",
        [(descriptor("local", ExecutionLocation.LOCAL), tool_provider)],
    )
    try:
        mismatch_conversation = await mismatch_runtime.create_conversation()
        mismatch = await mismatch_runtime.send_text(
            SendTextCommand(
                mismatch_conversation.id, "mismatch", DataLocality.LOCAL_ONLY, True
            )
        )
        assert mismatch.turn.status is TurnStatus.FAILED
        assert mismatch.turn.error_category == "provider_protocol_error"
        assert mismatch.turn.provider_request_id is None
        assert mismatch.turn.provider_session_id is None

        tool_conversation = await tool_runtime.create_conversation()
        tool = await tool_runtime.send_text(
            SendTextCommand(tool_conversation.id, "tool", DataLocality.LOCAL_ONLY, True)
        )
        assert tool.turn.status is TurnStatus.FAILED
        assert tool.turn.error_category == "tool_call_unsupported"
        assert tool.turn.assistant_text == "partial"
        assert tool.turn.provider_request_id == "trusted-request"
    finally:
        await mismatch_engine.dispose()
        await tool_engine.dispose()


@pytest.mark.asyncio
async def test_unknown_conversation_fails_before_provider(tmp_path: Path) -> None:
    provider = ScriptedFakeProvider()
    runtime, _, engine, _, _ = await create_runtime(
        tmp_path, [(descriptor("local", ExecutionLocation.LOCAL), provider)]
    )
    try:
        with pytest.raises(ConversationNotFoundError):
            await runtime.send_text(
                SendTextCommand(uuid4(), "missing", DataLocality.LOCAL_ONLY, True)
            )
        assert provider.invocations() == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_conversation_is_serialized_while_different_conversations_can_overlap(
    tmp_path: Path,
) -> None:
    same_provider = BlockingProvider(required_entries=1)
    runtime, factory, engine, _, _ = await create_runtime(
        tmp_path, [(descriptor("local", ExecutionLocation.LOCAL), same_provider)]
    )
    try:
        conversation = await runtime.create_conversation()
        first = asyncio.create_task(
            runtime.send_text(
                SendTextCommand(conversation.id, "first", DataLocality.LOCAL_ONLY, True)
            )
        )
        await same_provider.ready.wait()
        second_started = asyncio.Event()

        async def send_second() -> TextTurnResult:
            second_started.set()
            return await runtime.send_text(
                SendTextCommand(
                    conversation.id, "second", DataLocality.LOCAL_ONLY, True
                )
            )

        second = asyncio.create_task(send_second())
        await second_started.wait()
        assert same_provider.max_active == 1
        same_provider.release.set()
        await asyncio.gather(first, second)
        _, turns = await load_conversation_and_turns(factory, conversation.id)
        assert [turn.sequence for turn in turns] == [1, 2]
        assert all(turn.status is TurnStatus.COMPLETED for turn in turns)

        overlap_provider = BlockingProvider(required_entries=2)
        overlap_runtime, _, overlap_engine, _, _ = await create_runtime(
            tmp_path / "overlap",
            [(descriptor("local", ExecutionLocation.LOCAL), overlap_provider)],
        )
        try:
            first_conversation = await overlap_runtime.create_conversation()
            second_conversation = await overlap_runtime.create_conversation()
            first_task = asyncio.create_task(
                overlap_runtime.send_text(
                    SendTextCommand(
                        first_conversation.id, "first", DataLocality.LOCAL_ONLY, True
                    )
                )
            )
            second_task = asyncio.create_task(
                overlap_runtime.send_text(
                    SendTextCommand(
                        second_conversation.id, "second", DataLocality.LOCAL_ONLY, True
                    )
                )
            )
            await overlap_provider.ready.wait()
            assert overlap_provider.max_active == 2
            overlap_provider.release.set()
            await asyncio.gather(first_task, second_task)
        finally:
            await overlap_engine.dispose()
    finally:
        await engine.dispose()


@dataclass
class UowTracker:
    """Track runtime UoW contexts without changing production persistence."""

    raw_factory: Callable[[], SqlAlchemyUnitOfWork] | None = None
    active: int = 0

    def factory_placeholder(self) -> SqlAlchemyUnitOfWork:
        if self.raw_factory is None:
            raise AssertionError("raw UoW factory is not configured")
        return TrackingUow(self.raw_factory(), self)  # type: ignore[return-value]


class TrackingUow:
    def __init__(self, inner: SqlAlchemyUnitOfWork, tracker: UowTracker) -> None:
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


class ObservingProvider:
    def __init__(self, tracker: UowTracker) -> None:
        self._tracker = tracker
        self.conversation_id: UUID | None = None
        self.observed_processing = False

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        assert self._tracker.active == 0
        assert self._tracker.raw_factory is not None
        assert self.conversation_id is not None
        async with self._tracker.raw_factory() as unit_of_work:
            turns = await unit_of_work.turns.list_for_conversation(self.conversation_id)
        assert len(turns) == 1
        assert turns[0].status is TurnStatus.PROCESSING
        self.observed_processing = True
        return TextResponse(
            text="answer",
            metadata=ProviderResponseMetadata(
                request_id=request.request_id,
                model=model,
                provider_request_id="provider-request",
                provider_session_id="provider-session",
            ),
        )


class MismatchedProvider:
    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        return TextResponse(
            text="untrusted",
            metadata=ProviderResponseMetadata(
                request_id=uuid4(), model=model, provider_request_id="untrusted"
            ),
        )


class BlockingProvider:
    def __init__(self, *, required_entries: int) -> None:
        self._required_entries = required_entries
        self.ready = asyncio.Event()
        self.release = asyncio.Event()
        self._active = 0
        self.max_active = 0

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        if self._active >= self._required_entries:
            self.ready.set()
        try:
            await self.release.wait()
            return TextResponse(
                text="answer",
                metadata=ProviderResponseMetadata(
                    request_id=request.request_id,
                    model=model,
                ),
            )
        finally:
            self._active -= 1
