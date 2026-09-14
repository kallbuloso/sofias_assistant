"""Assistant-owned value objects for the Sofias Memory Cognitive Memory boundary.

These types mirror only the public wire contract of Sofias Memory v0.7.0
Cognitive Memory (Create/Get/Recall/Supersede/Forget) plus the Assistant's own
operational candidate/operation lifecycle. Sofia's Assistant never imports the
Sofias Memory Python package; Memory is treated strictly as an external HTTP
service and this module is the entire boundary vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

SOURCE_SYSTEM = "sofias-assistant"


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware when provided")


# --------------------------------------------------------------------------
# Wire-level enums (mirror the Sofias Memory v0.7 public contract exactly)
# --------------------------------------------------------------------------


class MemoryType(StrEnum):
    """Cognitive Memory type supported by Gate I6."""

    PROFILE = "profile"
    SEMANTIC = "semantic"


class MemoryOriginKind(StrEnum):
    """Provenance origin kinds defined by the Sofias Memory v0.7 contract."""

    USER_ASSERTED = "user_asserted"
    TOOL_OBSERVED = "tool_observed"
    IMPORTED = "imported"
    INFERRED = "inferred"
    ASSISTANT_GENERATED = "assistant_generated"


class MemoryLifecycle(StrEnum):
    """Public Cognitive Memory lifecycle states."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


_ORIGIN_MINIMUM_FIELDS: dict[MemoryOriginKind, tuple[str, ...]] = {
    MemoryOriginKind.USER_ASSERTED: ("turn_uuid", "source_ref"),
    MemoryOriginKind.IMPORTED: ("source_ref",),
    MemoryOriginKind.INFERRED: ("turn_uuid", "task_uuid", "source_ref"),
    MemoryOriginKind.ASSISTANT_GENERATED: ("turn_uuid", "task_uuid", "source_ref"),
}


@dataclass(frozen=True, slots=True)
class MemoryProvenance:
    """Assistant-supplied provenance for one Cognitive Memory mutation."""

    origin_kind: MemoryOriginKind
    conversation_uuid: UUID | None = None
    turn_uuid: UUID | None = None
    task_uuid: UUID | None = None
    source_ref: str | None = None
    confirmation_ref: str | None = None
    observed_at: datetime | None = None
    source_system: str = SOURCE_SYSTEM

    def __post_init__(self) -> None:
        if not isinstance(self.origin_kind, MemoryOriginKind):
            raise ValueError("origin_kind must be a MemoryOriginKind")
        _require_non_blank(self.source_system, "source_system")
        _require_aware(self.observed_at, "observed_at")
        if self.source_ref is not None:
            _require_non_blank(self.source_ref, "source_ref")
        if self.confirmation_ref is not None:
            _require_non_blank(self.confirmation_ref, "confirmation_ref")
        if self.origin_kind is MemoryOriginKind.TOOL_OBSERVED:
            if self.source_ref is None or self.observed_at is None:
                raise ValueError(
                    "tool_observed provenance requires source_ref and observed_at"
                )
            return
        minimum_fields = _ORIGIN_MINIMUM_FIELDS.get(self.origin_kind)
        if minimum_fields is None:
            return
        if not any(getattr(self, name) is not None for name in minimum_fields):
            raise ValueError(
                f"{self.origin_kind.value} provenance requires at least one of "
                f"{', '.join(minimum_fields)}"
            )


@dataclass(frozen=True, slots=True)
class MemoryItemProvenance:
    """Provenance as returned by Memory on a MemoryItem (nullable after Forget)."""

    origin_kind: MemoryOriginKind
    source_system: str
    conversation_uuid: UUID | None = None
    turn_uuid: UUID | None = None
    task_uuid: UUID | None = None
    source_ref: str | None = None
    confirmation_ref: str | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """Public Cognitive Memory resource returned by every mutation/read.

    `scope`/`content`/`confidence`/`valid_from`/`valid_until` are nullable
    because a FORGOTTEN tombstone destroys them; only `memory_id`,
    `memory_type`, `lifecycle`, `created_at` and the reduced `provenance`
    (origin_kind/source_system only) always survive.
    """

    memory_id: UUID
    memory_type: MemoryType
    lifecycle: MemoryLifecycle
    created_at: datetime
    provenance: MemoryItemProvenance
    scope: str | None = None
    content: str | None = None
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    superseded_at: datetime | None = None
    superseded_by: UUID | None = None
    forgotten_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryRecallItem:
    """One ranked Cognitive Memory recall result."""

    memory: MemoryItem
    relevance: float
    is_current_truth: bool


@dataclass(frozen=True, slots=True)
class MemoryRecallResult:
    """Ordered Cognitive Memory recall response."""

    items: tuple[MemoryRecallItem, ...]


@dataclass(frozen=True, slots=True)
class MemorySupersedeResult:
    """Atomic Supersede outcome: the superseded target and its replacement."""

    old: MemoryItem
    replacement: MemoryItem


_REQUIRED_COGNITIVE_MEMORY_CAPABILITIES = frozenset(
    {
        "cognitive_memory.write",
        "cognitive_memory.get",
        "cognitive_memory.recall",
        "cognitive_memory.supersede",
        "cognitive_memory.forget",
    }
)


@dataclass(frozen=True, slots=True)
class MemoryCapabilities:
    """Negotiated Cognitive Memory compatibility from `GET /api/v1/info`."""

    api_contract_version: str | None
    cognitive_memory_contract_version: str | None
    capabilities: frozenset[str]

    @property
    def supports_cognitive_memory(self) -> bool:
        """Return whether every capability required by Gate I6 is present.

        Never inferred from application SemVer: only the machine contract
        identifier and the explicit capability list are authority.
        """

        return (
            self.api_contract_version == "1"
            and self.cognitive_memory_contract_version == "1"
            and _REQUIRED_COGNITIVE_MEMORY_CAPABILITIES <= self.capabilities
        )


# --------------------------------------------------------------------------
# Request DTOs sent to the Adapter
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateMemoryRequest:
    """Assistant-owned request to create one Cognitive MemoryItem."""

    memory_type: MemoryType
    scope: str
    content: str
    provenance: MemoryProvenance
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.memory_type, MemoryType):
            raise ValueError("memory_type must be a MemoryType")
        _require_non_blank(self.scope, "scope")
        _require_non_blank(self.content, "content")
        if not isinstance(self.provenance, MemoryProvenance):
            raise ValueError("provenance must be a MemoryProvenance")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0 when provided")
        if (
            self.provenance.origin_kind is MemoryOriginKind.INFERRED
            and self.confidence is None
        ):
            raise ValueError("inferred provenance requires confidence")
        _require_aware(self.valid_from, "valid_from")
        _require_aware(self.valid_until, "valid_until")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until <= self.valid_from
        ):
            raise ValueError("valid_until must be strictly after valid_from")


@dataclass(frozen=True, slots=True)
class SupersedeMemoryRequest:
    """Assistant-owned request to atomically replace an ACTIVE MemoryItem."""

    content: str
    provenance: MemoryProvenance
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.content, "content")
        if not isinstance(self.provenance, MemoryProvenance):
            raise ValueError("provenance must be a MemoryProvenance")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0 when provided")
        if (
            self.provenance.origin_kind is MemoryOriginKind.INFERRED
            and self.confidence is None
        ):
            raise ValueError("inferred provenance requires confidence")
        _require_aware(self.valid_from, "valid_from")
        _require_aware(self.valid_until, "valid_until")


@dataclass(frozen=True, slots=True)
class RecallRequest:
    """Assistant-owned typed Cognitive Memory recall request."""

    query: str
    scopes: tuple[str, ...]
    memory_types: tuple[MemoryType, ...] = (MemoryType.PROFILE, MemoryType.SEMANTIC)
    top_k: int = 10
    as_of: datetime | None = None
    include_superseded: bool = False
    min_relevance: float | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.query, "query")
        if not self.scopes or not all(scope.strip() for scope in self.scopes):
            raise ValueError("scopes must contain at least one non-blank scope")
        if not self.memory_types:
            raise ValueError("memory_types must not be empty")
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int):
            raise ValueError("top_k must be an integer")
        if not 1 <= self.top_k <= 50:
            raise ValueError("top_k must be between 1 and 50")
        _require_aware(self.as_of, "as_of")
        if self.min_relevance is not None and not -1.0 <= self.min_relevance <= 1.0:
            raise ValueError("min_relevance must be between -1.0 and 1.0")


# --------------------------------------------------------------------------
# Memory error taxonomy (mirrors ai.contracts.ProviderError's shape)
# --------------------------------------------------------------------------


class MemoryErrorCategory(StrEnum):
    """Safe categories for errors normalized by the Sofias Memory Adapter."""

    INCOMPATIBLE_CONTRACT = "incompatible_contract"
    AUTHENTICATION_ERROR = "authentication_error"
    UNAVAILABLE = "unavailable"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    STATE_CONFLICT = "state_conflict"
    VALIDATION_ERROR = "validation_error"
    PROTOCOL_ERROR = "protocol_error"


@dataclass(frozen=True, slots=True)
class MemoryError:
    """Normalized Memory boundary failure with a safe message only."""

    category: MemoryErrorCategory
    safe_message: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.category, MemoryErrorCategory):
            raise ValueError("category must be a MemoryErrorCategory")
        _require_non_blank(self.safe_message, "safe_message")
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a bool")


class MemoryInvocationError(RuntimeError):
    """Exception wrapper that exposes only a normalized Memory failure."""

    def __init__(self, error: MemoryError) -> None:
        self.error = error
        super().__init__(error.safe_message)


# --------------------------------------------------------------------------
# Assistant-owned MemoryCandidate / MemoryOperation lifecycle
# --------------------------------------------------------------------------


class MemoryCandidateDecisionStatus(StrEnum):
    """Assistant-owned cognitive decision state for one MemoryCandidate."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MemoryCandidatePersistenceStatus(StrEnum):
    """Assistant-owned persistence attempt state for one MemoryCandidate."""

    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Assistant-owned durable candidate; never a copy of MemoryItem authority."""

    id: UUID
    memory_type: MemoryType
    scope: str
    origin_kind: MemoryOriginKind
    decision_status: MemoryCandidateDecisionStatus
    persistence_status: MemoryCandidatePersistenceStatus
    created_at: datetime
    updated_at: datetime
    conversation_id: UUID | None = None
    turn_id: UUID | None = None
    task_id: UUID | None = None
    source_ref: str | None = None
    confirmation_ref: str | None = None
    observed_at: datetime | None = None
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    cloud_context_eligible: bool = False
    content: str | None = None
    memory_id: UUID | None = None
    safe_failure_code: str | None = None
    decided_at: datetime | None = None
    persisted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.memory_type, MemoryType):
            raise ValueError("memory_type must be a MemoryType")
        _require_non_blank(self.scope, "scope")
        if not isinstance(self.origin_kind, MemoryOriginKind):
            raise ValueError("origin_kind must be a MemoryOriginKind")
        if not isinstance(self.decision_status, MemoryCandidateDecisionStatus):
            raise ValueError("decision_status must be a MemoryCandidateDecisionStatus")
        if not isinstance(self.persistence_status, MemoryCandidatePersistenceStatus):
            raise ValueError(
                "persistence_status must be a MemoryCandidatePersistenceStatus"
            )


class MemoryOperationKind(StrEnum):
    """Kind of durable Assistant-owned Cognitive Memory mutation operation."""

    SUPERSEDE = "SUPERSEDE"
    FORGET = "FORGET"


class MemoryOperationStatus(StrEnum):
    """Assistant-owned lifecycle for one durable Memory mutation operation."""

    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class MemoryOperation:
    """Assistant-owned durable identity for one Supersede/Forget mutation."""

    id: UUID
    kind: MemoryOperationKind
    target_memory_id: UUID
    status: MemoryOperationStatus
    created_at: datetime
    updated_at: datetime
    replacement_candidate_id: UUID | None = None
    replacement_memory_id: UUID | None = None
    safe_failure_code: str | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MemoryOperationKind):
            raise ValueError("kind must be a MemoryOperationKind")
        if not isinstance(self.status, MemoryOperationStatus):
            raise ValueError("status must be a MemoryOperationStatus")
