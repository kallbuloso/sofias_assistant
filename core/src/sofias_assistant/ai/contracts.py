"""Provider-independent contracts for AI inference boundaries."""

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from uuid import UUID


class Capability(StrEnum):
    """AI capabilities required for the initial text-conversation gate."""

    TEXT_GENERATION = "text_generation"
    TEXT_STREAMING = "text_streaming"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"


class DataLocality(StrEnum):
    """Data policy requested by an AI operation."""

    LOCAL_ONLY = "local_only"
    CLOUD_ALLOWED = "cloud_allowed"
    CLOUD_PREFERRED = "cloud_preferred"


class ExecutionLocation(StrEnum):
    """Where a model executes, independent from a request's data policy."""

    LOCAL = "local"
    CLOUD = "cloud"


class AIMessageRole(StrEnum):
    """Provider-independent role for a textual inference message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ProviderErrorCategory(StrEnum):
    """Safe categories for errors normalized by provider adapters."""

    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMITED = "rate_limited"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_LIMIT_EXCEEDED = "context_limit_exceeded"
    TIMEOUT = "timeout"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _is_json_value(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item) for key, item in value.items()
        )
    return False


def _require_json_value(value: object, field_name: str) -> None:
    if not _is_json_value(value):
        raise ValueError(f"{field_name} must contain only JSON-compatible values")


def _require_non_negative_token_count(value: int | None, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"{field_name} must be a non-negative integer when provided")
    if value is not None and value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer when provided")


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Provider/model identifier that never substitutes for a Sofia identity."""

    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        _require_non_blank(self.provider_id, "provider_id")
        _require_non_blank(self.model_id, "model_id")


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Declared static characteristics of a model, without runtime state."""

    identity: ModelIdentity
    capabilities: frozenset[Capability]
    execution_location: ExecutionLocation
    context_window: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ModelIdentity):
            raise ValueError("identity must be a ModelIdentity")
        if not isinstance(self.capabilities, frozenset) or not all(
            isinstance(capability, Capability) for capability in self.capabilities
        ):
            raise ValueError("capabilities must be a frozenset of Capability values")
        if not isinstance(self.execution_location, ExecutionLocation):
            raise ValueError("execution_location must be an ExecutionLocation")
        if self.context_window is not None and (
            isinstance(self.context_window, bool)
            or not isinstance(self.context_window, int)
            or self.context_window <= 0
        ):
            raise ValueError("context_window must be greater than zero when provided")


@dataclass(frozen=True, slots=True)
class AIRequestRequirements:
    """Required and preferred capabilities plus a mandatory data policy."""

    required_capabilities: frozenset[Capability]
    preferred_capabilities: frozenset[Capability]
    locality: DataLocality

    def __post_init__(self) -> None:
        capability_sets = (
            self.required_capabilities,
            self.preferred_capabilities,
        )
        if not all(
            isinstance(capabilities, frozenset)
            and all(isinstance(capability, Capability) for capability in capabilities)
            for capabilities in capability_sets
        ):
            raise ValueError("capabilities must be frozensets of Capability values")
        if self.required_capabilities & self.preferred_capabilities:
            raise ValueError("required and preferred capabilities must not overlap")
        if not isinstance(self.locality, DataLocality):
            raise ValueError("locality must be a DataLocality")


@dataclass(frozen=True, slots=True)
class AIMessage:
    """One ordered, provider-independent text message."""

    role: AIMessageRole
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, AIMessageRole):
            raise ValueError("role must be an AIMessageRole")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")


@dataclass(frozen=True, slots=True)
class AIRequest:
    """Core-owned textual inference request without provider-native objects."""

    request_id: UUID
    messages: tuple[AIMessage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID):
            raise ValueError("request_id must be a UUID")
        if not isinstance(self.messages, tuple) or not all(
            isinstance(message, AIMessage) for message in self.messages
        ):
            raise ValueError("messages must be a tuple of AIMessage values")


@dataclass(frozen=True, slots=True)
class ProviderResponseMetadata:
    """Safe correlation metadata; provider IDs are never Core identities."""

    request_id: UUID
    model: ModelIdentity
    provider_request_id: str | None = None
    provider_session_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID):
            raise ValueError("request_id must be a UUID")
        if not isinstance(self.model, ModelIdentity):
            raise ValueError("model must be a ModelIdentity")
        if self.provider_request_id is not None:
            _require_non_blank(self.provider_request_id, "provider_request_id")
        if self.provider_session_id is not None:
            _require_non_blank(self.provider_session_id, "provider_session_id")


@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    """An inert, normalized provider proposal; it grants no execution authority."""

    call_id: str
    name: str
    arguments: JsonValue

    def __post_init__(self) -> None:
        _require_non_blank(self.call_id, "call_id")
        _require_non_blank(self.name, "name")
        _require_json_value(self.arguments, "arguments")


@dataclass(frozen=True, slots=True)
class UsageMetadata:
    """Optional normalized textual token counts reported by a provider."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None

    def __post_init__(self) -> None:
        _require_non_negative_token_count(self.input_tokens, "input_tokens")
        _require_non_negative_token_count(self.output_tokens, "output_tokens")
        _require_non_negative_token_count(self.cached_tokens, "cached_tokens")


@dataclass(frozen=True, slots=True)
class StructuredOutputSpec:
    """Provider-independent JSON Schema request for structured output."""

    name: str
    schema: JsonObject

    def __post_init__(self) -> None:
        _require_non_blank(self.name, "name")
        if not isinstance(self.schema, dict):
            raise ValueError("schema must be a JSON object")
        _require_json_value(self.schema, "schema")


@dataclass(frozen=True, slots=True)
class StructuredOutputResult:
    """Normalized structured value returned with safe response metadata."""

    value: JsonValue
    metadata: ProviderResponseMetadata
    usage: UsageMetadata | None = None

    def __post_init__(self) -> None:
        _require_json_value(self.value, "value")
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if self.usage is not None and not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata when provided")


@dataclass(frozen=True, slots=True)
class TextResponse:
    """Normalized non-streaming text response with inert ToolCall proposals."""

    text: str
    metadata: ProviderResponseMetadata
    tool_calls: tuple[ToolCallProposal, ...] = ()
    usage: UsageMetadata | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(tool_call, ToolCallProposal) for tool_call in self.tool_calls
        ):
            raise ValueError("tool_calls must be a tuple of ToolCallProposal values")
        if self.usage is not None and not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata when provided")


@dataclass(frozen=True, slots=True)
class ProviderError:
    """Normalized provider failure with a safe message only."""

    category: ProviderErrorCategory
    safe_message: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.category, ProviderErrorCategory):
            raise ValueError("category must be a ProviderErrorCategory")
        _require_non_blank(self.safe_message, "safe_message")
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a bool")


class ProviderInvocationError(RuntimeError):
    """Exception wrapper that exposes only a normalized provider failure."""

    def __init__(self, error: ProviderError) -> None:
        self.error = error
        super().__init__(error.safe_message)


@dataclass(frozen=True, slots=True)
class TextDelta:
    """Non-terminal ordered partial text for one provider request."""

    metadata: ProviderResponseMetadata
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")


@dataclass(frozen=True, slots=True)
class ToolCallProposed:
    """Non-terminal event that carries an inert ToolCallProposal."""

    metadata: ProviderResponseMetadata
    proposal: ToolCallProposal

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if not isinstance(self.proposal, ToolCallProposal):
            raise ValueError("proposal must be a ToolCallProposal")


@dataclass(frozen=True, slots=True)
class UsageUpdated:
    """Non-terminal usage report for one provider request."""

    metadata: ProviderResponseMetadata
    usage: UsageMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata")


@dataclass(frozen=True, slots=True)
class ProviderCompleted:
    """Successful terminal event; no later event is valid for this stream."""

    metadata: ProviderResponseMetadata
    usage: UsageMetadata | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if self.usage is not None and not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata when provided")


@dataclass(frozen=True, slots=True)
class ProviderFailed:
    """Failure terminal event; no later event is valid for this stream."""

    metadata: ProviderResponseMetadata
    error: ProviderError

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, ProviderResponseMetadata):
            raise ValueError("metadata must be ProviderResponseMetadata")
        if not isinstance(self.error, ProviderError):
            raise ValueError("error must be a ProviderError")


type ProviderStreamEvent = (
    TextDelta | ToolCallProposed | UsageUpdated | ProviderCompleted | ProviderFailed
)


def is_terminal_stream_event(event: ProviderStreamEvent) -> bool:
    """Return whether an event completes a stream successfully or with failure.

    A valid provider stream contains zero or more non-terminal events followed
    by exactly one ProviderCompleted or ProviderFailed event, with no event
    after that terminal event. Conversation Runtime will enforce full sequence
    handling in SA-B008.3.
    """

    return isinstance(event, (ProviderCompleted, ProviderFailed))
