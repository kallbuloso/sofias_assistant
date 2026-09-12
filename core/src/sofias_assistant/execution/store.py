"""Explicit persistence boundary for Gate I4 execution state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.execution.models import (
    AgentDefinition,
    AgentRun,
    ArtifactRef,
    ArtifactRetention,
    AuthorityContext,
    ConfirmationRequest,
    ConfirmationStatus,
    Delegation,
    GrantLifetime,
    GrantStatus,
    PermissionGrant,
    PolicyDecision,
    Task,
    TaskAttempt,
    TaskExecutionStrategy,
    TaskStatus,
    ToolCall,
    ToolError,
    ToolExecutionMode,
    ToolResult,
)
from sofias_assistant.persistence.models import (
    AgentDefinitionRecord,
    AgentRunRecord,
    ArtifactRecord,
    ConfirmationRequestRecord,
    DelegationRecord,
    PermissionGrantRecord,
    PolicyDecisionRecord,
    TaskAttemptRecord,
    TaskRecord,
    ToolCallRecord,
)


class ExecutionStore:
    """Persist execution intent and authority without owning external side effects."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_grant(self, grant: PermissionGrant) -> None:
        async with self._session_factory() as session:
            session.add(_grant_record(grant))
            await session.commit()

    async def save_delegation(self, delegation: Delegation) -> None:
        async with self._session_factory() as session:
            session.add(
                DelegationRecord(
                    id=delegation.id,
                    subject=delegation.subject,
                    objective=delegation.objective,
                    resource_scope=delegation.resource_scope,
                    authority_scope=delegation.authority_scope,
                    constraints_json=_encode(delegation.constraints),
                    created_at=delegation.created_at,
                    expires_at=delegation.expires_at,
                    revoked_at=delegation.revoked_at,
                )
            )
            await session.commit()

    async def get_grant(self, grant_id: UUID) -> PermissionGrant | None:
        async with self._session_factory() as session:
            record = await session.get(PermissionGrantRecord, grant_id)
            return _grant_from_record(record) if record is not None else None

    async def revoke_grant(self, grant_id: UUID, revoked_at: datetime) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(PermissionGrantRecord)
                .where(
                    PermissionGrantRecord.id == grant_id,
                    PermissionGrantRecord.status == GrantStatus.ACTIVE.value,
                )
                .values(status=GrantStatus.REVOKED.value, revoked_at=revoked_at)
            )
            await session.commit()
            return getattr(result, "rowcount", 0) == 1

    async def consume_one_shot(self, grant_id: UUID) -> bool:
        """Atomically consume the only use of a ONE_SHOT grant."""

        async with self._session_factory() as session:
            result = await session.execute(
                update(PermissionGrantRecord)
                .where(
                    PermissionGrantRecord.id == grant_id,
                    PermissionGrantRecord.status == GrantStatus.ACTIVE.value,
                    PermissionGrantRecord.lifetime == GrantLifetime.ONE_SHOT.value,
                    PermissionGrantRecord.remaining_uses == 1,
                )
                .values(
                    status=GrantStatus.CONSUMED.value,
                    remaining_uses=0,
                )
            )
            await session.commit()
            return getattr(result, "rowcount", 0) == 1

    async def save_decision(self, decision: PolicyDecision) -> None:
        async with self._session_factory() as session:
            session.add(
                PolicyDecisionRecord(
                    id=decision.id,
                    request_id=decision.request_id,
                    outcome=decision.outcome.value,
                    reason=decision.reason,
                    policy_version=decision.policy_version,
                    grant_id=decision.grant_id,
                    created_at=decision.created_at,
                )
            )
            await session.commit()

    async def save_confirmation(self, request: ConfirmationRequest) -> None:
        async with self._session_factory() as session:
            session.add(_confirmation_record(request))
            await session.commit()

    async def get_confirmation(
        self, confirmation_id: UUID
    ) -> ConfirmationRequest | None:
        async with self._session_factory() as session:
            record = await session.get(ConfirmationRequestRecord, confirmation_id)
            return _confirmation_from_record(record) if record is not None else None

    async def resolve_confirmation(
        self,
        confirmation_id: UUID,
        *,
        status: ConfirmationStatus,
        resolved_at: datetime,
        grant_id: UUID | None,
    ) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                update(ConfirmationRequestRecord)
                .where(
                    ConfirmationRequestRecord.id == confirmation_id,
                    ConfirmationRequestRecord.status
                    == ConfirmationStatus.PENDING.value,
                )
                .values(
                    status=status.value,
                    resolved_at=resolved_at,
                    grant_id=grant_id,
                )
            )
            await session.commit()
            return getattr(result, "rowcount", 0) == 1

    async def save_tool_call(
        self,
        call: ToolCall,
        *,
        status: str,
        result: ToolResult | None = None,
        decision_id: UUID | None = None,
        confirmation_id: UUID | None = None,
    ) -> None:
        async with self._session_factory() as session:
            record = await session.get(ToolCallRecord, call.id)
            values = dict(
                name=call.name,
                subject=call.subject,
                session_id=call.session_id,
                arguments_json=_encode(call.arguments),
                status=status,
                result_json=_encode_result(result) if result is not None else None,
                decision_id=decision_id,
                confirmation_id=confirmation_id,
            )
            if record is None:
                session.add(
                    ToolCallRecord(
                        id=call.id,
                        created_at=datetime.now(call_created_timezone()),
                        **values,
                    )
                )
            else:
                for key, value in values.items():
                    setattr(record, key, value)
            await session.commit()

    async def get_tool_call(
        self, call_id: UUID
    ) -> tuple[ToolCall, ToolResult | None, str] | None:
        async with self._session_factory() as session:
            record = await session.get(ToolCallRecord, call_id)
            if record is None:
                return None
            call = ToolCall(
                id=record.id,
                name=record.name,
                subject=record.subject,
                session_id=record.session_id,
                arguments=json.loads(record.arguments_json),
            )
            return call, _decode_result(record.result_json), record.status

    async def save_artifact(self, ref: ArtifactRef, relative_path: str) -> None:
        async with self._session_factory() as session:
            session.add(
                ArtifactRecord(
                    id=ref.id,
                    relative_path=relative_path,
                    kind=ref.kind,
                    media_type=ref.media_type,
                    size=ref.size,
                    retention=ref.retention.value,
                    created_at=ref.created_at,
                )
            )
            await session.commit()

    async def get_artifact(self, artifact_id: UUID) -> tuple[ArtifactRef, str] | None:
        async with self._session_factory() as session:
            record = await session.get(ArtifactRecord, artifact_id)
            if record is None:
                return None
            return (
                ArtifactRef(
                    id=record.id,
                    kind=record.kind,
                    media_type=record.media_type,
                    size=record.size,
                    retention=ArtifactRetention(record.retention),
                    created_at=record.created_at,
                ),
                record.relative_path,
            )

    async def save_task(self, task: Task) -> None:
        async with self._session_factory() as session:
            session.add(_task_record(task))
            await session.commit()

    async def get_task(self, task_id: UUID) -> Task | None:
        async with self._session_factory() as session:
            record = await session.get(TaskRecord, task_id)
            return _task_from_record(record) if record is not None else None

    async def update_task(self, task: Task) -> None:
        async with self._session_factory() as session:
            record = await session.get(TaskRecord, task.id)
            if record is None:
                raise KeyError("Task not found")
            for key, value in _task_record_values(task).items():
                setattr(record, key, value)
            await session.commit()

    async def claim_task(self, task_id: UUID, owner: str) -> Task | None:
        async with self._session_factory() as session:
            result = await session.execute(
                update(TaskRecord)
                .where(
                    TaskRecord.id == task_id,
                    TaskRecord.status == TaskStatus.QUEUED.value,
                    TaskRecord.claimed_by.is_(None),
                )
                .values(
                    status=TaskStatus.RUNNING.value,
                    claimed_by=owner,
                    started_at=datetime.now(call_created_timezone()),
                    updated_at=datetime.now(call_created_timezone()),
                )
            )
            await session.commit()
            if getattr(result, "rowcount", 0) != 1:
                return None
            record = await session.get(TaskRecord, task_id)
            return _task_from_record(record) if record is not None else None

    async def save_task_attempt(self, attempt: TaskAttempt) -> None:
        async with self._session_factory() as session:
            session.add(_task_attempt_record(attempt))
            await session.commit()

    async def update_task_attempt(self, attempt: TaskAttempt) -> None:
        async with self._session_factory() as session:
            record = await session.get(TaskAttemptRecord, attempt.id)
            if record is None:
                raise KeyError("Task attempt not found")
            for key, value in _task_attempt_record_values(attempt).items():
                setattr(record, key, value)
            await session.commit()

    async def list_task_attempts(self, task_id: UUID) -> tuple[TaskAttempt, ...]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TaskAttemptRecord)
                .where(TaskAttemptRecord.task_id == task_id)
                .order_by(TaskAttemptRecord.attempt_number)
            )
            return tuple(_task_attempt_from_record(row) for row in result.scalars())

    async def save_agent_definition(self, definition: AgentDefinition) -> None:
        async with self._session_factory() as session:
            session.add(_agent_definition_record(definition))
            await session.commit()

    async def get_agent_definition(self, definition_id: UUID) -> AgentDefinition | None:
        async with self._session_factory() as session:
            record = await session.get(AgentDefinitionRecord, definition_id)
            return _agent_definition_from_record(record) if record is not None else None

    async def save_agent_run(self, run: AgentRun) -> None:
        async with self._session_factory() as session:
            session.add(_agent_run_record(run))
            await session.commit()

    async def update_agent_run(self, run: AgentRun) -> None:
        async with self._session_factory() as session:
            record = await session.get(AgentRunRecord, run.id)
            if record is None:
                raise KeyError("AgentRun not found")
            for key, value in _agent_run_record_values(run).items():
                setattr(record, key, value)
            await session.commit()


def call_created_timezone() -> Any:
    from datetime import UTC

    return UTC


def _encode(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, default=_json_default)


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _encode_result(result: ToolResult) -> str:
    return json.dumps(
        {
            "status": result.status,
            "call_id": str(result.call_id),
            "value": result.value,
            "error": (
                {"code": result.error.code, "message": result.error.message}
                if result.error is not None
                else None
            ),
            "confirmation_id": (
                str(result.confirmation_id)
                if result.confirmation_id is not None
                else None
            ),
            "artifact_refs": [
                {
                    "id": str(ref.id),
                    "kind": ref.kind,
                    "media_type": ref.media_type,
                    "size": ref.size,
                    "retention": ref.retention.value,
                    "created_at": ref.created_at.isoformat(),
                }
                for ref in result.artifact_refs
            ],
        },
        default=_json_default,
    )


def _decode_result(value: str | None) -> ToolResult | None:
    if value is None:
        return None
    data = json.loads(value)
    return ToolResult(
        status=data["status"],
        call_id=UUID(data["call_id"]),
        value=data.get("value"),
        error=(ToolError(**data["error"]) if data.get("error") else None),
        confirmation_id=(
            UUID(data["confirmation_id"]) if data.get("confirmation_id") else None
        ),
        artifact_refs=tuple(
            ArtifactRef(
                id=UUID(item["id"]),
                kind=item["kind"],
                media_type=item["media_type"],
                size=item["size"],
                retention=ArtifactRetention(item["retention"]),
                created_at=datetime.fromisoformat(item["created_at"]),
            )
            for item in data.get("artifact_refs", [])
        ),
    )


def _grant_record(grant: PermissionGrant) -> PermissionGrantRecord:
    return PermissionGrantRecord(
        id=grant.id,
        subject=grant.subject,
        capability=grant.capability,
        resource_scope=grant.resource_scope,
        constraints_json=_encode(grant.constraints),
        lifetime=grant.lifetime.value,
        session_id=grant.session_id,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
        issuing_context_json=_encode(grant.issuing_context),
        remaining_uses=1
        if grant.lifetime is GrantLifetime.ONE_SHOT
        else grant.remaining_uses,
        status=grant.status.value,
        revoked_at=grant.revoked_at,
    )


def _grant_from_record(record: PermissionGrantRecord) -> PermissionGrant:
    return PermissionGrant(
        id=record.id,
        subject=record.subject,
        capability=record.capability,
        resource_scope=record.resource_scope,
        constraints=json.loads(record.constraints_json),
        lifetime=GrantLifetime(record.lifetime),
        session_id=record.session_id,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
        issuing_context=json.loads(record.issuing_context_json),
        remaining_uses=record.remaining_uses,
        status=GrantStatus(record.status),
        revoked_at=record.revoked_at,
    )


def _confirmation_record(request: ConfirmationRequest) -> ConfirmationRequestRecord:
    return ConfirmationRequestRecord(
        id=request.id,
        subject=request.subject,
        capability=request.capability,
        operation=request.operation,
        resource=request.resource,
        tool_call_id=request.tool_call_id,
        session_id=request.session_id,
        requested_lifetime=request.requested_lifetime.value,
        constraints_json=_encode(request.constraints),
        status=request.status.value,
        created_at=request.created_at,
        resolved_at=request.resolved_at,
        grant_id=request.grant_id,
    )


def _confirmation_from_record(record: ConfirmationRequestRecord) -> ConfirmationRequest:
    return ConfirmationRequest(
        id=record.id,
        subject=record.subject,
        capability=record.capability,
        operation=record.operation,
        resource=record.resource,
        tool_call_id=record.tool_call_id,
        session_id=record.session_id,
        requested_lifetime=GrantLifetime(record.requested_lifetime),
        constraints=json.loads(record.constraints_json),
        status=ConfirmationStatus(record.status),
        created_at=record.created_at,
        resolved_at=record.resolved_at,
        grant_id=record.grant_id,
    )


def _task_record(task: Task) -> TaskRecord:
    return TaskRecord(**_task_record_values(task), id=task.id)


def _task_record_values(task: Task) -> dict[str, Any]:
    return {
        "objective": task.objective,
        "origin": task.origin,
        "subject": task.subject,
        "status": task.status.value,
        "authority_json": _encode(
            {
                "subject": task.authority.subject if task.authority else task.subject,
                "session_id": str(task.authority.session_id)
                if task.authority and task.authority.session_id
                else None,
                "root_subject": task.authority.root_subject if task.authority else None,
            }
        ),
        "conversation_id": task.conversation_id,
        "delegation_id": task.delegation_id,
        "execution_strategy": task.execution_strategy.value,
        "result_json": json.dumps(task.result, default=_json_default)
        if task.result is not None
        else None,
        "error_code": task.error.code if task.error else None,
        "error_message": task.error.message if task.error else None,
        "cancellation_requested": task.cancellation_requested,
        "claimed_by": task.claimed_by,
        "claim_expires_at": task.claim_expires_at,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def _task_from_record(record: TaskRecord) -> Task:
    authority = json.loads(record.authority_json)
    return Task(
        id=record.id,
        objective=record.objective,
        origin=record.origin,
        subject=record.subject,
        status=TaskStatus(record.status),
        authority=AuthorityContext(
            authority["subject"],
            UUID(authority["session_id"]) if authority.get("session_id") else None,
            authority.get("root_subject"),
        ),
        conversation_id=record.conversation_id,
        delegation_id=record.delegation_id,
        execution_strategy=TaskExecutionStrategy(record.execution_strategy),
        result=json.loads(record.result_json) if record.result_json else None,
        error=(
            ToolError(record.error_code, record.error_message or "Task failed")
            if record.error_code
            else None
        ),
        cancellation_requested=record.cancellation_requested,
        claimed_by=record.claimed_by,
        claim_expires_at=record.claim_expires_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _task_attempt_record(attempt: TaskAttempt) -> TaskAttemptRecord:
    return TaskAttemptRecord(**_task_attempt_record_values(attempt), id=attempt.id)


def _task_attempt_record_values(attempt: TaskAttempt) -> dict[str, Any]:
    return {
        "task_id": attempt.task_id,
        "attempt_number": attempt.attempt_number,
        "status": attempt.status.value,
        "tool_call_id": attempt.tool_call_id,
        "execution_mode": attempt.execution_mode.value
        if attempt.execution_mode
        else None,
        "process_id": attempt.process_id,
        "result_json": json.dumps(attempt.result, default=_json_default)
        if attempt.result is not None
        else None,
        "error_code": attempt.error.code if attempt.error else None,
        "error_message": attempt.error.message if attempt.error else None,
        "started_at": attempt.started_at,
        "finished_at": attempt.finished_at,
    }


def _task_attempt_from_record(record: TaskAttemptRecord) -> TaskAttempt:
    return TaskAttempt(
        id=record.id,
        task_id=record.task_id,
        attempt_number=record.attempt_number,
        status=TaskStatus(record.status),
        tool_call_id=record.tool_call_id,
        execution_mode=(
            ToolExecutionMode(record.execution_mode) if record.execution_mode else None
        ),
        process_id=record.process_id,
        result=json.loads(record.result_json) if record.result_json else None,
        error=(
            ToolError(record.error_code, record.error_message or "Task failed")
            if record.error_code
            else None
        ),
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _agent_definition_record(definition: AgentDefinition) -> AgentDefinitionRecord:
    return AgentDefinitionRecord(
        id=definition.id,
        name=definition.name,
        version=definition.version,
        description=definition.description,
        required_capabilities_json=_encode(
            {"values": sorted(definition.required_capabilities)}
        ),
        allowed_tools_json=_encode({"values": sorted(definition.allowed_tools)}),
        context_policy=definition.context_policy,
        provider_requirements_json=_encode(definition.provider_requirements),
        runtime_limits_json=_encode(definition.runtime_limits),
        enabled=definition.enabled,
    )


def _agent_definition_from_record(record: AgentDefinitionRecord) -> AgentDefinition:
    return AgentDefinition(
        id=record.id,
        name=record.name,
        version=record.version,
        description=record.description,
        required_capabilities=frozenset(
            json.loads(record.required_capabilities_json)["values"]
        ),
        allowed_tools=frozenset(json.loads(record.allowed_tools_json)["values"]),
        context_policy=record.context_policy,
        provider_requirements=json.loads(record.provider_requirements_json),
        runtime_limits=json.loads(record.runtime_limits_json),
        enabled=record.enabled,
    )


def _agent_run_record(run: AgentRun) -> AgentRunRecord:
    return AgentRunRecord(**_agent_run_record_values(run), id=run.id)


def _agent_run_record_values(run: AgentRun) -> dict[str, Any]:
    return {
        "task_id": run.task_id,
        "agent_definition_id": run.agent_definition_id,
        "agent_definition_version": run.agent_definition_version,
        "objective": run.objective,
        "delegated_context_json": _encode(run.delegated_context),
        "authority_scope": run.authority_scope,
        "allowed_tools_json": _encode({"values": sorted(run.allowed_tools)}),
        "status": run.status.value,
        "workspace": run.workspace,
        "provider_requirements_json": _encode(run.provider_requirements),
        "runtime_limits_json": _encode(run.runtime_limits),
        "result_json": json.dumps(run.result, default=_json_default)
        if run.result is not None
        else None,
        "correlation_id": run.correlation_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }
