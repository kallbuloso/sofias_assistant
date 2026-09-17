"""Integration coverage for bounded Conversation History (Gate I18, SA-B040)."""

from __future__ import annotations

from asyncio import to_thread
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from sofias_assistant.conversation.history import (
    MAX_LIMIT,
    ConversationHistoryError,
    ConversationHistoryService,
    ConversationNotFoundError,
    InvalidCursorError,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork

_CREATED_AT = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _conversation(conversation_id: UUID, updated_at: datetime) -> Conversation:
    return Conversation(conversation_id, _CREATED_AT, updated_at)


def _turn(
    conversation_id: UUID,
    sequence: int,
    *,
    status: TurnStatus = TurnStatus.COMPLETED,
    user_text: str = "hello",
    assistant_text: str | None = "hi",
    finished_at: datetime | None = _CREATED_AT,
) -> Turn:
    return Turn(
        id=uuid4(),
        conversation_id=conversation_id,
        sequence=sequence,
        status=status,
        input_modality=TurnInputModality.TEXT,
        cloud_context_eligible=False,
        user_text=user_text,
        assistant_text=assistant_text if status != TurnStatus.PROCESSING else None,
        ai_request_id=None,
        provider_id=None,
        model_id=None,
        provider_request_id=None,
        provider_session_id=None,
        error_category=None,
        error_message=None,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
        finished_at=finished_at if status != TurnStatus.PROCESSING else None,
    )


async def _service(tmp_path: Path) -> ConversationHistoryService:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    return ConversationHistoryService(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory)
    )


@pytest.mark.asyncio
async def test_list_conversations_empty(tmp_path: Path) -> None:
    service = await _service(tmp_path)

    page = await service.list_conversations()

    assert page.items == ()
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_list_conversations_returns_preview_and_last_turn(
    tmp_path: Path,
) -> None:
    service = await _service(tmp_path)
    conversation_id = UUID("30000000-0000-0000-0000-000000000001")
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.conversations.add(_conversation(conversation_id, _CREATED_AT))
        uow.turns.add(
            _turn(
                conversation_id,
                1,
                user_text="  What   is   the   weather   today?  ",
            )
        )
        uow.turns.add(
            _turn(conversation_id, 2, status=TurnStatus.PROCESSING, user_text="ok")
        )
        await uow.commit()

    page = await service.list_conversations()

    assert len(page.items) == 1
    item = page.items[0]
    assert item.conversation_id == conversation_id
    assert item.preview == "What is the weather today?"
    assert item.last_turn_status == "PROCESSING"
    assert item.last_turn_sequence == 2
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_list_conversations_preview_truncates_to_120_code_points(
    tmp_path: Path,
) -> None:
    service = await _service(tmp_path)
    conversation_id = UUID("30000000-0000-0000-0000-000000000002")
    long_text = "x" * 200
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.conversations.add(_conversation(conversation_id, _CREATED_AT))
        uow.turns.add(_turn(conversation_id, 1, user_text=long_text))
        await uow.commit()

    page = await service.list_conversations()

    assert len(page.items[0].preview) == 120
    assert page.items[0].preview == "x" * 120


@pytest.mark.asyncio
async def test_list_conversations_default_and_max_limit(tmp_path: Path) -> None:
    service = await _service(tmp_path)
    async with service._uow_factory() as uow:  # noqa: SLF001
        for index in range(60):
            uow.conversations.add(
                _conversation(
                    UUID(int=index + 1), _CREATED_AT + timedelta(seconds=index)
                )
            )
        await uow.commit()

    default_page = await service.list_conversations()
    assert len(default_page.items) == 50
    assert default_page.next_cursor is not None

    max_page = await service.list_conversations(limit=MAX_LIMIT)
    assert len(max_page.items) == 60


@pytest.mark.asyncio
async def test_list_conversations_rejects_invalid_limit(tmp_path: Path) -> None:
    service = await _service(tmp_path)

    with pytest.raises(ConversationHistoryError):
        await service.list_conversations(limit=0)
    with pytest.raises(ConversationHistoryError):
        await service.list_conversations(limit=101)


@pytest.mark.asyncio
async def test_list_conversations_cursor_paging_is_deterministic_and_ordered(
    tmp_path: Path,
) -> None:
    service = await _service(tmp_path)
    ids = [UUID(int=index + 1) for index in range(5)]
    async with service._uow_factory() as uow:  # noqa: SLF001
        for index, conversation_id in enumerate(ids):
            uow.conversations.add(
                _conversation(conversation_id, _CREATED_AT + timedelta(seconds=index))
            )
        await uow.commit()

    collected: list[UUID] = []
    cursor: str | None = None
    while True:
        page = await service.list_conversations(limit=2, cursor=cursor)
        collected.extend(item.conversation_id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert collected == list(reversed(ids))


@pytest.mark.asyncio
async def test_list_conversations_rejects_a_malformed_cursor(tmp_path: Path) -> None:
    service = await _service(tmp_path)

    with pytest.raises(InvalidCursorError):
        await service.list_conversations(cursor="not-a-real-cursor!!")


@pytest.mark.asyncio
async def test_list_turns_initial_page_is_most_recent_and_chronological(
    tmp_path: Path,
) -> None:
    service = await _service(tmp_path)
    conversation_id = UUID("30000000-0000-0000-0000-000000000003")
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.conversations.add(_conversation(conversation_id, _CREATED_AT))
        for sequence in range(1, 6):
            uow.turns.add(_turn(conversation_id, sequence))
        await uow.commit()

    page = await service.list_turns(conversation_id, limit=2)

    assert [turn.sequence for turn in page.turns] == [4, 5]
    assert page.has_older is True


@pytest.mark.asyncio
async def test_list_turns_before_sequence_pages_older_turns(tmp_path: Path) -> None:
    service = await _service(tmp_path)
    conversation_id = UUID("30000000-0000-0000-0000-000000000004")
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.conversations.add(_conversation(conversation_id, _CREATED_AT))
        for sequence in range(1, 6):
            uow.turns.add(_turn(conversation_id, sequence))
        await uow.commit()

    page = await service.list_turns(conversation_id, limit=2, before_sequence=4)

    assert [turn.sequence for turn in page.turns] == [2, 3]
    assert page.has_older is True


@pytest.mark.asyncio
async def test_list_turns_unknown_conversation_is_explicit(tmp_path: Path) -> None:
    service = await _service(tmp_path)

    with pytest.raises(ConversationNotFoundError):
        await service.list_turns(UUID(int=1))


@pytest.mark.asyncio
async def test_list_turns_rejects_invalid_before_sequence(tmp_path: Path) -> None:
    service = await _service(tmp_path)
    conversation_id = UUID("30000000-0000-0000-0000-000000000005")
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.conversations.add(_conversation(conversation_id, _CREATED_AT))
        await uow.commit()

    with pytest.raises(ConversationHistoryError):
        await service.list_turns(conversation_id, before_sequence=0)


@pytest.mark.asyncio
async def test_list_conversations_never_loads_unbounded_turn_collections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract v1 SS37: list query must not load all Turns for every Conversation."""

    from sofias_assistant.persistence.repositories import TurnRepository

    service = await _service(tmp_path)
    conversation_id = UUID("30000000-0000-0000-0000-000000000006")
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.conversations.add(_conversation(conversation_id, _CREATED_AT))
        for sequence in range(1, 21):
            uow.turns.add(_turn(conversation_id, sequence))
        await uow.commit()

    def _forbidden(self: TurnRepository, conversation_id: UUID) -> None:
        raise AssertionError("list_for_conversation must not be used for previews")

    monkeypatch.setattr(TurnRepository, "list_for_conversation", _forbidden)

    page = await service.list_conversations()
    assert len(page.items) == 1
