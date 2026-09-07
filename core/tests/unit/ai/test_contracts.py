"""Unit tests for provider-independent AI contracts."""

from dataclasses import FrozenInstanceError, fields
from uuid import uuid4

import pytest

from sofias_assistant.ai import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    AIRequestRequirements,
    AssistantAudioChunk,
    AssistantTranscriptFinal,
    AssistantTranscriptPartial,
    AudioEncoding,
    AudioFormat,
    AudioInputFrame,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ProviderCompleted,
    ProviderError,
    ProviderErrorCategory,
    ProviderFailed,
    ProviderInvocationError,
    ProviderResponseMetadata,
    RealtimeContextSeed,
    RealtimeInteractionId,
    RealtimeResponseCompleted,
    RealtimeResponseFailed,
    RealtimeSessionFailed,
    RealtimeSessionId,
    RealtimeSessionRequest,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextDelta,
    TextResponse,
    ToolCallProposal,
    ToolCallProposed,
    UsageMetadata,
    UsageUpdated,
    UserTranscriptFinal,
    UserTranscriptPartial,
    is_terminal_realtime_event,
    is_terminal_stream_event,
)


@pytest.fixture
def model() -> ModelIdentity:
    return ModelIdentity(provider_id="test-provider", model_id="text-model")


@pytest.fixture
def metadata(model: ModelIdentity) -> ProviderResponseMetadata:
    return ProviderResponseMetadata(request_id=uuid4(), model=model)


def test_capability_baseline_contains_text_and_realtime_capabilities() -> None:
    assert set(Capability) == {
        Capability.TEXT_GENERATION,
        Capability.TEXT_STREAMING,
        Capability.STRUCTURED_OUTPUT,
        Capability.TOOL_CALLING,
        Capability.REALTIME,
        Capability.AUDIO_INPUT,
        Capability.AUDIO_OUTPUT,
    }


def test_data_locality_is_distinct_from_model_execution_location(
    model: ModelIdentity,
) -> None:
    assert set(DataLocality) == {
        DataLocality.LOCAL_ONLY,
        DataLocality.CLOUD_ALLOWED,
        DataLocality.CLOUD_PREFERRED,
    }
    assert set(ExecutionLocation) == {
        ExecutionLocation.LOCAL,
        ExecutionLocation.CLOUD,
    }

    descriptor = ModelDescriptor(
        identity=model,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
        execution_location=ExecutionLocation.LOCAL,
    )

    assert descriptor.execution_location is ExecutionLocation.LOCAL
    assert isinstance(DataLocality.CLOUD_PREFERRED, DataLocality)
    assert not isinstance(DataLocality.CLOUD_PREFERRED, ExecutionLocation)


@pytest.mark.parametrize(
    "provider_id, model_id",
    [("", "model"), ("   ", "model"), ("provider", ""), ("provider", "\t")],
)
def test_model_identity_rejects_blank_ids(provider_id: str, model_id: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        ModelIdentity(provider_id=provider_id, model_id=model_id)


def test_model_identity_preserves_valid_ids_without_case_normalization() -> None:
    identity = ModelIdentity(provider_id="Provider-A", model_id="Model/Preview")

    assert identity.provider_id == "Provider-A"
    assert identity.model_id == "Model/Preview"


@pytest.mark.parametrize("context_window", [None, 1, 16_384])
def test_model_descriptor_accepts_unknown_or_positive_context_window(
    model: ModelIdentity, context_window: int | None
) -> None:
    descriptor = ModelDescriptor(
        identity=model,
        capabilities=frozenset(),
        execution_location=ExecutionLocation.CLOUD,
        context_window=context_window,
    )

    assert descriptor.context_window == context_window


@pytest.mark.parametrize("context_window", [0, -1])
def test_model_descriptor_rejects_non_positive_context_window(
    model: ModelIdentity, context_window: int
) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        ModelDescriptor(
            identity=model,
            capabilities=frozenset(),
            execution_location=ExecutionLocation.CLOUD,
            context_window=context_window,
        )


def test_absent_capability_is_not_implicitly_supported(model: ModelIdentity) -> None:
    descriptor = ModelDescriptor(
        identity=model,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
        execution_location=ExecutionLocation.CLOUD,
    )

    assert Capability.TEXT_STREAMING not in descriptor.capabilities


def test_requirements_store_distinct_frozensets_and_locality() -> None:
    requirements = AIRequestRequirements(
        required_capabilities=frozenset({Capability.TEXT_GENERATION}),
        preferred_capabilities=frozenset({Capability.TEXT_STREAMING}),
        locality=DataLocality.CLOUD_ALLOWED,
    )

    assert requirements.required_capabilities == frozenset({Capability.TEXT_GENERATION})
    assert requirements.preferred_capabilities == frozenset({Capability.TEXT_STREAMING})
    assert requirements.locality is DataLocality.CLOUD_ALLOWED


def test_requirements_reject_overlapping_capabilities() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        AIRequestRequirements(
            required_capabilities=frozenset({Capability.TEXT_GENERATION}),
            preferred_capabilities=frozenset({Capability.TEXT_GENERATION}),
            locality=DataLocality.LOCAL_ONLY,
        )


def test_request_preserves_core_uuid_and_ordered_messages() -> None:
    request_id = uuid4()
    messages = (
        AIMessage(AIMessageRole.SYSTEM, "Be concise."),
        AIMessage(AIMessageRole.USER, "Hello"),
    )

    request = AIRequest(request_id=request_id, messages=messages)

    assert request.request_id == request_id
    assert request.messages == messages


@pytest.mark.parametrize(
    "arguments",
    [
        {"path": "report.txt", "options": [True, None, 3]},
        ["item", {"nested": 1.5}],
        "scalar",
    ],
)
def test_tool_call_proposal_accepts_json_compatible_arguments(
    arguments: object,
) -> None:
    proposal = ToolCallProposal(
        call_id="call-1",
        name="filesystem.read",
        arguments=arguments,  # type: ignore[arg-type]
    )

    assert proposal.arguments == arguments
    assert [field.name for field in fields(ToolCallProposal)] == [
        "call_id",
        "name",
        "arguments",
    ]


@pytest.mark.parametrize("arguments", [{"bad": {1, 2}}, {1: "bad"}, object()])
def test_tool_call_proposal_rejects_non_json_arguments(arguments: object) -> None:
    with pytest.raises(ValueError, match="JSON-compatible"):
        ToolCallProposal(call_id="call-1", name="tool", arguments=arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, 0, 7])
def test_usage_metadata_accepts_optional_non_negative_counts(value: int | None) -> None:
    usage = UsageMetadata(input_tokens=value, output_tokens=value, cached_tokens=value)

    assert usage.input_tokens == value


@pytest.mark.parametrize("value", [-1, -2])
def test_usage_metadata_rejects_negative_counts(value: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        UsageMetadata(input_tokens=value)


def test_structured_output_contract_is_provider_independent(
    metadata: ProviderResponseMetadata,
) -> None:
    spec = StructuredOutputSpec(
        name="answer",
        schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )
    result = StructuredOutputResult(value={"answer": "yes"}, metadata=metadata)

    assert spec.schema["type"] == "object"
    assert result.value == {"answer": "yes"}


def test_normalized_error_categories_and_safe_exception_representation() -> None:
    assert set(ProviderErrorCategory) == {
        ProviderErrorCategory.AUTHENTICATION_ERROR,
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.MODEL_UNAVAILABLE,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        ProviderErrorCategory.INVALID_REQUEST,
        ProviderErrorCategory.CONTEXT_LIMIT_EXCEEDED,
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.CAPABILITY_UNAVAILABLE,
    }

    error = ProviderError(
        category=ProviderErrorCategory.AUTHENTICATION_ERROR,
        safe_message="Provider authentication failed",
        retryable=False,
    )
    sentinel = "client-ai-secret-sentinel"
    try:
        raise RuntimeError(sentinel)
    except RuntimeError as cause:
        try:
            raise ProviderInvocationError(error) from cause
        except ProviderInvocationError as exception:
            assert sentinel not in repr(error)
            assert sentinel not in str(exception)
            assert sentinel not in repr(exception)
            assert str(exception) == "Provider authentication failed"


def test_text_response_contains_only_normalized_contract_values(
    metadata: ProviderResponseMetadata,
) -> None:
    response = TextResponse(
        text="Hello",
        metadata=metadata,
        tool_calls=(ToolCallProposal("call-1", "tool", {"enabled": True}),),
        usage=UsageMetadata(input_tokens=2, output_tokens=1),
    )

    assert response.text == "Hello"
    assert response.tool_calls[0].name == "tool"


def test_stream_taxonomy_and_terminal_semantics(
    metadata: ProviderResponseMetadata,
) -> None:
    proposal = ToolCallProposal("call-1", "tool", {})
    provider_error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        "Provider unavailable",
        retryable=True,
    )
    events = (
        TextDelta(metadata, "Hel"),
        ToolCallProposed(metadata, proposal),
        UsageUpdated(metadata, UsageMetadata(input_tokens=3)),
        ProviderCompleted(metadata),
        ProviderFailed(metadata, provider_error),
    )

    assert not is_terminal_stream_event(events[0])
    assert not is_terminal_stream_event(events[1])
    assert not is_terminal_stream_event(events[2])
    assert is_terminal_stream_event(events[3])
    assert is_terminal_stream_event(events[4])


def _realtime_session_id() -> RealtimeSessionId:
    return RealtimeSessionId(uuid4())


def _realtime_interaction_id() -> RealtimeInteractionId:
    return RealtimeInteractionId(uuid4())


def test_audio_format_is_explicit_and_provider_neutral() -> None:
    audio_format = AudioFormat(AudioEncoding.PCM16, 24_000, 1)

    assert audio_format.encoding is AudioEncoding.PCM16
    assert audio_format.sample_rate_hz == 24_000
    assert audio_format.channels == 1


@pytest.mark.parametrize(
    ("encoding", "sample_rate_hz", "channels", "message"),
    [
        ("pcm16", 24_000, 1, "AudioEncoding"),
        (AudioEncoding.PCM16, 0, 1, "sample_rate_hz"),
        (AudioEncoding.PCM16, 24_000, 0, "channels"),
        (AudioEncoding.PCM16, True, 1, "sample_rate_hz"),
    ],
)
def test_audio_format_rejects_invalid_values(
    encoding: object, sample_rate_hz: int, channels: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        AudioFormat(encoding, sample_rate_hz, channels)  # type: ignore[arg-type]


def test_realtime_request_and_context_seed_are_core_owned_values() -> None:
    seed = RealtimeContextSeed((AIMessage(AIMessageRole.SYSTEM, "Sofia"),), True)
    request = RealtimeSessionRequest(
        realtime_session_id=_realtime_session_id(),
        input_audio_format=AudioFormat(AudioEncoding.PCM16, 24_000, 1),
        output_audio_format=AudioFormat(AudioEncoding.PCM16, 24_000, 1),
        context_seed=seed,
    )

    assert request.context_seed is seed
    with pytest.raises(FrozenInstanceError):
        request.context_seed = seed  # type: ignore[misc]
    with pytest.raises(ValueError, match="tuple of AIMessage"):
        RealtimeContextSeed(("not-a-message",), True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="RealtimeSessionId"):
        RealtimeSessionRequest(
            realtime_session_id="not-a-uuid",  # type: ignore[arg-type]
            input_audio_format=request.input_audio_format,
            output_audio_format=request.output_audio_format,
            context_seed=seed,
        )


def test_audio_input_frame_requires_ordered_non_empty_immutable_bytes() -> None:
    frame = AudioInputFrame(sequence=0, audio=b"audio")

    assert frame.sequence == 0
    assert frame.audio == b"audio"
    with pytest.raises(ValueError, match="non-empty"):
        AudioInputFrame(sequence=1, audio=b"")
    with pytest.raises(ValueError, match="sequence"):
        AudioInputFrame(sequence=-1, audio=b"audio")
    with pytest.raises(ValueError, match="sequence"):
        AudioInputFrame(sequence=True, audio=b"audio")


def test_realtime_events_have_explicit_identity_sequence_and_terminal_semantics() -> (
    None
):
    session_id = _realtime_session_id()
    interaction_id = _realtime_interaction_id()
    audio_format = AudioFormat(AudioEncoding.PCM16, 24_000, 1)
    error = ProviderError(
        ProviderErrorCategory.PROVIDER_UNAVAILABLE, "Provider unavailable", True
    )
    events = (
        UserTranscriptPartial(session_id, interaction_id, 0, "hel"),
        UserTranscriptFinal(session_id, interaction_id, 1, ""),
        AssistantAudioChunk(session_id, interaction_id, 2, b"audio", audio_format),
        AssistantTranscriptPartial(session_id, interaction_id, 3, "hi"),
        AssistantTranscriptFinal(session_id, interaction_id, 4, "hello"),
        RealtimeResponseCompleted(session_id, interaction_id, 5),
        RealtimeResponseFailed(session_id, interaction_id, 6, error),
        RealtimeSessionFailed(session_id, 7, error),
    )

    assert all(not is_terminal_realtime_event(event) for event in events[:5])
    assert all(is_terminal_realtime_event(event) for event in events[5:])
    with pytest.raises(ValueError, match="non-empty"):
        AssistantAudioChunk(session_id, interaction_id, 8, b"", audio_format)
    with pytest.raises(ValueError, match="ProviderError"):
        RealtimeResponseFailed(session_id, interaction_id, 8, "failure")  # type: ignore[arg-type]


def test_realtime_event_ids_require_uuid_values_at_runtime() -> None:
    session_id = _realtime_session_id()
    interaction_id = _realtime_interaction_id()

    with pytest.raises(ValueError, match="RealtimeSessionId"):
        UserTranscriptPartial(
            "not-a-uuid",  # type: ignore[arg-type]
            interaction_id,
            0,
            "partial",
        )
    with pytest.raises(ValueError, match="RealtimeInteractionId"):
        UserTranscriptPartial(
            session_id,
            "not-a-uuid",  # type: ignore[arg-type]
            0,
            "partial",
        )
