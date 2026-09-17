"""Authenticated bounded Conversation History routes (Gate I18, SA-B040).

Desktop/Core Interaction Contract v1 SS37-SS39. Every endpoint calls
`ConversationHistoryService`; neither touches persistence directly. Never
returns an unbounded Turn collection and never a raw ORM object.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel

from sofias_assistant.client_boundary.sessions import ClientSession
from sofias_assistant.conversation.history import (
    ConversationHistoryError,
    ConversationHistoryService,
    ConversationNotFoundError,
    ConversationPage,
    ConversationSummary,
    TurnPage,
)
from sofias_assistant.conversation.models import Turn


class ConversationSummaryResponse(BaseModel):
    conversation_id: UUID
    created_at: datetime
    updated_at: datetime
    preview: str
    last_turn_status: str | None
    last_turn_sequence: int | None

    @classmethod
    def from_summary(
        cls, summary: ConversationSummary
    ) -> "ConversationSummaryResponse":
        return cls(
            conversation_id=summary.conversation_id,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            preview=summary.preview,
            last_turn_status=summary.last_turn_status,
            last_turn_sequence=summary.last_turn_sequence,
        )


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]
    next_cursor: str | None

    @classmethod
    def from_page(cls, page: ConversationPage) -> "ConversationListResponse":
        return cls(
            items=[
                ConversationSummaryResponse.from_summary(item) for item in page.items
            ],
            next_cursor=page.next_cursor,
        )


class TurnHistoryItemResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sequence: int
    status: str
    input_modality: str
    cloud_context_eligible: bool
    user_text: str
    assistant_text: str | None
    provider_id: str | None
    model_id: str | None
    error_category: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_turn(cls, turn: Turn) -> "TurnHistoryItemResponse":
        return cls(
            id=turn.id,
            conversation_id=turn.conversation_id,
            sequence=turn.sequence,
            status=turn.status.value,
            input_modality=turn.input_modality.value,
            cloud_context_eligible=turn.cloud_context_eligible,
            user_text=turn.user_text,
            assistant_text=turn.assistant_text,
            provider_id=turn.provider_id,
            model_id=turn.model_id,
            error_category=turn.error_category,
            error_message=turn.error_message,
            created_at=turn.created_at,
            updated_at=turn.updated_at,
            finished_at=turn.finished_at,
        )


class TurnHistoryResponse(BaseModel):
    turns: list[TurnHistoryItemResponse]
    has_older: bool

    @classmethod
    def from_page(cls, page: TurnPage) -> "TurnHistoryResponse":
        return cls(
            turns=[TurnHistoryItemResponse.from_turn(turn) for turn in page.turns],
            has_older=page.has_older,
        )


def register_conversation_history_routes(
    app: FastAPI,
    require_session: Callable[..., Any],
    service: ConversationHistoryService,
) -> None:
    @app.get("/api/v1/conversations", response_model=ConversationListResponse)
    async def list_conversations(
        _: Annotated[ClientSession, Depends(require_session)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Query()] = None,
    ) -> ConversationListResponse:
        try:
            page = await service.list_conversations(limit=limit, cursor=cursor)
        except ConversationHistoryError as error:
            raise HTTPException(422, str(error)) from None
        return ConversationListResponse.from_page(page)

    @app.get(
        "/api/v1/conversations/{conversation_id}/turns",
        response_model=TurnHistoryResponse,
    )
    async def list_conversation_turns(
        conversation_id: UUID,
        _: Annotated[ClientSession, Depends(require_session)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        before_sequence: Annotated[int | None, Query(ge=1)] = None,
    ) -> TurnHistoryResponse:
        try:
            page = await service.list_turns(
                conversation_id, limit=limit, before_sequence=before_sequence
            )
        except ConversationNotFoundError:
            raise HTTPException(404, "Conversation not found") from None
        except ConversationHistoryError as error:
            raise HTTPException(422, str(error)) from None
        return TurnHistoryResponse.from_page(page)
