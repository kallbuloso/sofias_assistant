"""Deterministic scripted provider support for AI boundary tests."""

from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from sofias_assistant.ai.contracts import (
    AIRequest,
    JsonValue,
    ModelIdentity,
    ProviderCompleted,
    ProviderError,
    ProviderFailed,
    ProviderInvocationError,
    ProviderResponseMetadata,
    ProviderStreamEvent,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextDelta,
    TextResponse,
    ToolCallProposal,
    ToolCallProposed,
    UsageMetadata,
    UsageUpdated,
)


class FakeProviderScriptError(AssertionError):
    """Raised when a test invokes the fake without a valid scripted outcome."""


class FakeProviderOperation(StrEnum):
    """Operation names recorded by ScriptedFakeProvider."""

    TEXT_GENERATION = "text_generation"
    TEXT_STREAMING = "text_streaming"
    STRUCTURED_OUTPUT = "structured_output"


@dataclass(frozen=True, slots=True)
class FakeTextSuccess:
    """Scripted normalized success for one non-streaming text invocation."""

    text: str
    tool_calls: tuple[ToolCallProposal, ...] = ()
    usage: UsageMetadata | None = None
    provider_request_id: str | None = None
    provider_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class FakeStructuredSuccess:
    """Scripted normalized success for one structured-output invocation."""

    value: JsonValue
    usage: UsageMetadata | None = None
    provider_request_id: str | None = None
    provider_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class FakeProviderFailure:
    """Scripted normalized failure for a non-streaming provider invocation."""

    error: ProviderError


@dataclass(frozen=True, slots=True)
class FakeTextDelta:
    """Script item converted to a normalized non-terminal TextDelta."""

    text: str


@dataclass(frozen=True, slots=True)
class FakeToolCall:
    """Script item converted to an inert normalized ToolCallProposed event."""

    proposal: ToolCallProposal


@dataclass(frozen=True, slots=True)
class FakeUsageUpdate:
    """Script item converted to a normalized non-terminal UsageUpdated event."""

    usage: UsageMetadata


@dataclass(frozen=True, slots=True)
class FakeStreamCompleted:
    """Script terminal converted to a successful ProviderCompleted event."""

    usage: UsageMetadata | None = None


@dataclass(frozen=True, slots=True)
class FakeStreamFailed:
    """Script terminal converted to a failed ProviderFailed event."""

    error: ProviderError


type FakeTextOutcome = FakeTextSuccess | FakeProviderFailure
type FakeStructuredOutcome = FakeStructuredSuccess | FakeProviderFailure
type FakeStreamItem = (
    FakeTextDelta
    | FakeToolCall
    | FakeUsageUpdate
    | FakeStreamCompleted
    | FakeStreamFailed
)


@dataclass(frozen=True, slots=True)
class FakeStreamScript:
    """One validated scripted stream with optional operational provider IDs."""

    items: tuple[FakeStreamItem, ...]
    provider_request_id: str | None = None
    provider_session_id: str | None = None

    def __post_init__(self) -> None:
        _validate_stream_items(self.items)


@dataclass(frozen=True, slots=True)
class FakeProviderInvocation:
    """Read-only record of one call received by the scripted fake."""

    operation: FakeProviderOperation
    model: ModelIdentity
    request: AIRequest = field(repr=False)
    structured_output_spec: StructuredOutputSpec | None = field(
        default=None, repr=False
    )


def _metadata(
    request: AIRequest,
    model: ModelIdentity,
    provider_request_id: str | None,
    provider_session_id: str | None,
) -> ProviderResponseMetadata:
    return ProviderResponseMetadata(
        request_id=request.request_id,
        model=model,
        provider_request_id=provider_request_id,
        provider_session_id=provider_session_id,
    )


def _validate_stream_items(items: tuple[FakeStreamItem, ...]) -> None:
    if not all(
        isinstance(
            item,
            (
                FakeTextDelta,
                FakeToolCall,
                FakeUsageUpdate,
                FakeStreamCompleted,
                FakeStreamFailed,
            ),
        )
        for item in items
    ):
        raise FakeProviderScriptError("A stream script contains an unsupported item")
    terminals = tuple(
        index
        for index, item in enumerate(items)
        if isinstance(item, (FakeStreamCompleted, FakeStreamFailed))
    )
    if len(terminals) != 1:
        raise FakeProviderScriptError(
            "A stream script must contain exactly one terminal"
        )
    if terminals[0] != len(items) - 1:
        raise FakeProviderScriptError("A stream script terminal must be the final item")


class ScriptedFakeProvider:
    """A deterministic, no-I/O structural implementation of all AI protocols."""

    def __init__(
        self,
        *,
        text_scripts: Iterable[FakeTextOutcome] = (),
        stream_scripts: Iterable[FakeStreamScript] = (),
        structured_scripts: Iterable[FakeStructuredOutcome] = (),
    ) -> None:
        frozen_stream_scripts = tuple(stream_scripts)
        self._text_scripts = deque(text_scripts)
        self._stream_scripts = deque(frozen_stream_scripts)
        self._structured_scripts = deque(structured_scripts)
        self._invocations: list[FakeProviderInvocation] = []

    def invocations(self) -> tuple[FakeProviderInvocation, ...]:
        """Return a read-only snapshot of calls in their invocation order."""

        return tuple(self._invocations)

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        """Consume one text script and return or raise its normalized outcome."""

        self._record(FakeProviderOperation.TEXT_GENERATION, model, request)
        outcome = self._consume(self._text_scripts, "text generation")
        if isinstance(outcome, FakeProviderFailure):
            raise ProviderInvocationError(outcome.error)
        return TextResponse(
            text=outcome.text,
            metadata=_metadata(
                request,
                model,
                outcome.provider_request_id,
                outcome.provider_session_id,
            ),
            tool_calls=outcome.tool_calls,
            usage=outcome.usage,
        )

    async def generate_structured_output(
        self,
        *,
        model: ModelIdentity,
        request: AIRequest,
        spec: StructuredOutputSpec,
    ) -> StructuredOutputResult:
        """Consume one structured script without validating its JSON Schema."""

        self._record(FakeProviderOperation.STRUCTURED_OUTPUT, model, request, spec)
        outcome = self._consume(self._structured_scripts, "structured output")
        if isinstance(outcome, FakeProviderFailure):
            raise ProviderInvocationError(outcome.error)
        return StructuredOutputResult(
            value=outcome.value,
            metadata=_metadata(
                request,
                model,
                outcome.provider_request_id,
                outcome.provider_session_id,
            ),
            usage=outcome.usage,
        )

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Yield one validated scripted stream immediately and in configured order."""

        self._record(FakeProviderOperation.TEXT_STREAMING, model, request)
        script = self._consume(self._stream_scripts, "text streaming")
        metadata = _metadata(
            request,
            model,
            script.provider_request_id,
            script.provider_session_id,
        )
        for item in script.items:
            if isinstance(item, FakeTextDelta):
                yield TextDelta(metadata=metadata, text=item.text)
            elif isinstance(item, FakeToolCall):
                yield ToolCallProposed(metadata=metadata, proposal=item.proposal)
            elif isinstance(item, FakeUsageUpdate):
                yield UsageUpdated(metadata=metadata, usage=item.usage)
            elif isinstance(item, FakeStreamCompleted):
                yield ProviderCompleted(metadata=metadata, usage=item.usage)
            else:
                yield ProviderFailed(metadata=metadata, error=item.error)

    def _record(
        self,
        operation: FakeProviderOperation,
        model: ModelIdentity,
        request: AIRequest,
        spec: StructuredOutputSpec | None = None,
    ) -> None:
        self._invocations.append(
            FakeProviderInvocation(operation, model, request, spec)
        )

    @staticmethod
    def _consume[T](scripts: deque[T], operation: str) -> T:
        if not scripts:
            raise FakeProviderScriptError(f"No {operation} script is available")
        return scripts.popleft()
