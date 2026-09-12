"""Core-owned, append-oriented execution audit and trace queries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.persistence.models import AuditEntryRecord

_SENSITIVE_KEYS = {
    "password",
    "token",
    "api_key",
    "authorization",
    "bearer",
    "cookie",
    "secret",
    "credential",
}


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One immutable application audit fact."""

    event_type: str
    actor: str
    subject: str
    action: str
    resource: str
    outcome: str
    origin: str
    correlation_id: UUID
    causation_id: UUID | None = None
    authority_context: dict[str, Any] = field(default_factory=dict)
    execution_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    conversation_id: UUID | None = None
    turn_id: UUID | None = None
    task_id: UUID | None = None
    attempt_id: UUID | None = None
    agent_run_id: UUID | None = None
    tool_call_id: UUID | None = None
    policy_decision_id: UUID | None = None
    grant_id: UUID | None = None
    delegation_id: UUID | None = None
    confirmation_id: UUID | None = None
    artifact_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for name, value in (
            ("event_type", self.event_type),
            ("actor", self.actor),
            ("subject", self.subject),
            ("action", self.action),
            ("resource", self.resource),
            ("outcome", self.outcome),
            ("origin", self.origin),
        ):
            if not value.strip():
                raise ValueError(f"audit {name} must not be blank")
        if self.timestamp.tzinfo is None:
            raise ValueError("audit timestamp must be timezone-aware")

    @property
    def safe_metadata(self) -> dict[str, Any]:
        """Return recursively redacted metadata suitable for persistence."""

        return _redact_mapping(self.metadata)


class AuditStore:
    """Persistence boundary for append-only audit facts."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(self, entry: AuditEntry) -> AuditEntry:
        async with self._session_factory() as session:
            session.add(_record(entry))
            await session.commit()
        return entry

    async def list(
        self,
        *,
        correlation_id: UUID | None = None,
        task_id: UUID | None = None,
        attempt_id: UUID | None = None,
        agent_run_id: UUID | None = None,
        tool_call_id: UUID | None = None,
        policy_decision_id: UUID | None = None,
        grant_id: UUID | None = None,
        resource: str | None = None,
        outcome: str | None = None,
        origin: str | None = None,
        tool_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> tuple[AuditEntry, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("audit limit must be between 1 and 1000")
        statement: Select[Any] = select(AuditEntryRecord).order_by(
            AuditEntryRecord.timestamp, AuditEntryRecord.id
        )
        filters = []
        for column, value in (
            (AuditEntryRecord.correlation_id, correlation_id),
            (AuditEntryRecord.task_id, task_id),
            (AuditEntryRecord.attempt_id, attempt_id),
            (AuditEntryRecord.agent_run_id, agent_run_id),
            (AuditEntryRecord.tool_call_id, tool_call_id),
            (AuditEntryRecord.policy_decision_id, policy_decision_id),
            (AuditEntryRecord.grant_id, grant_id),
            (AuditEntryRecord.resource, resource),
            (AuditEntryRecord.outcome, outcome),
            (AuditEntryRecord.origin, origin),
            (AuditEntryRecord.action, tool_name),
        ):
            if value is not None:
                filters.append(column == value)
        if start is not None:
            filters.append(AuditEntryRecord.timestamp >= start)
        if end is not None:
            filters.append(AuditEntryRecord.timestamp <= end)
        if filters:
            statement = statement.where(*filters)
        statement = statement.limit(limit)
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return tuple(_entry(row) for row in result.scalars())


class AuditService:
    """Small composition facade used by execution, task and agent runtimes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.store = AuditStore(session_factory)

    async def record(
        self,
        *,
        event_type: str,
        actor: str,
        subject: str,
        action: str,
        resource: str,
        outcome: str,
        origin: str,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        authority_context: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        **references: UUID | None,
    ) -> AuditEntry:
        entry = AuditEntry(
            event_type=event_type,
            actor=actor,
            subject=subject,
            action=action,
            resource=resource,
            outcome=outcome,
            origin=origin,
            correlation_id=correlation_id,
            causation_id=causation_id,
            authority_context=authority_context or {},
            execution_context=execution_context or {},
            metadata=metadata or {},
            conversation_id=references.get("conversation_id"),
            turn_id=references.get("turn_id"),
            task_id=references.get("task_id"),
            attempt_id=references.get("attempt_id"),
            agent_run_id=references.get("agent_run_id"),
            tool_call_id=references.get("tool_call_id"),
            policy_decision_id=references.get("policy_decision_id"),
            grant_id=references.get("grant_id"),
            delegation_id=references.get("delegation_id"),
            confirmation_id=references.get("confirmation_id"),
            artifact_id=references.get("artifact_id"),
        )
        return await self.store.append(entry)

    async def trace(self, correlation_id: UUID) -> tuple[AuditEntry, ...]:
        return await self.store.list(correlation_id=correlation_id)

    async def query(self, **filters: Any) -> tuple[AuditEntry, ...]:
        return await self.store.list(**filters)


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(sensitive in key_text.lower() for sensitive in _SENSITIVE_KEYS):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _redact_mapping(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_mapping(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _json(value: Any) -> str:
    return json.dumps(_redact_mapping(value), sort_keys=True, separators=(",", ":"))


def _record(entry: AuditEntry) -> AuditEntryRecord:
    return AuditEntryRecord(
        id=entry.id,
        timestamp=entry.timestamp,
        event_type=entry.event_type,
        actor=entry.actor,
        subject=entry.subject,
        action=entry.action,
        resource=entry.resource,
        outcome=entry.outcome,
        origin=entry.origin,
        correlation_id=entry.correlation_id,
        causation_id=entry.causation_id,
        authority_context_json=_json(entry.authority_context),
        execution_context_json=_json(entry.execution_context),
        metadata_json=_json(entry.safe_metadata),
        conversation_id=entry.conversation_id,
        turn_id=entry.turn_id,
        task_id=entry.task_id,
        attempt_id=entry.attempt_id,
        agent_run_id=entry.agent_run_id,
        tool_call_id=entry.tool_call_id,
        policy_decision_id=entry.policy_decision_id,
        grant_id=entry.grant_id,
        delegation_id=entry.delegation_id,
        confirmation_id=entry.confirmation_id,
        artifact_id=entry.artifact_id,
    )


def _entry(record: AuditEntryRecord) -> AuditEntry:
    return AuditEntry(
        id=record.id,
        timestamp=record.timestamp,
        event_type=record.event_type,
        actor=record.actor,
        subject=record.subject,
        action=record.action,
        resource=record.resource,
        outcome=record.outcome,
        origin=record.origin,
        correlation_id=record.correlation_id,
        causation_id=record.causation_id,
        authority_context=json.loads(record.authority_context_json),
        execution_context=json.loads(record.execution_context_json),
        metadata=json.loads(record.metadata_json),
        conversation_id=record.conversation_id,
        turn_id=record.turn_id,
        task_id=record.task_id,
        attempt_id=record.attempt_id,
        agent_run_id=record.agent_run_id,
        tool_call_id=record.tool_call_id,
        policy_decision_id=record.policy_decision_id,
        grant_id=record.grant_id,
        delegation_id=record.delegation_id,
        confirmation_id=record.confirmation_id,
        artifact_id=record.artifact_id,
    )
