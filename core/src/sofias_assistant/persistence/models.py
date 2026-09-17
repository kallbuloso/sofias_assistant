"""SQLAlchemy models for the Operational Store."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sofias_assistant.conversation.models import TurnInputModality, TurnStatus
from sofias_assistant.persistence.types import UTCDateTime


class Base(DeclarativeBase):
    """Base class for future Operational Store models."""


class EventRecord(Base):
    """Selective durable delivery outbox, not historical domain state."""

    __tablename__ = "runtime_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','DISPATCHING','DELIVERED','FAILED','CANCELLED')"
        ),
        Index("ix_runtime_events_pending", "status", "available_at"),
        Index("ix_runtime_events_cause_type", "causation_id", "type", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    type: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload_json: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    owner: Mapped[UUID | None] = mapped_column(Uuid)
    attempts: Mapped[int] = mapped_column(default=0)
    completed_handlers_json: Mapped[str] = mapped_column(Text, default="[]")


class ScheduleRecord(Base):
    """Timing intent and a durable continuation reference, never a callable."""

    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','COMPLETED','CANCELLED')"),
        CheckConstraint("kind IN ('REMINDER','TASK_WAKEUP')"),
        CheckConstraint("recurrence IN ('ONCE','INTERVAL','DAILY')"),
        CheckConstraint(
            "(recurrence = 'INTERVAL' AND interval_seconds IS NOT NULL "
            "AND interval_seconds BETWEEN 1 AND 31622400) OR "
            "(recurrence != 'INTERVAL' AND interval_seconds IS NULL)"
        ),
        Index("ix_schedules_due", "status", "next_run_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(255))
    reminder: Mapped[str] = mapped_column(String(1024))
    timezone: Mapped[str] = mapped_column(String(128))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    recurrence: Mapped[str] = mapped_column(String(32))
    interval_seconds: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"))
    tool_call_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("tool_calls.id"))
    grant_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_event_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("runtime_events.id")
    )


class NotificationRecord(Base):
    """Durable user attention; delivery is not acknowledgement or approval."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("state IN ('PENDING','ACKNOWLEDGED')"),
        Index("ix_notifications_pending", "state", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runtime_events.id"), unique=True
    )
    type: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(128))
    action_reference: Mapped[UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    state: Mapped[str] = mapped_column(String(32), default="PENDING")
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RuntimeSessionStatus(StrEnum):
    """Lifecycle states persisted for a runtime session."""

    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    INTERRUPTED = "INTERRUPTED"


class RuntimeSession(Base):
    """Persistent marker for a single runtime process session."""

    __tablename__ = "runtime_sessions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[RuntimeSessionStatus] = mapped_column(
        SqlEnum(
            RuntimeSessionStatus,
            name="runtime_session_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    application_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ApplicationSetting(Base):
    """Operational setting stored as serialized JSON text."""

    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ConversationRecord(Base):
    """ORM record for a Core-owned durable Conversation."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_updated_at_id", "updated_at", "id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class TurnRecord(Base):
    """ORM record for a durable ordered Turn within a Conversation."""

    __tablename__ = "turns"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_turns_sequence_at_least_one"),
        UniqueConstraint(
            "conversation_id", "sequence", name="uq_turns_conversation_sequence"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[TurnStatus] = mapped_column(
        SqlEnum(
            TurnStatus,
            name="turn_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    input_modality: Mapped[TurnInputModality] = mapped_column(
        SqlEnum(
            TurnInputModality,
            name="turn_input_modality",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    cloud_context_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    user_text: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_request_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PermissionGrantRecord(Base):
    """Durable, revocable authority owned by the Core."""

    __tablename__ = "permission_grants"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    capability: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_scope: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    lifetime: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    issuing_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    remaining_uses: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class DelegationRecord(Base):
    """Durable optional narrowed authority contract."""

    __tablename__ = "delegations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    resource_scope: Mapped[str] = mapped_column(Text, nullable=False)
    authority_scope: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ConfirmationRequestRecord(Base):
    """Durable pending confirmation with an exact requested scope."""

    __tablename__ = "confirmation_requests"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    capability: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    requested_lifetime: Mapped[str] = mapped_column(String(32), nullable=False)
    constraints_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    grant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class PolicyDecisionRecord(Base):
    """Persisted policy evidence for future audit correlation."""

    __tablename__ = "policy_decisions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ToolCallRecord(Base):
    """Durable normalized ToolCall lifecycle marker."""

    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    confirmation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ArtifactRecord(Base):
    """Metadata for a Core-controlled artifact blob."""

    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    retention: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class TaskRecord(Base):
    """Durable Core-owned Task lifecycle and claim marker."""

    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    authority_json: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    delegation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    execution_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class TaskAttemptRecord(Base):
    """Append-only attempt evidence for one Task."""

    __tablename__ = "task_attempts"
    __table_args__ = (UniqueConstraint("task_id", "attempt_number"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_call_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    execution_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    process_id: Mapped[int | None] = mapped_column(nullable=True)
    grant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    correlation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    causation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class AgentDefinitionRecord(Base):
    """Durable normalized Agent registry metadata."""

    __tablename__ = "agent_definitions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_capabilities_json: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_policy: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_requirements_json: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_limits_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __table_args__ = (UniqueConstraint("name", "version"),)


class AgentRunRecord(Base):
    """Durable AgentRun lifecycle and narrowed authority evidence."""

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    agent_definition_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    agent_definition_version: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    delegated_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    authority_scope: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_tools_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    workspace: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_requirements_json: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_limits_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditEntryRecord(Base):
    """Append-only structured evidence for consequential Core actions."""

    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entries_correlation_id", "correlation_id"),
        Index("ix_audit_entries_task_id", "task_id"),
        Index("ix_audit_entries_timestamp", "timestamp"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    authority_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    execution_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    agent_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    tool_call_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    policy_decision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    grant_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    delegation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    confirmation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    artifact_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    memory_candidate_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    memory_operation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    memory_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class MemoryCandidateRecord(Base):
    """Assistant-owned durable MemoryCandidate; never a MemoryItem replica."""

    __tablename__ = "memory_candidates"
    __table_args__ = (
        CheckConstraint("memory_type IN ('profile','semantic')"),
        CheckConstraint(
            "origin_kind IN ('user_asserted','tool_observed','imported',"
            "'inferred','assistant_generated')"
        ),
        CheckConstraint("decision_status IN ('PENDING','APPROVED','REJECTED')"),
        CheckConstraint(
            "persistence_status IN ('NOT_REQUESTED','PENDING','SUCCEEDED','FAILED')"
        ),
        Index("ix_memory_candidates_conversation_id", "conversation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False)
    persistence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    turn_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confirmation_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cloud_context_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    safe_failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    persisted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ProviderConfigurationRecord(Base):
    """Non-secret AI provider configuration (Amendment 0003 SS10, Gate I15)."""

    __tablename__ = "ai_provider_configurations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_location: Mapped[str] = mapped_column(String(16), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ModelCatalogEntryRecord(Base):
    """Non-secret catalog entry keyed by (provider_id, model_id) identity."""

    __tablename__ = "ai_model_catalog_entries"
    __table_args__ = (UniqueConstraint("provider_id", "model_id"),)

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    provider_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("ai_provider_configurations.id"), nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    execution_location: Mapped[str] = mapped_column(String(16), nullable=False)
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class InferenceProfileRecord(Base):
    """Persistent workload profile (Contract v1 SS21)."""

    __tablename__ = "ai_inference_profiles"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_capabilities_json: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_capabilities_json: Mapped[str] = mapped_column(Text, nullable=False)
    locality: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fallback_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ProfileModelBindingRecord(Base):
    """Ordered preference binding a profile to one candidate model."""

    __tablename__ = "ai_profile_model_bindings"
    __table_args__ = (UniqueConstraint("profile_key", "provider_id", "model_id"),)

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    profile_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_inference_profiles.key"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MemoryOperationRecord(Base):
    """Assistant-owned durable identity for one Supersede/Forget mutation."""

    __tablename__ = "memory_operations"
    __table_args__ = (
        CheckConstraint("kind IN ('SUPERSEDE','FORGET')"),
        CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED')"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_memory_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    replacement_candidate_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    replacement_memory_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    safe_failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
