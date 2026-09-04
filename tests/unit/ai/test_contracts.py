"""Unit tests for provider-independent AI contracts."""

from dataclasses import fields
from uuid import uuid4

import pytest

from sofias_assistant.ai import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    AIRequestRequirements,
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
    StructuredOutputResult,
    StructuredOutputSpec,
    TextDelta,
    TextResponse,
    ToolCallProposal,
    ToolCallProposed,
    UsageMetadata,
    UsageUpdated,
    is_terminal_stream_event,
)


@pytest.fixture
def model() -> ModelIdentity:
    return ModelIdentity(provider_id="test-provider", model_id="text-model")


@pytest.fixture
def metadata(model: ModelIdentity) -> ProviderResponseMetadata:
    return ProviderResponseMetadata(request_id=uuid4(), model=model)


def test_capability_baseline_contains_only_gate_i2_capabilities() -> None:
    assert set(Capability) == {
        Capability.TEXT_GENERATION,
        Capability.TEXT_STREAMING,
        Capability.STRUCTURED_OUTPUT,
        Capability.TOOL_CALLING,
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
