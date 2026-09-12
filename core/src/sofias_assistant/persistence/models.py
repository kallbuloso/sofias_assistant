"""SQLAlchemy models for the Operational Store."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
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
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


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
