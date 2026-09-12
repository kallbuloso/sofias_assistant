"""Explicit persistence boundary for Gate I4 execution state."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.execution.models import (
    ArtifactRef,
    ArtifactRetention,
    ConfirmationRequest,
    ConfirmationStatus,
    Delegation,
    GrantLifetime,
    GrantStatus,
    PermissionGrant,
    PolicyDecision,
    ToolCall,
    ToolError,
    ToolResult,
)
from sofias_assistant.persistence.models import (
    ArtifactRecord,
    ConfirmationRequestRecord,
    DelegationRecord,
    PermissionGrantRecord,
    PolicyDecisionRecord,
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
