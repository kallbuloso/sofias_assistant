"""Provider-independent contracts for authorized Tool execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class DecisionOutcome(StrEnum):
    """Exhaustive outcomes produced by the deterministic PolicyEngine."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    REQUIRE_ELEVATION = "REQUIRE_ELEVATION"


class GrantLifetime(StrEnum):
    """MVP authority lifetimes."""

    ONE_SHOT = "ONE_SHOT"
    SESSION = "SESSION"
    UNTIL_REVOKED = "UNTIL_REVOKED"


class GrantStatus(StrEnum):
    """Lifecycle state of a PermissionGrant."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    CONSUMED = "CONSUMED"


class ConfirmationStatus(StrEnum):
    """Lifecycle state of a confirmation request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ToolExecutionMode(StrEnum):
    """Execution modes reserved by the approved architecture."""

    IN_PROCESS = "IN_PROCESS"
    SUBPROCESS = "SUBPROCESS"
    SANDBOX = "SANDBOX"


class TaskStatus(StrEnum):
    """Durable lifecycle states for Core-owned work."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_EXTERNAL = "WAITING_EXTERNAL"
    WAITING_SCHEDULE = "WAITING_SCHEDULE"
    PAUSED = "PAUSED"
    CANCELLING = "CANCELLING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskExecutionStrategy(StrEnum):
    """Explicit choice between a durable Tool task and an Agent run."""

    DIRECT_TOOL = "DIRECT_TOOL"
    WORKFLOW = "WORKFLOW"
    AGENT = "AGENT"


class AgentRunStatus(StrEnum):
    """Lifecycle of one concrete Agent execution."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolSideEffect(StrEnum):
    """Coarse side-effect classification used by policy defaults."""

    NONE = "NONE"
    MUTATING = "MUTATING"


class ArtifactRetention(StrEnum):
    """Artifact retention baseline."""

    TEMPORARY = "TEMPORARY"
    PERSISTENT = "PERSISTENT"


@dataclass(frozen=True, slots=True)
class AuthorityContext:
    """The authenticated subject and explicit session used for narrowing."""

    subject: str
    session_id: UUID | None = None
    root_subject: str | None = None

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("authority subject must not be blank")


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    """Side-effect-free input to the PolicyEngine."""

    subject: str
    capability: str
    operation: str
    resource: str
    authority: AuthorityContext
    constraints: Mapping[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    requires_elevation: bool = False
    grant_id: UUID | None = None
    correlation_id: UUID = field(default_factory=uuid4)
    tool_call_id: UUID | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("subject", self.subject),
            ("capability", self.capability),
            ("operation", self.operation),
            ("resource", self.resource),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        if self.subject != self.authority.subject:
            raise ValueError("policy subject must match authority subject")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Correlatable, versioned result of Policy evaluation."""

    outcome: DecisionOutcome
    reason: str
    request_id: UUID
    policy_version: str = "i4-v1"
    id: UUID = field(default_factory=uuid4)
    grant_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    """Narrow, Core-owned authority that can be consumed or revoked."""

    subject: str
    capability: str
    resource_scope: str
    lifetime: GrantLifetime
    session_id: UUID | None = None
    constraints: Mapping[str, Any] = field(default_factory=dict)
    issued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    issuing_context: Mapping[str, Any] = field(default_factory=dict)
    remaining_uses: int | None = None
    id: UUID = field(default_factory=uuid4)
    status: GrantStatus = GrantStatus.ACTIVE
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.capability.strip():
            raise ValueError("grant subject and capability must not be blank")
        if not self.resource_scope.strip():
            raise ValueError("grant resource scope must not be blank")
        if self.lifetime is GrantLifetime.SESSION and self.session_id is None:
            raise ValueError("SESSION grants require a session_id")
        if self.lifetime is GrantLifetime.ONE_SHOT:
            allowed_uses = (0, 1) if self.status is GrantStatus.CONSUMED else (None, 1)
            if self.remaining_uses not in allowed_uses:
                raise ValueError("ONE_SHOT grants have exactly one remaining use")

    def matches(self, request: PolicyRequest, now: datetime | None = None) -> bool:
        """Return whether this grant authorizes exactly this request scope."""

        current = (now or datetime.now(UTC)).astimezone(UTC)
        if self.status is not GrantStatus.ACTIVE or self.subject != request.subject:
            return False
        if self.capability != request.capability:
            return False
        if not _scope_contains(self.resource_scope, request.resource):
            return False
        if self.expires_at is not None and current >= self.expires_at:
            return False
        if self.lifetime is GrantLifetime.SESSION and (
            self.session_id != request.authority.session_id
        ):
            return False
        return _constraints_match(self.constraints, request.constraints)


@dataclass(frozen=True, slots=True)
class Delegation:
    """Optional narrowed authority for future Task/Agent consumers."""

    subject: str
    objective: str
    resource_scope: str
    authority_scope: str
    constraints: Mapping[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    """An explicit request for exactly one presented authority scope."""

    subject: str
    capability: str
    operation: str
    resource: str
    tool_call_id: UUID
    session_id: UUID | None
    requested_lifetime: GrantLifetime = GrantLifetime.ONE_SHOT
    constraints: Mapping[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
    grant_id: UUID | None = None


ToolHandler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]
ResourceResolver = Callable[[Mapping[str, Any]], str]
InputValidator = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Declarative capability metadata plus a Core-owned handler seam."""

    name: str
    version: str
    description: str
    capability: str
    handler: ToolHandler
    resource_resolver: ResourceResolver
    input_validator: InputValidator | None = None
    side_effect: ToolSideEffect = ToolSideEffect.NONE
    confirmation_required: bool = False
    confirmation_lifetime: GrantLifetime = GrantLifetime.ONE_SHOT
    elevation_required: bool = False
    execution_mode: ToolExecutionMode = ToolExecutionMode.IN_PROCESS
    timeout_seconds: float = 30.0
    idempotent: bool = True
    enabled: bool = True
    subprocess_command: tuple[str, ...] | None = None
    subprocess_cwd: str | None = None
    subprocess_environment: Mapping[str, str] = field(default_factory=dict)
    subprocess_output_limit_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("name", self.name),
            ("version", self.version),
            ("description", self.description),
            ("capability", self.capability),
        ):
            if not value.strip():
                raise ValueError(f"ToolSpec {name} must not be blank")
        if self.timeout_seconds <= 0:
            raise ValueError("ToolSpec timeout_seconds must be positive")
        if self.subprocess_output_limit_bytes <= 0:
            raise ValueError("subprocess_output_limit_bytes must be positive")
        if (
            self.execution_mode is ToolExecutionMode.SUBPROCESS
            and not self.subprocess_command
        ):
            raise ValueError("SUBPROCESS tools require subprocess_command")


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Core-owned normalized call identity and arguments."""

    name: str
    arguments: Mapping[str, Any]
    subject: str
    session_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class Task:
    """Durable work identity and lifecycle snapshot."""

    objective: str
    subject: str
    status: TaskStatus = TaskStatus.QUEUED
    origin: str = "client"
    authority: AuthorityContext | None = None
    conversation_id: UUID | None = None
    delegation_id: UUID | None = None
    execution_strategy: TaskExecutionStrategy = TaskExecutionStrategy.DIRECT_TOOL
    result: Any = None
    error: ToolError | None = None
    cancellation_requested: bool = False
    claimed_by: str | None = None
    claim_expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.objective.strip() or not self.subject.strip():
            raise ValueError("Task objective and subject must not be blank")


@dataclass(frozen=True, slots=True)
class TaskAttempt:
    """Append-only execution attempt evidence for a Task."""

    task_id: UUID
    attempt_number: int
    status: TaskStatus = TaskStatus.QUEUED
    tool_call_id: UUID | None = None
    execution_mode: ToolExecutionMode | None = None
    process_id: int | None = None
    result: Any = None
    error: ToolError | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Versioned, registered Agent capability metadata."""

    name: str
    version: str
    description: str
    required_capabilities: frozenset[str]
    allowed_tools: frozenset[str]
    context_policy: str = "task_minimal"
    provider_requirements: Mapping[str, Any] = field(default_factory=dict)
    runtime_limits: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("Agent identity must not be blank")


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Concrete Agent execution with narrowed context and authority."""

    task_id: UUID
    agent_definition_id: UUID
    agent_definition_version: str
    objective: str
    delegated_context: Mapping[str, Any]
    authority_scope: str
    allowed_tools: frozenset[str]
    status: AgentRunStatus = AgentRunStatus.QUEUED
    workspace: str | None = None
    provider_requirements: Mapping[str, Any] = field(default_factory=dict)
    runtime_limits: Mapping[str, Any] = field(default_factory=dict)
    result: Any = None
    correlation_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class SpecializationRequest:
    """Structured request returned to root instead of nested Agent creation."""

    agent_run_id: UUID
    objective: str
    requested_tools: frozenset[str]
    reason: str
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class ToolError:
    """Structured safe error without raw exception details."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Normalized result of policy evaluation or Tool execution."""

    status: str
    call_id: UUID
    value: Any = None
    error: ToolError | None = None
    decision: PolicyDecision | None = None
    confirmation_id: UUID | None = None
    artifact_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Stable reference to data controlled by ArtifactService."""

    id: UUID
    kind: str
    media_type: str
    size: int
    retention: ArtifactRetention
    created_at: datetime


def _scope_contains(scope: str, resource: str) -> bool:
    return scope == resource or (
        scope.endswith("/*") and resource.startswith(scope[:-1])
    )


def _constraints_match(
    granted: Mapping[str, Any], requested: Mapping[str, Any]
) -> bool:
    return all(requested.get(key) == value for key, value in granted.items())
