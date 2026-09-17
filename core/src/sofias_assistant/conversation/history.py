"""Bounded, paginated Conversation History reads (Gate I18, SA-B040).

Desktop/Core Interaction Contract v1 SS37-SS39: Conversation History remains
Core-owned Operational Store data, never Sofias Memory. This service only
reads already-persisted Conversation/Turn rows through bounded, index-
friendly repository queries; it never loads an unbounded Turn collection to
build a list, and it never calls an LLM or writes to Memory to build a
preview.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sofias_assistant.conversation.models import Turn
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
_PREVIEW_MAX_CODE_POINTS = 120
_NEUTRAL_PREVIEW = "New conversation"


class ConversationHistoryError(RuntimeError):
    """Raised for a deterministically invalid Conversation History request."""


class InvalidCursorError(ConversationHistoryError):
    """Raised when an opaque list cursor cannot be decoded."""


class ConversationNotFoundError(ConversationHistoryError):
    """Raised when Turn history is requested for an unknown Conversation."""


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """One bounded Conversation list item (Contract v1 SS38)."""

    conversation_id: UUID
    created_at: datetime
    updated_at: datetime
    preview: str
    last_turn_status: str | None
    last_turn_sequence: int | None


@dataclass(frozen=True, slots=True)
class ConversationPage:
    """One page of `ConversationSummary` items plus an opaque next cursor."""

    items: tuple[ConversationSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class TurnPage:
    """One chronological page of Turns plus whether older Turns remain."""

    turns: tuple[Turn, ...]
    has_older: bool


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ConversationHistoryError("limit must be an integer")
    if not 1 <= limit <= MAX_LIMIT:
        raise ConversationHistoryError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def _encode_cursor(updated_at: datetime, conversation_id: UUID) -> str:
    raw = f"{updated_at.isoformat()}|{conversation_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        updated_at_text, conversation_id_text = raw.rsplit("|", 1)
        return datetime.fromisoformat(updated_at_text), UUID(conversation_id_text)
    except (
        ValueError,
        binascii.Error,
        UnicodeDecodeError,
    ) as error:
        raise InvalidCursorError("cursor is not a valid opaque page token") from error


def _build_preview(first_user_turn: Turn | None) -> str:
    if first_user_turn is None:
        return _NEUTRAL_PREVIEW
    normalized = " ".join(first_user_turn.user_text.split())
    if not normalized:
        return _NEUTRAL_PREVIEW
    return normalized[:_PREVIEW_MAX_CODE_POINTS]


class ConversationHistoryService:
    """Read-only application boundary for bounded Conversation/Turn history."""

    def __init__(self, *, uow_factory: Callable[[], SqlAlchemyUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def list_conversations(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> ConversationPage:
        bounded_limit = _clamp_limit(limit)
        before = _decode_cursor(cursor) if cursor is not None else None
        async with self._uow_factory() as uow:
            conversations, has_more = await uow.conversations.list_page(
                limit=bounded_limit, before=before
            )
            ids = [conversation.id for conversation in conversations]
            first_turns = await uow.turns.first_turns_for(ids)
            last_turns = await uow.turns.latest_turns_for(ids)
        items = tuple(
            ConversationSummary(
                conversation_id=conversation.id,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                preview=_build_preview(first_turns.get(conversation.id)),
                last_turn_status=(
                    last_turns[conversation.id].status.value
                    if conversation.id in last_turns
                    else None
                ),
                last_turn_sequence=(
                    last_turns[conversation.id].sequence
                    if conversation.id in last_turns
                    else None
                ),
            )
            for conversation in conversations
        )
        next_cursor = (
            _encode_cursor(conversations[-1].updated_at, conversations[-1].id)
            if has_more and conversations
            else None
        )
        return ConversationPage(items=items, next_cursor=next_cursor)

    async def list_turns(
        self,
        conversation_id: UUID,
        *,
        limit: int | None = None,
        before_sequence: int | None = None,
    ) -> TurnPage:
        bounded_limit = _clamp_limit(limit)
        if before_sequence is not None and (
            isinstance(before_sequence, bool)
            or not isinstance(before_sequence, int)
            or before_sequence < 1
        ):
            raise ConversationHistoryError(
                "before_sequence must be an integer greater than or equal to one"
            )
        async with self._uow_factory() as uow:
            conversation = await uow.conversations.get_by_id(conversation_id)
            if conversation is None:
                raise ConversationNotFoundError("Conversation was not found")
            if before_sequence is None:
                turns, has_older = await uow.turns.list_recent(
                    conversation_id, limit=bounded_limit
                )
            else:
                turns, has_older = await uow.turns.list_before(
                    conversation_id,
                    before_sequence=before_sequence,
                    limit=bounded_limit,
                )
        return TurnPage(turns=tuple(turns), has_older=has_older)
