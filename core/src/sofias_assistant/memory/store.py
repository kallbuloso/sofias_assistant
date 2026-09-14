"""Explicit persistence boundary for Assistant-owned Cognitive Memory runtime state.

Only operational state lives here: MemoryCandidate/MemoryOperation lifecycle,
opaque `memory_id` references, and enough correlation to recover after a
crash. No embedding, ranking, or authoritative MemoryItem content is ever
cached here (Slice 05 invariants).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.memory.models import (
    MemoryCandidate,
    MemoryCandidateDecisionStatus,
    MemoryCandidatePersistenceStatus,
    MemoryOperation,
    MemoryOperationKind,
    MemoryOperationStatus,
    MemoryOriginKind,
    MemoryType,
)
from sofias_assistant.persistence.models import (
    MemoryCandidateRecord,
    MemoryOperationRecord,
)


class MemoryStore:
    """Persist MemoryCandidate/MemoryOperation state with short-lived sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_candidate(self, candidate: MemoryCandidate) -> None:
        async with self._session_factory() as session:
            session.add(_candidate_record(candidate))
            await session.commit()

    async def get_candidate(self, candidate_id: UUID) -> MemoryCandidate | None:
        async with self._session_factory() as session:
            record = await session.get(MemoryCandidateRecord, candidate_id)
            return _candidate_from_record(record) if record is not None else None

    async def update_candidate(self, candidate: MemoryCandidate) -> None:
        async with self._session_factory() as session:
            record = await session.get(MemoryCandidateRecord, candidate.id)
            if record is None:
                raise KeyError("MemoryCandidate not found")
            for key, value in _candidate_record_values(candidate).items():
                setattr(record, key, value)
            await session.commit()

    async def save_operation(self, operation: MemoryOperation) -> None:
        async with self._session_factory() as session:
            session.add(_operation_record(operation))
            await session.commit()

    async def get_operation(self, operation_id: UUID) -> MemoryOperation | None:
        async with self._session_factory() as session:
            record = await session.get(MemoryOperationRecord, operation_id)
            return _operation_from_record(record) if record is not None else None

    async def update_operation(self, operation: MemoryOperation) -> None:
        async with self._session_factory() as session:
            record = await session.get(MemoryOperationRecord, operation.id)
            if record is None:
                raise KeyError("MemoryOperation not found")
            for key, value in _operation_record_values(operation).items():
                setattr(record, key, value)
            await session.commit()


def _candidate_record(candidate: MemoryCandidate) -> MemoryCandidateRecord:
    return MemoryCandidateRecord(id=candidate.id, **_candidate_record_values(candidate))


def _candidate_record_values(candidate: MemoryCandidate) -> dict[str, Any]:
    return {
        "memory_type": candidate.memory_type.value,
        "scope": candidate.scope,
        "origin_kind": candidate.origin_kind.value,
        "decision_status": candidate.decision_status.value,
        "persistence_status": candidate.persistence_status.value,
        "conversation_id": candidate.conversation_id,
        "turn_id": candidate.turn_id,
        "task_id": candidate.task_id,
        "source_ref": candidate.source_ref,
        "confirmation_ref": candidate.confirmation_ref,
        "observed_at": candidate.observed_at,
        "confidence": candidate.confidence,
        "valid_from": candidate.valid_from,
        "valid_until": candidate.valid_until,
        "cloud_context_eligible": candidate.cloud_context_eligible,
        "content": candidate.content,
        "memory_id": candidate.memory_id,
        "safe_failure_code": candidate.safe_failure_code,
        "created_at": candidate.created_at,
        "updated_at": candidate.updated_at,
        "decided_at": candidate.decided_at,
        "persisted_at": candidate.persisted_at,
    }


def _candidate_from_record(record: MemoryCandidateRecord) -> MemoryCandidate:
    return MemoryCandidate(
        id=record.id,
        memory_type=MemoryType(record.memory_type),
        scope=record.scope,
        origin_kind=MemoryOriginKind(record.origin_kind),
        decision_status=MemoryCandidateDecisionStatus(record.decision_status),
        persistence_status=MemoryCandidatePersistenceStatus(record.persistence_status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        conversation_id=record.conversation_id,
        turn_id=record.turn_id,
        task_id=record.task_id,
        source_ref=record.source_ref,
        confirmation_ref=record.confirmation_ref,
        observed_at=record.observed_at,
        confidence=record.confidence,
        valid_from=record.valid_from,
        valid_until=record.valid_until,
        cloud_context_eligible=record.cloud_context_eligible,
        content=record.content,
        memory_id=record.memory_id,
        safe_failure_code=record.safe_failure_code,
        decided_at=record.decided_at,
        persisted_at=record.persisted_at,
    )


def _operation_record(operation: MemoryOperation) -> MemoryOperationRecord:
    return MemoryOperationRecord(id=operation.id, **_operation_record_values(operation))


def _operation_record_values(operation: MemoryOperation) -> dict[str, Any]:
    return {
        "kind": operation.kind.value,
        "target_memory_id": operation.target_memory_id,
        "status": operation.status.value,
        "replacement_candidate_id": operation.replacement_candidate_id,
        "replacement_memory_id": operation.replacement_memory_id,
        "safe_failure_code": operation.safe_failure_code,
        "created_at": operation.created_at,
        "updated_at": operation.updated_at,
        "completed_at": operation.completed_at,
    }


def _operation_from_record(record: MemoryOperationRecord) -> MemoryOperation:
    return MemoryOperation(
        id=record.id,
        kind=MemoryOperationKind(record.kind),
        target_memory_id=record.target_memory_id,
        status=MemoryOperationStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        replacement_candidate_id=record.replacement_candidate_id,
        replacement_memory_id=record.replacement_memory_id,
        safe_failure_code=record.safe_failure_code,
        completed_at=record.completed_at,
    )
