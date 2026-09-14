"""Authenticated local boundary for deterministic Cognitive Memory operations.

Every endpoint calls `MemoryOrchestrator`; none touches `MemoryProvider`
directly (Slice 05 §71). No endpoint exposes generic administrative access to
the Sofias Memory API.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sofias_assistant.client_boundary.sessions import ClientSession
from sofias_assistant.memory.models import MemoryItem, MemoryType, RecallRequest
from sofias_assistant.memory.orchestrator import (
    ConversationTurnMismatchError,
    ForgetOutcome,
    MemoryOrchestrator,
    RememberOutcome,
    SupersedeOutcome,
)


class RememberRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    turn_id: UUID
    memory_type: Literal["profile", "semantic"]
    scope: str = Field(min_length=1, max_length=255)
    cloud_context_eligible: bool = False


class SupersedeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID
    turn_id: UUID
    cloud_context_eligible: bool = False


class ForgetRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID | None = None
    turn_id: UUID | None = None


class RecallRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    memory_types: list[Literal["profile", "semantic"]] | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    as_of: datetime | None = None
    include_superseded: bool = False
    min_relevance: float | None = Field(default=None, ge=-1.0, le=1.0)


def register_memory_routes(
    app: FastAPI,
    require_session: Callable[..., Any],
    orchestrator: MemoryOrchestrator,
) -> None:
    @app.post("/api/v1/memory/remember", status_code=201)
    async def remember(
        body: RememberRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> dict[str, Any]:
        try:
            outcome = await orchestrator.remember(
                conversation_id=body.conversation_id,
                turn_id=body.turn_id,
                memory_type=MemoryType(body.memory_type),
                scope=body.scope,
                cloud_context_eligible=body.cloud_context_eligible,
            )
        except ConversationTurnMismatchError:
            raise HTTPException(
                422, "Turn does not belong to the given Conversation"
            ) from None
        return _remember_response(outcome)

    @app.post("/api/v1/memory/recall")
    async def recall(
        body: RecallRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> dict[str, Any]:
        memory_types = (
            tuple(MemoryType(value) for value in body.memory_types)
            if body.memory_types
            else (MemoryType.PROFILE, MemoryType.SEMANTIC)
        )
        request = RecallRequest(
            query=body.query,
            scopes=tuple(body.scopes),
            memory_types=memory_types,
            top_k=body.top_k,
            as_of=body.as_of,
            include_superseded=body.include_superseded,
            min_relevance=body.min_relevance,
        )
        result = await orchestrator.recall(request)
        return {
            "items": [
                {
                    "memory": _item_dict(item.memory),
                    "relevance": item.relevance,
                    "is_current_truth": item.is_current_truth,
                }
                for item in result.items
            ]
        }

    @app.get("/api/v1/memory/items/{memory_id}")
    async def get_item(
        memory_id: UUID, _: Annotated[ClientSession, Depends(require_session)]
    ) -> dict[str, Any]:
        item = await orchestrator.get_memory(memory_id)
        if item is None:
            raise HTTPException(404, "Memory not found")
        return _item_dict(item)

    @app.post("/api/v1/memory/items/{memory_id}/supersede")
    async def supersede(
        memory_id: UUID,
        body: SupersedeRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> dict[str, Any]:
        try:
            outcome = await orchestrator.supersede(
                target_memory_id=memory_id,
                conversation_id=body.conversation_id,
                turn_id=body.turn_id,
                cloud_context_eligible=body.cloud_context_eligible,
            )
        except ConversationTurnMismatchError:
            raise HTTPException(
                422, "Turn does not belong to the given Conversation"
            ) from None
        return _supersede_response(outcome)

    @app.post("/api/v1/memory/items/{memory_id}/forget")
    async def forget(
        memory_id: UUID,
        body: ForgetRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> dict[str, Any]:
        outcome = await orchestrator.forget(
            target_memory_id=memory_id,
            conversation_id=body.conversation_id,
            turn_id=body.turn_id,
        )
        return _forget_response(outcome)


def _remember_response(outcome: RememberOutcome) -> dict[str, Any]:
    return {
        "candidate_id": str(outcome.candidate_id),
        "success": outcome.success,
        "memory_id": str(outcome.memory_id) if outcome.memory_id else None,
        "safe_failure_code": outcome.safe_failure_code,
    }


def _supersede_response(outcome: SupersedeOutcome) -> dict[str, Any]:
    return {
        "operation_id": str(outcome.operation_id),
        "success": outcome.success,
        "old_memory_id": str(outcome.old_memory_id) if outcome.old_memory_id else None,
        "replacement_memory_id": (
            str(outcome.replacement_memory_id)
            if outcome.replacement_memory_id
            else None
        ),
        "safe_failure_code": outcome.safe_failure_code,
    }


def _forget_response(outcome: ForgetOutcome) -> dict[str, Any]:
    return {
        "operation_id": str(outcome.operation_id),
        "success": outcome.success,
        "memory_id": str(outcome.memory_id) if outcome.memory_id else None,
        "safe_failure_code": outcome.safe_failure_code,
    }


def _item_dict(item: MemoryItem) -> dict[str, Any]:
    provenance = item.provenance
    return {
        "memory_id": str(item.memory_id),
        "memory_type": item.memory_type.value,
        "lifecycle": item.lifecycle.value,
        "created_at": item.created_at.isoformat(),
        "scope": item.scope,
        "content": item.content,
        "confidence": item.confidence,
        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
        "valid_until": item.valid_until.isoformat() if item.valid_until else None,
        "superseded_at": (
            item.superseded_at.isoformat() if item.superseded_at else None
        ),
        "superseded_by": str(item.superseded_by) if item.superseded_by else None,
        "forgotten_at": item.forgotten_at.isoformat() if item.forgotten_at else None,
        "provenance": {
            "origin_kind": provenance.origin_kind.value,
            "source_system": provenance.source_system,
            "conversation_uuid": (
                str(provenance.conversation_uuid)
                if provenance.conversation_uuid
                else None
            ),
            "turn_uuid": (str(provenance.turn_uuid) if provenance.turn_uuid else None),
            "task_uuid": (str(provenance.task_uuid) if provenance.task_uuid else None),
            "source_ref": provenance.source_ref,
            "confirmation_ref": provenance.confirmation_ref,
            "observed_at": (
                provenance.observed_at.isoformat() if provenance.observed_at else None
            ),
        },
    }
