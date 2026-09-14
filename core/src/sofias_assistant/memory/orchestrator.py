"""Assistant-owned Memory Orchestrator: SA-B019.

Coordinates MemoryCandidate lifecycle, Memory Policy, provenance, recall
adaptation, supersession, and precise Forget against a `MemoryProvider`.
Never implements embedding, ranking, or MemoryItem storage itself (those
remain Sofias Memory's authority) and never calls Memory while a SQLite UoW
is open (Amendment 0002 §7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sofias_assistant.context.models import MemoryContextItem
from sofias_assistant.conversation.models import Turn
from sofias_assistant.execution.audit import AuditService
from sofias_assistant.memory.contracts import MemoryCandidateExtractor, MemoryProvider
from sofias_assistant.memory.models import (
    CreateMemoryRequest,
    MemoryCandidate,
    MemoryCandidateDecisionStatus,
    MemoryCandidatePersistenceStatus,
    MemoryCapabilities,
    MemoryInvocationError,
    MemoryItem,
    MemoryOperation,
    MemoryOperationKind,
    MemoryOperationStatus,
    MemoryOriginKind,
    MemoryProvenance,
    MemoryRecallResult,
    MemoryType,
    RecallRequest,
    SupersedeMemoryRequest,
)
from sofias_assistant.memory.policy import MemoryPolicy
from sofias_assistant.memory.store import MemoryStore
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork

_SOURCE_SYSTEM = "sofias-assistant"


class ConversationTurnMismatchError(ValueError):
    """Raised when a referenced Turn does not belong to the given Conversation."""


class MemoryCandidateNotRetryableError(ValueError):
    """Raised when a candidate/operation is not in a retryable state."""


@dataclass(frozen=True, slots=True)
class RememberOutcome:
    """Outcome of one explicit Remember; never reports false success."""

    candidate_id: UUID
    success: bool
    memory_id: UUID | None = None
    safe_failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class SupersedeOutcome:
    """Outcome of one atomic Supersede operation."""

    operation_id: UUID
    success: bool
    old_memory_id: UUID | None = None
    replacement_memory_id: UUID | None = None
    safe_failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class ForgetOutcome:
    """Outcome of one precise Forget operation."""

    operation_id: UUID
    success: bool
    memory_id: UUID | None = None
    safe_failure_code: str | None = None


class MemoryOrchestrator:
    """Assistant-owned coordination of Cognitive Memory usage."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        provider: MemoryProvider,
        policy: MemoryPolicy,
        extractor: MemoryCandidateExtractor,
        audit: AuditService,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        recall_scopes: tuple[str, ...] = ("global",),
        recall_top_k: int = 10,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._policy = policy
        self._extractor = extractor
        self._audit = audit
        self._uow_factory = uow_factory
        self._recall_scopes = recall_scopes
        self._recall_top_k = recall_top_k
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or uuid4

    async def probe(self) -> MemoryCapabilities:
        """Negotiate Cognitive Memory compatibility; raises on failure."""

        return await self._provider.probe_contract()

    async def recall_for_turn(
        self, turn: Turn, *, scopes: tuple[str, ...] | None = None
    ) -> tuple[MemoryContextItem, ...]:
        """Return ranked context for one Turn; degrades to `()` on any failure."""

        request = RecallRequest(
            query=turn.user_text,
            scopes=scopes or self._recall_scopes,
            top_k=self._recall_top_k,
        )
        try:
            result = await self._provider.recall_memories(request)
        except MemoryInvocationError as error:
            await self._audit.record(
                event_type="MEMORY_RECALL_DEGRADED",
                actor=_SOURCE_SYSTEM,
                subject=str(turn.conversation_id),
                action="recall_memories",
                resource="cognitive_memory",
                outcome="degraded",
                origin=_SOURCE_SYSTEM,
                correlation_id=turn.id,
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                metadata={"safe_failure_code": error.error.category.value},
            )
            return ()
        await self._audit.record(
            event_type="MEMORY_RECALL_COMPLETED",
            actor=_SOURCE_SYSTEM,
            subject=str(turn.conversation_id),
            action="recall_memories",
            resource="cognitive_memory",
            outcome="success",
            origin=_SOURCE_SYSTEM,
            correlation_id=turn.id,
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            metadata={"count": len(result.items)},
        )
        return tuple(
            MemoryContextItem(
                memory_id=item.memory.memory_id,
                memory_type=item.memory.memory_type,
                scope=item.memory.scope or "",
                content=item.memory.content or "",
                relevance=item.relevance,
                is_current_truth=item.is_current_truth,
                lifecycle=item.memory.lifecycle,
                origin_kind=item.memory.provenance.origin_kind,
                # Unknown local cloud policy for a recalled item fails closed;
                # never inferred from type/scope/origin/relevance (Slice §46).
                cloud_context_eligible=False,
            )
            for item in result.items
        )

    async def remember(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        memory_type: MemoryType,
        scope: str,
        cloud_context_eligible: bool,
    ) -> RememberOutcome:
        """Explicit USER_ASSERTED Remember: load Turn, extract, decide, persist."""

        turn = await self._load_turn(conversation_id, turn_id)
        now = self._clock()
        candidate_id = self._id_factory()
        normalized_content = await self._extractor.extract(text=turn.user_text)
        candidate = MemoryCandidate(
            id=candidate_id,
            memory_type=memory_type,
            scope=scope,
            origin_kind=MemoryOriginKind.USER_ASSERTED,
            decision_status=MemoryCandidateDecisionStatus.PENDING,
            persistence_status=MemoryCandidatePersistenceStatus.NOT_REQUESTED,
            created_at=now,
            updated_at=now,
            conversation_id=conversation_id,
            turn_id=turn_id,
            cloud_context_eligible=cloud_context_eligible,
            content=normalized_content,
        )
        await self._store.save_candidate(candidate)
        await self._audit.record(
            event_type="MEMORY_CANDIDATE_CREATED",
            actor=_SOURCE_SYSTEM,
            subject=str(conversation_id),
            action="create_candidate",
            resource="memory_candidate",
            outcome="success",
            origin=_SOURCE_SYSTEM,
            correlation_id=candidate_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            memory_candidate_id=candidate_id,
            metadata={"memory_type": memory_type.value, "scope": scope},
        )
        decision = self._policy.evaluate(
            memory_type=memory_type,
            scope=scope,
            origin_kind=MemoryOriginKind.USER_ASSERTED,
            explicit_user_intent=True,
        )
        if not decision.approved:
            rejected = replace(
                candidate,
                decision_status=MemoryCandidateDecisionStatus.REJECTED,
                decided_at=now,
                updated_at=now,
                content=None,
            )
            await self._store.update_candidate(rejected)
            await self._audit.record(
                event_type="MEMORY_CANDIDATE_REJECTED",
                actor=_SOURCE_SYSTEM,
                subject=str(conversation_id),
                action="evaluate_policy",
                resource="memory_candidate",
                outcome="rejected",
                origin=_SOURCE_SYSTEM,
                correlation_id=candidate_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                memory_candidate_id=candidate_id,
                metadata={"reason": decision.reason},
            )
            return RememberOutcome(
                candidate_id=candidate_id,
                success=False,
                safe_failure_code="POLICY_REJECTED",
            )
        approved = replace(
            candidate,
            decision_status=MemoryCandidateDecisionStatus.APPROVED,
            decided_at=now,
            persistence_status=MemoryCandidatePersistenceStatus.PENDING,
            updated_at=now,
        )
        await self._store.update_candidate(approved)
        await self._audit.record(
            event_type="MEMORY_CANDIDATE_APPROVED",
            actor=_SOURCE_SYSTEM,
            subject=str(conversation_id),
            action="evaluate_policy",
            resource="memory_candidate",
            outcome="approved",
            origin=_SOURCE_SYSTEM,
            correlation_id=candidate_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            memory_candidate_id=candidate_id,
        )
        return await self._attempt_create(approved)

    async def retry_pending_candidate(self, candidate_id: UUID) -> RememberOutcome:
        """Safely retry an APPROVED candidate whose persistence is PENDING/FAILED.

        Reuses the same durable candidate id and thus the same deterministic
        Idempotency-Key, so a crash after a remote commit but before the local
        outcome was recorded converges to the original result on replay.
        """

        candidate = await self._store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError("MemoryCandidate not found")
        if candidate.decision_status is not MemoryCandidateDecisionStatus.APPROVED or (
            candidate.persistence_status
            not in (
                MemoryCandidatePersistenceStatus.PENDING,
                MemoryCandidatePersistenceStatus.FAILED,
            )
        ):
            raise MemoryCandidateNotRetryableError(
                "candidate is not an APPROVED, retryable persistence attempt"
            )
        return await self._attempt_create(candidate)

    async def _attempt_create(self, candidate: MemoryCandidate) -> RememberOutcome:
        if candidate.content is None:
            raise MemoryCandidateNotRetryableError(
                "candidate content was already scrubbed"
            )
        provenance = MemoryProvenance(
            origin_kind=candidate.origin_kind,
            conversation_uuid=candidate.conversation_id,
            turn_uuid=candidate.turn_id,
            task_uuid=candidate.task_id,
            source_ref=candidate.source_ref,
            confirmation_ref=candidate.confirmation_ref,
            observed_at=candidate.observed_at,
        )
        request = CreateMemoryRequest(
            memory_type=candidate.memory_type,
            scope=candidate.scope,
            content=candidate.content,
            provenance=provenance,
            confidence=candidate.confidence,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
        )
        idempotency_key = f"sofias-assistant:memory:create:{candidate.id}"
        await self._audit.record(
            event_type="MEMORY_WRITE_REQUESTED",
            actor=_SOURCE_SYSTEM,
            subject=str(candidate.conversation_id),
            action="create_memory",
            resource="cognitive_memory",
            outcome="requested",
            origin=_SOURCE_SYSTEM,
            correlation_id=candidate.id,
            conversation_id=candidate.conversation_id,
            turn_id=candidate.turn_id,
            memory_candidate_id=candidate.id,
        )
        now = self._clock()
        try:
            item = await self._provider.create_memory(
                request, idempotency_key=idempotency_key
            )
        except MemoryInvocationError as error:
            failed = replace(
                candidate,
                persistence_status=MemoryCandidatePersistenceStatus.FAILED,
                safe_failure_code=error.error.category.value,
                updated_at=now,
            )
            await self._store.update_candidate(failed)
            await self._audit.record(
                event_type="MEMORY_WRITE_FAILED",
                actor=_SOURCE_SYSTEM,
                subject=str(candidate.conversation_id),
                action="create_memory",
                resource="cognitive_memory",
                outcome="failed",
                origin=_SOURCE_SYSTEM,
                correlation_id=candidate.id,
                conversation_id=candidate.conversation_id,
                turn_id=candidate.turn_id,
                memory_candidate_id=candidate.id,
                metadata={"safe_failure_code": error.error.category.value},
            )
            return RememberOutcome(
                candidate_id=candidate.id,
                success=False,
                safe_failure_code=error.error.category.value,
            )
        succeeded = replace(
            candidate,
            persistence_status=MemoryCandidatePersistenceStatus.SUCCEEDED,
            memory_id=item.memory_id,
            persisted_at=now,
            updated_at=now,
            content=None,
        )
        await self._store.update_candidate(succeeded)
        await self._audit.record(
            event_type="MEMORY_WRITE_COMPLETED",
            actor=_SOURCE_SYSTEM,
            subject=str(candidate.conversation_id),
            action="create_memory",
            resource="cognitive_memory",
            outcome="success",
            origin=_SOURCE_SYSTEM,
            correlation_id=candidate.id,
            conversation_id=candidate.conversation_id,
            turn_id=candidate.turn_id,
            memory_candidate_id=candidate.id,
            memory_id=item.memory_id,
        )
        return RememberOutcome(
            candidate_id=candidate.id, success=True, memory_id=item.memory_id
        )

    async def get_memory(self, memory_id: UUID) -> MemoryItem | None:
        """Return one MemoryItem by exact id, or None when not found."""

        return await self._provider.get_memory(memory_id)

    async def recall(self, request: RecallRequest) -> MemoryRecallResult:
        """Explicit, caller-specified typed recall for diagnostics/UI (Slice §73)."""

        return await self._provider.recall_memories(request)

    async def supersede(
        self,
        *,
        target_memory_id: UUID,
        conversation_id: UUID,
        turn_id: UUID,
        cloud_context_eligible: bool,
    ) -> SupersedeOutcome:
        """Atomically replace one ACTIVE MemoryItem via a correction Turn."""

        turn = await self._load_turn(conversation_id, turn_id)
        now = self._clock()
        operation_id = self._id_factory()
        target = await self._provider.get_memory(target_memory_id)
        if target is None:
            await self._store.save_operation(
                MemoryOperation(
                    id=operation_id,
                    kind=MemoryOperationKind.SUPERSEDE,
                    target_memory_id=target_memory_id,
                    status=MemoryOperationStatus.FAILED,
                    created_at=now,
                    updated_at=now,
                    completed_at=now,
                    safe_failure_code="not_found",
                )
            )
            await self._audit.record(
                event_type="MEMORY_SUPERSEDE_FAILED",
                actor=_SOURCE_SYSTEM,
                subject=str(conversation_id),
                action="supersede_memory",
                resource="cognitive_memory",
                outcome="failed",
                origin=_SOURCE_SYSTEM,
                correlation_id=operation_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                memory_operation_id=operation_id,
                metadata={"safe_failure_code": "not_found"},
            )
            return SupersedeOutcome(
                operation_id=operation_id,
                success=False,
                safe_failure_code="not_found",
            )
        normalized_content = await self._extractor.extract(text=turn.user_text)
        decision = self._policy.evaluate(
            memory_type=target.memory_type,
            scope=target.scope or "",
            origin_kind=MemoryOriginKind.USER_ASSERTED,
            explicit_user_intent=True,
        )
        candidate_id = self._id_factory()
        if not decision.approved:
            rejected = MemoryCandidate(
                id=candidate_id,
                memory_type=target.memory_type,
                scope=target.scope or "",
                origin_kind=MemoryOriginKind.USER_ASSERTED,
                decision_status=MemoryCandidateDecisionStatus.REJECTED,
                persistence_status=MemoryCandidatePersistenceStatus.NOT_REQUESTED,
                created_at=now,
                updated_at=now,
                decided_at=now,
                conversation_id=conversation_id,
                turn_id=turn_id,
                cloud_context_eligible=cloud_context_eligible,
            )
            await self._store.save_candidate(rejected)
            await self._store.save_operation(
                MemoryOperation(
                    id=operation_id,
                    kind=MemoryOperationKind.SUPERSEDE,
                    target_memory_id=target_memory_id,
                    status=MemoryOperationStatus.FAILED,
                    created_at=now,
                    updated_at=now,
                    completed_at=now,
                    replacement_candidate_id=candidate_id,
                    safe_failure_code="POLICY_REJECTED",
                )
            )
            await self._audit.record(
                event_type="MEMORY_SUPERSEDE_FAILED",
                actor=_SOURCE_SYSTEM,
                subject=str(conversation_id),
                action="evaluate_policy",
                resource="memory_candidate",
                outcome="rejected",
                origin=_SOURCE_SYSTEM,
                correlation_id=operation_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                memory_operation_id=operation_id,
                memory_candidate_id=candidate_id,
                metadata={"reason": decision.reason},
            )
            return SupersedeOutcome(
                operation_id=operation_id,
                success=False,
                safe_failure_code="POLICY_REJECTED",
            )
        candidate = MemoryCandidate(
            id=candidate_id,
            memory_type=target.memory_type,
            scope=target.scope or "",
            origin_kind=MemoryOriginKind.USER_ASSERTED,
            decision_status=MemoryCandidateDecisionStatus.APPROVED,
            persistence_status=MemoryCandidatePersistenceStatus.PENDING,
            created_at=now,
            updated_at=now,
            decided_at=now,
            conversation_id=conversation_id,
            turn_id=turn_id,
            cloud_context_eligible=cloud_context_eligible,
            content=normalized_content,
        )
        await self._store.save_candidate(candidate)
        operation = MemoryOperation(
            id=operation_id,
            kind=MemoryOperationKind.SUPERSEDE,
            target_memory_id=target_memory_id,
            status=MemoryOperationStatus.PENDING,
            created_at=now,
            updated_at=now,
            replacement_candidate_id=candidate_id,
        )
        await self._store.save_operation(operation)
        return await self._attempt_supersede(candidate, operation)

    async def retry_pending_operation(
        self, operation_id: UUID
    ) -> SupersedeOutcome | ForgetOutcome:
        """Safely retry a durable Supersede/Forget operation using its own id."""

        operation = await self._store.get_operation(operation_id)
        if operation is None:
            raise KeyError("MemoryOperation not found")
        if operation.status not in (
            MemoryOperationStatus.PENDING,
            MemoryOperationStatus.FAILED,
        ):
            raise MemoryCandidateNotRetryableError(
                "operation is not in a retryable state"
            )
        if operation.kind is MemoryOperationKind.FORGET:
            return await self._attempt_forget(operation)
        if operation.replacement_candidate_id is None:
            raise MemoryCandidateNotRetryableError(
                "supersede operation is missing its replacement candidate"
            )
        candidate = await self._store.get_candidate(operation.replacement_candidate_id)
        if candidate is None:
            raise KeyError("replacement MemoryCandidate not found")
        return await self._attempt_supersede(candidate, operation)

    async def _attempt_supersede(
        self, candidate: MemoryCandidate, operation: MemoryOperation
    ) -> SupersedeOutcome:
        if candidate.content is None:
            raise MemoryCandidateNotRetryableError(
                "replacement candidate content was already scrubbed"
            )
        provenance = MemoryProvenance(
            origin_kind=candidate.origin_kind,
            conversation_uuid=candidate.conversation_id,
            turn_uuid=candidate.turn_id,
        )
        request = SupersedeMemoryRequest(
            content=candidate.content, provenance=provenance
        )
        idempotency_key = f"sofias-assistant:memory:supersede:{operation.id}"
        now = self._clock()
        try:
            result = await self._provider.supersede_memory(
                operation.target_memory_id, request, idempotency_key=idempotency_key
            )
        except MemoryInvocationError as error:
            await self._store.update_operation(
                replace(
                    operation,
                    status=MemoryOperationStatus.FAILED,
                    safe_failure_code=error.error.category.value,
                    updated_at=now,
                )
            )
            await self._store.update_candidate(
                replace(
                    candidate,
                    persistence_status=MemoryCandidatePersistenceStatus.FAILED,
                    safe_failure_code=error.error.category.value,
                    updated_at=now,
                )
            )
            await self._audit.record(
                event_type="MEMORY_SUPERSEDE_FAILED",
                actor=_SOURCE_SYSTEM,
                subject=str(candidate.conversation_id),
                action="supersede_memory",
                resource="cognitive_memory",
                outcome="failed",
                origin=_SOURCE_SYSTEM,
                correlation_id=operation.id,
                conversation_id=candidate.conversation_id,
                turn_id=candidate.turn_id,
                memory_operation_id=operation.id,
                memory_candidate_id=candidate.id,
                metadata={"safe_failure_code": error.error.category.value},
            )
            return SupersedeOutcome(
                operation_id=operation.id,
                success=False,
                safe_failure_code=error.error.category.value,
            )
        await self._store.update_operation(
            replace(
                operation,
                status=MemoryOperationStatus.SUCCEEDED,
                replacement_memory_id=result.replacement.memory_id,
                updated_at=now,
                completed_at=now,
            )
        )
        await self._store.update_candidate(
            replace(
                candidate,
                persistence_status=MemoryCandidatePersistenceStatus.SUCCEEDED,
                memory_id=result.replacement.memory_id,
                persisted_at=now,
                updated_at=now,
                content=None,
            )
        )
        await self._audit.record(
            event_type="MEMORY_SUPERSEDE_COMPLETED",
            actor=_SOURCE_SYSTEM,
            subject=str(candidate.conversation_id),
            action="supersede_memory",
            resource="cognitive_memory",
            outcome="success",
            origin=_SOURCE_SYSTEM,
            correlation_id=operation.id,
            conversation_id=candidate.conversation_id,
            turn_id=candidate.turn_id,
            memory_operation_id=operation.id,
            memory_candidate_id=candidate.id,
            memory_id=result.replacement.memory_id,
        )
        return SupersedeOutcome(
            operation_id=operation.id,
            success=True,
            old_memory_id=result.old.memory_id,
            replacement_memory_id=result.replacement.memory_id,
        )

    async def forget(
        self,
        *,
        target_memory_id: UUID,
        conversation_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> ForgetOutcome:
        """Precisely and destructively forget one exact MemoryItem."""

        now = self._clock()
        operation = MemoryOperation(
            id=self._id_factory(),
            kind=MemoryOperationKind.FORGET,
            target_memory_id=target_memory_id,
            status=MemoryOperationStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        await self._store.save_operation(operation)
        return await self._attempt_forget(
            operation, conversation_id=conversation_id, turn_id=turn_id
        )

    async def _attempt_forget(
        self,
        operation: MemoryOperation,
        *,
        conversation_id: UUID | None = None,
        turn_id: UUID | None = None,
    ) -> ForgetOutcome:
        idempotency_key = f"sofias-assistant:memory:forget:{operation.id}"
        now = self._clock()
        try:
            tombstone = await self._provider.forget_memory(
                operation.target_memory_id, idempotency_key=idempotency_key
            )
        except MemoryInvocationError as error:
            await self._store.update_operation(
                replace(
                    operation,
                    status=MemoryOperationStatus.FAILED,
                    safe_failure_code=error.error.category.value,
                    updated_at=now,
                )
            )
            await self._audit.record(
                event_type="MEMORY_FORGET_FAILED",
                actor=_SOURCE_SYSTEM,
                subject=str(conversation_id) if conversation_id else _SOURCE_SYSTEM,
                action="forget_memory",
                resource="cognitive_memory",
                outcome="failed",
                origin=_SOURCE_SYSTEM,
                correlation_id=operation.id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                memory_operation_id=operation.id,
                metadata={"safe_failure_code": error.error.category.value},
            )
            return ForgetOutcome(
                operation_id=operation.id,
                success=False,
                safe_failure_code=error.error.category.value,
            )
        await self._store.update_operation(
            replace(
                operation,
                status=MemoryOperationStatus.SUCCEEDED,
                updated_at=now,
                completed_at=now,
            )
        )
        await self._audit.record(
            event_type="MEMORY_FORGET_COMPLETED",
            actor=_SOURCE_SYSTEM,
            subject=str(conversation_id) if conversation_id else _SOURCE_SYSTEM,
            action="forget_memory",
            resource="cognitive_memory",
            outcome="success",
            origin=_SOURCE_SYSTEM,
            correlation_id=operation.id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            memory_operation_id=operation.id,
            memory_id=tombstone.memory_id,
        )
        return ForgetOutcome(
            operation_id=operation.id, success=True, memory_id=tombstone.memory_id
        )

    async def _load_turn(self, conversation_id: UUID, turn_id: UUID) -> Turn:
        async with self._uow_factory() as unit_of_work:
            turn = await unit_of_work.turns.get_by_id(turn_id)
        if turn is None or turn.conversation_id != conversation_id:
            raise ConversationTurnMismatchError(
                "Turn was not found in the given Conversation"
            )
        return turn
