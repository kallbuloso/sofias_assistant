"""Unit tests for the deterministic ScriptedFakeProvider test support."""

from typing import cast
from uuid import UUID

import pytest

from sofias_assistant.ai import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    AIRequestRequirements,
    Capability,
    CapabilityRouter,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
    ProviderCompleted,
    ProviderError,
    ProviderErrorCategory,
    ProviderFailed,
    ProviderInvocationError,
    StructuredOutputProvider,
    StructuredOutputSpec,
    TextDelta,
    TextGenerationProvider,
    TextStreamingProvider,
    ToolCallProposal,
    ToolCallProposed,
    UsageMetadata,
    UsageUpdated,
)
from tests.support.ai import (
    FakeProviderFailure,
    FakeProviderOperation,
    FakeProviderScriptError,
    FakeStreamCompleted,
    FakeStreamFailed,
    FakeStreamItem,
    FakeStreamScript,
    FakeStructuredSuccess,
    FakeTextDelta,
    FakeTextSuccess,
    FakeToolCall,
    FakeUsageUpdate,
    ScriptedFakeProvider,
)


def _model() -> ModelIdentity:
    return ModelIdentity("fake-provider", "fake-model")


def _request(request_id: str) -> AIRequest:
    return AIRequest(
        request_id=UUID(request_id),
        messages=(AIMessage(AIMessageRole.USER, "Hello"),),
    )


def _error() -> ProviderError:
    return ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        "Provider unavailable",
        retryable=True,
    )


def test_fake_provider_satisfies_specialized_protocols_structurally() -> None:
    fake = ScriptedFakeProvider()

    generation_provider: TextGenerationProvider = fake
    streaming_provider: TextStreamingProvider = fake
    structured_provider: StructuredOutputProvider = fake

    assert generation_provider is fake
    assert streaming_provider is fake
    assert structured_provider is fake


@pytest.mark.asyncio
async def test_scripted_text_success_preserves_invocation_metadata() -> None:
    request = _request("00000000-0000-0000-0000-000000000001")
    model = _model()
    proposal = ToolCallProposal("call-1", "tool", {"enabled": True})
    fake = ScriptedFakeProvider(
        text_scripts=(
            FakeTextSuccess(
                text="Hello",
                tool_calls=(proposal,),
                usage=UsageMetadata(input_tokens=2, output_tokens=1),
                provider_request_id="provider-request",
                provider_session_id="provider-session",
            ),
        )
    )

    response = await fake.generate_text(model=model, request=request)

    assert response.text == "Hello"
    assert response.tool_calls == (proposal,)
    assert response.usage == UsageMetadata(input_tokens=2, output_tokens=1)
    assert response.metadata.request_id == request.request_id
    assert response.metadata.model == model
    assert response.metadata.provider_request_id == "provider-request"
    assert response.metadata.provider_session_id == "provider-session"


@pytest.mark.asyncio
async def test_scripted_text_failure_raises_normalized_error_only() -> None:
    error = _error()
    fake = ScriptedFakeProvider(text_scripts=(FakeProviderFailure(error),))

    with pytest.raises(ProviderInvocationError) as raised:
        await fake.generate_text(
            model=_model(),
            request=_request("00000000-0000-0000-0000-000000000002"),
        )

    assert raised.value.error is error
    assert str(raised.value) == error.safe_message


@pytest.mark.asyncio
async def test_structured_success_records_spec_and_preserves_metadata() -> None:
    request = _request("00000000-0000-0000-0000-000000000003")
    model = _model()
    spec = StructuredOutputSpec("answer", {"type": "object"})
    fake = ScriptedFakeProvider(
        structured_scripts=(
            FakeStructuredSuccess(
                value={"answer": "yes"},
                usage=UsageMetadata(output_tokens=2),
                provider_request_id="structured-request",
            ),
        )
    )

    response = await fake.generate_structured_output(
        model=model, request=request, spec=spec
    )

    assert response.value == {"answer": "yes"}
    assert response.metadata.request_id == request.request_id
    assert response.metadata.model == model
    assert response.metadata.provider_request_id == "structured-request"
    assert response.usage == UsageMetadata(output_tokens=2)
    assert fake.invocations()[0].structured_output_spec is spec


@pytest.mark.asyncio
async def test_structured_failure_raises_normalized_error() -> None:
    error = _error()
    fake = ScriptedFakeProvider(structured_scripts=(FakeProviderFailure(error),))

    with pytest.raises(ProviderInvocationError) as raised:
        await fake.generate_structured_output(
            model=_model(),
            request=_request("00000000-0000-0000-0000-000000000004"),
            spec=StructuredOutputSpec("answer", {"type": "object"}),
        )

    assert raised.value.error is error


@pytest.mark.asyncio
async def test_streaming_success_yields_ordered_normalized_events() -> None:
    request = _request("00000000-0000-0000-0000-000000000005")
    model = _model()
    proposal = ToolCallProposal("call-1", "tool", {})
    fake = ScriptedFakeProvider(
        stream_scripts=(
            FakeStreamScript(
                (
                    FakeTextDelta("Hel"),
                    FakeTextDelta("lo"),
                    FakeToolCall(proposal),
                    FakeUsageUpdate(UsageMetadata(input_tokens=2)),
                    FakeStreamCompleted(UsageMetadata(output_tokens=1)),
                ),
                provider_request_id="stream-request",
                provider_session_id="stream-session",
            ),
        )
    )

    events = [event async for event in fake.stream_text(model=model, request=request)]

    assert [type(event) for event in events] == [
        TextDelta,
        TextDelta,
        ToolCallProposed,
        UsageUpdated,
        ProviderCompleted,
    ]
    assert [event.metadata.request_id for event in events] == [request.request_id] * 5
    assert [event.metadata.model for event in events] == [model] * 5
    assert [event.metadata.provider_request_id for event in events] == [
        "stream-request"
    ] * 5
    assert [event.metadata.provider_session_id for event in events] == [
        "stream-session"
    ] * 5
    completed = events[-1]
    assert isinstance(completed, ProviderCompleted)
    assert completed.usage == UsageMetadata(output_tokens=1)


@pytest.mark.asyncio
async def test_streaming_failure_is_normalized_terminal_event() -> None:
    request = _request("00000000-0000-0000-0000-000000000006")
    error = _error()
    fake = ScriptedFakeProvider(
        stream_scripts=(
            FakeStreamScript((FakeTextDelta("partial"), FakeStreamFailed(error))),
        )
    )

    events = [
        event async for event in fake.stream_text(model=_model(), request=request)
    ]

    assert [type(event) for event in events] == [TextDelta, ProviderFailed]
    failed = events[-1]
    assert isinstance(failed, ProviderFailed)
    assert failed.error is error


@pytest.mark.parametrize(
    "items",
    [
        (),
        (FakeStreamCompleted(), FakeStreamFailed(_error())),
        (FakeStreamCompleted(), FakeTextDelta("after terminal")),
    ],
)
def test_invalid_stream_scripts_are_rejected(items: tuple[object, ...]) -> None:
    with pytest.raises(FakeProviderScriptError):
        FakeStreamScript(items=cast(tuple[FakeStreamItem, ...], items))


@pytest.mark.asyncio
async def test_unscripted_and_exhausted_calls_fail_clearly() -> None:
    fake = ScriptedFakeProvider(text_scripts=(FakeTextSuccess("first"),))
    request = _request("00000000-0000-0000-0000-000000000007")

    assert (await fake.generate_text(model=_model(), request=request)).text == "first"
    with pytest.raises(FakeProviderScriptError, match="No text generation script"):
        await fake.generate_text(model=_model(), request=request)


@pytest.mark.asyncio
async def test_text_scripts_are_consumed_in_order() -> None:
    fake = ScriptedFakeProvider(
        text_scripts=(FakeTextSuccess("first"), FakeTextSuccess("second"))
    )
    request = _request("00000000-0000-0000-0000-000000000008")

    first = await fake.generate_text(model=_model(), request=request)
    second = await fake.generate_text(model=_model(), request=request)

    assert first.text == "first"
    assert second.text == "second"
    with pytest.raises(FakeProviderScriptError, match="No text generation script"):
        await fake.generate_text(model=_model(), request=request)


@pytest.mark.asyncio
async def test_invocation_history_is_ordered_snapshot_and_scripts_are_owned() -> None:
    text_scripts = [FakeTextSuccess("first")]
    fake = ScriptedFakeProvider(text_scripts=text_scripts)
    text_scripts.append(FakeTextSuccess("externally added"))
    request = _request("00000000-0000-0000-0000-000000000009")
    model = _model()

    await fake.generate_text(model=model, request=request)
    history = fake.invocations()

    assert history[0].operation is FakeProviderOperation.TEXT_GENERATION
    assert history[0].model == model
    assert history[0].request == request
    assert history[0].structured_output_spec is None
    assert isinstance(history, tuple)
    with pytest.raises(FakeProviderScriptError):
        await fake.generate_text(model=model, request=request)


@pytest.mark.asyncio
async def test_tool_call_scripts_remain_inert_data() -> None:
    proposal = ToolCallProposal("call-1", "tool", {"argument": "value"})
    fake = ScriptedFakeProvider(
        text_scripts=(FakeTextSuccess("text", tool_calls=(proposal,)),),
        stream_scripts=(
            FakeStreamScript((FakeToolCall(proposal), FakeStreamCompleted())),
        ),
    )

    assert not hasattr(fake, "execute")
    assert not hasattr(fake, "authorize")
    assert not callable(proposal)
    text_response = await fake.generate_text(
        model=_model(), request=_request("00000000-0000-0000-0000-000000000010")
    )
    events = [
        event
        async for event in fake.stream_text(
            model=_model(),
            request=_request("00000000-0000-0000-0000-000000000011"),
        )
    ]

    assert text_response.tool_calls == (proposal,)
    assert isinstance(events[0], ToolCallProposed)
    assert events[0].proposal == proposal


def test_fake_wires_to_registry_and_router_without_invocation() -> None:
    fake = ScriptedFakeProvider()
    binding = ProviderBinding(
        text_generation=fake,
        text_streaming=fake,
        structured_output=fake,
    )
    descriptor = ModelDescriptor(
        identity=_model(),
        capabilities=frozenset(
            {
                Capability.TEXT_GENERATION,
                Capability.TEXT_STREAMING,
                Capability.STRUCTURED_OUTPUT,
                Capability.TOOL_CALLING,
            }
        ),
        execution_location=ExecutionLocation.LOCAL,
    )
    registry = ModelRegistry()
    registry.register(ModelRegistration(descriptor, binding))

    route = CapabilityRouter(registry).route(
        AIRequestRequirements(
            required_capabilities=frozenset({Capability.TEXT_GENERATION}),
            preferred_capabilities=frozenset(),
            locality=DataLocality.LOCAL_ONLY,
        )
    )

    assert route.descriptor == descriptor
    assert route.binding == binding
    assert fake.invocations() == ()
