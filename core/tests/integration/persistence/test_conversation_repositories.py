"""Integration tests for durable Conversation and Turn persistence."""

from asyncio import to_thread
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

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
from sofias_assistant.persistence.repositories import RepositoryEntityNotFoundError
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork

CREATED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
CONVERSATION_ID = UUID("10000000-0000-0000-0000-000000000001")


def database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"


def conversation() -> Conversation:
    return Conversation(CONVERSATION_ID, CREATED_AT, CREATED_AT)


def processing_turn(
    sequence: int, *, turn_id: UUID, cloud_context_eligible: bool = False
) -> Turn:
    return Turn(
        id=turn_id,
        conversation_id=CONVERSATION_ID,
        sequence=sequence,
        status=TurnStatus.PROCESSING,
        input_modality=TurnInputModality.TEXT,
        cloud_context_eligible=cloud_context_eligible,
        user_text=f"question {sequence}",
        assistant_text=None,
        ai_request_id=None,
        provider_id=None,
        model_id=None,
        provider_request_id=None,
        provider_session_id=None,
        error_category=None,
        error_message=None,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        finished_at=None,
    )


async def create_uow_factory(tmp_path: Path):
    url = database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    return engine, create_session_factory(engine)


@pytest.mark.asyncio
async def test_migration_creates_conversation_and_turn_tables(tmp_path: Path) -> None:
    engine, _ = await create_uow_factory(tmp_path)
    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
        assert {"conversations", "turns"} <= table_names
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_and_turn_roundtrip_ordering_and_next_sequence(
    tmp_path: Path,
) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    turn_ids = {
        1: UUID("10000000-0000-0000-0000-000000000011"),
        2: UUID("10000000-0000-0000-0000-000000000012"),
        3: UUID("10000000-0000-0000-0000-000000000013"),
    }
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.conversations.add(conversation())
            assert await uow.turns.next_sequence(CONVERSATION_ID) == 1
            for sequence in (3, 1, 2):
                uow.turns.add(
                    processing_turn(
                        sequence,
                        turn_id=turn_ids[sequence],
                        cloud_context_eligible=sequence != 2,
                    )
                )
            await uow.commit()

        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert await uow.conversations.get_by_id(CONVERSATION_ID) == conversation()
            assert [
                turn.sequence
                for turn in await uow.turns.list_for_conversation(CONVERSATION_ID)
            ] == [1, 2, 3]
            assert await uow.turns.get_by_id(turn_ids[2]) == processing_turn(
                2, turn_id=turn_ids[2], cloud_context_eligible=False
            )
            eligible_turn = await uow.turns.get_by_id(turn_ids[1])
            assert eligible_turn is not None
            assert eligible_turn.cloud_context_eligible is True
            assert await uow.turns.next_sequence(CONVERSATION_ID) == 4
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_constraints_and_explicit_commit_boundary(tmp_path: Path) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    duplicate_id = UUID("10000000-0000-0000-0000-000000000021")
    other_conversation_id = UUID("10000000-0000-0000-0000-000000000022")
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.conversations.add(conversation())
            uow.turns.add(processing_turn(1, turn_id=duplicate_id))
            await uow.commit()

        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.turns.add(
                Turn(
                    id=UUID("10000000-0000-0000-0000-000000000023"),
                    conversation_id=CONVERSATION_ID,
                    sequence=1,
                    status=TurnStatus.PROCESSING,
                    input_modality=TurnInputModality.TEXT,
                    cloud_context_eligible=False,
                    user_text="duplicate",
                    assistant_text=None,
                    ai_request_id=None,
                    provider_id=None,
                    model_id=None,
                    provider_request_id=None,
                    provider_session_id=None,
                    error_category=None,
                    error_message=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                    finished_at=None,
                )
            )
            with pytest.raises(IntegrityError):
                await uow.flush()
            await uow.rollback()

        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.turns.add(
                Turn(
                    id=UUID("10000000-0000-0000-0000-000000000024"),
                    conversation_id=other_conversation_id,
                    sequence=1,
                    status=TurnStatus.PROCESSING,
                    input_modality=TurnInputModality.TEXT,
                    cloud_context_eligible=False,
                    user_text="missing parent",
                    assistant_text=None,
                    ai_request_id=None,
                    provider_id=None,
                    model_id=None,
                    provider_request_id=None,
                    provider_session_id=None,
                    error_category=None,
                    error_message=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                    finished_at=None,
                )
            )
            with pytest.raises(IntegrityError):
                await uow.flush()
            await uow.rollback()

        uncommitted_id = UUID("10000000-0000-0000-0000-000000000025")
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.turns.add(processing_turn(2, turn_id=uncommitted_id))
        async with SqlAlchemyUnitOfWork(factory) as uow:
            assert await uow.turns.get_by_id(uncommitted_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_terminal_save_and_recreated_engine_recover_domain_snapshots(
    tmp_path: Path,
) -> None:
    url = database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    turn_id = UUID("10000000-0000-0000-0000-000000000031")
    finished_at = CREATED_AT + timedelta(seconds=1)
    engine = create_async_engine(url)
    factory = create_session_factory(engine)
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.conversations.add(conversation())
            uow.turns.add(
                processing_turn(1, turn_id=turn_id, cloud_context_eligible=True)
            )
            await uow.commit()
        async with SqlAlchemyUnitOfWork(factory) as uow:
            loaded = await uow.turns.get_by_id(turn_id)
            assert loaded is not None
            await uow.turns.save(
                loaded.complete(
                    assistant_text="final answer",
                    updated_at=finished_at,
                    finished_at=finished_at,
                    ai_request_id=UUID("10000000-0000-0000-0000-000000000032"),
                    provider_id="fake",
                    model_id="test-model",
                    provider_request_id="provider-request",
                    provider_session_id="provider-session",
                )
            )
            await uow.commit()
    finally:
        await engine.dispose()

    recreated_engine = create_async_engine(url)
    recreated_factory = create_session_factory(recreated_engine)
    try:
        async with SqlAlchemyUnitOfWork(recreated_factory) as uow:
            persisted = await uow.turns.get_by_id(turn_id)
            assert isinstance(persisted, Turn)
            assert persisted.status is TurnStatus.COMPLETED
            assert persisted.assistant_text == "final answer"
            assert persisted.finished_at == finished_at
            assert persisted.provider_id == "fake"
            assert persisted.cloud_context_eligible is True
    finally:
        await recreated_engine.dispose()


def _conversation(conversation_id: UUID, updated_at: datetime) -> Conversation:
    return Conversation(conversation_id, CREATED_AT, updated_at)


def _turn(
    conversation_id: UUID, sequence: int, *, turn_id: UUID, user_text: str
) -> Turn:
    return Turn(
        id=turn_id,
        conversation_id=conversation_id,
        sequence=sequence,
        status=TurnStatus.PROCESSING,
        input_modality=TurnInputModality.TEXT,
        cloud_context_eligible=False,
        user_text=user_text,
        assistant_text=None,
        ai_request_id=None,
        provider_id=None,
        model_id=None,
        provider_request_id=None,
        provider_session_id=None,
        error_category=None,
        error_message=None,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        finished_at=None,
    )


@pytest.mark.asyncio
async def test_conversation_list_page_orders_desc_with_deterministic_tiebreak_and_bounds(
    tmp_path: Path,
) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    ids = [UUID(f"20000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            # Two conversations share the same updated_at; id must break the tie.
            uow.conversations.add(_conversation(ids[0], CREATED_AT))
            uow.conversations.add(_conversation(ids[1], CREATED_AT))
            uow.conversations.add(
                _conversation(ids[2], CREATED_AT + timedelta(seconds=1))
            )
            await uow.commit()

        async with SqlAlchemyUnitOfWork(factory) as uow:
            page, has_more = await uow.conversations.list_page(limit=2, before=None)
            assert has_more is True
            assert [c.id for c in page] == [ids[2], max(ids[0], ids[1])]

            second_page, has_more_2 = await uow.conversations.list_page(
                limit=2, before=(page[-1].updated_at, page[-1].id)
            )
            assert has_more_2 is False
            assert [c.id for c in second_page] == [min(ids[0], ids[1])]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_list_page_keyset_pagination_has_no_gaps_or_duplicates(
    tmp_path: Path,
) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    ids = [UUID(f"21000000-0000-0000-0000-0000000000{i:02d}") for i in range(1, 6)]
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            for index, conversation_id in enumerate(ids):
                uow.conversations.add(
                    _conversation(
                        conversation_id, CREATED_AT + timedelta(seconds=index)
                    )
                )
            await uow.commit()

        seen: list[UUID] = []
        cursor: tuple[datetime, UUID] | None = None
        async with SqlAlchemyUnitOfWork(factory) as uow:
            while True:
                page, has_more = await uow.conversations.list_page(
                    limit=2, before=cursor
                )
                seen.extend(c.id for c in page)
                if not has_more:
                    break
                cursor = (page[-1].updated_at, page[-1].id)
        assert seen == list(reversed(ids))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_list_recent_and_list_before_page_chronologically(
    tmp_path: Path,
) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    turn_ids = [UUID(f"22000000-0000-0000-0000-0000000000{i:02d}") for i in range(1, 6)]
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            uow.conversations.add(conversation())
            for sequence, turn_id in enumerate(turn_ids, start=1):
                uow.turns.add(
                    _turn(
                        CONVERSATION_ID,
                        sequence,
                        turn_id=turn_id,
                        user_text=f"turn {sequence}",
                    )
                )
            await uow.commit()

        async with SqlAlchemyUnitOfWork(factory) as uow:
            recent, has_older = await uow.turns.list_recent(CONVERSATION_ID, limit=2)
            assert [t.sequence for t in recent] == [4, 5]
            assert has_older is True

            older, has_older_2 = await uow.turns.list_before(
                CONVERSATION_ID, before_sequence=4, limit=2
            )
            assert [t.sequence for t in older] == [2, 3]
            assert has_older_2 is True

            oldest, has_older_3 = await uow.turns.list_before(
                CONVERSATION_ID, before_sequence=2, limit=2
            )
            assert [t.sequence for t in oldest] == [1]
            assert has_older_3 is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_and_latest_turns_for_batch_lookup_across_conversations(
    tmp_path: Path,
) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    conversation_a = UUID("23000000-0000-0000-0000-000000000001")
    conversation_b = UUID("23000000-0000-0000-0000-000000000002")
    conversation_c = UUID("23000000-0000-0000-0000-000000000003")
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            for conversation_id in (conversation_a, conversation_b, conversation_c):
                uow.conversations.add(_conversation(conversation_id, CREATED_AT))
            uow.turns.add(
                _turn(
                    conversation_a,
                    1,
                    turn_id=UUID("23000000-0000-0000-0000-000000000011"),
                    user_text="  first question   with   spaces ",
                )
            )
            uow.turns.add(
                _turn(
                    conversation_a,
                    2,
                    turn_id=UUID("23000000-0000-0000-0000-000000000012"),
                    user_text="second question",
                )
            )
            uow.turns.add(
                _turn(
                    conversation_b,
                    1,
                    turn_id=UUID("23000000-0000-0000-0000-000000000021"),
                    user_text="only question",
                )
            )
            # conversation_c has no turns at all -- must not appear in either map.
            await uow.commit()

        async with SqlAlchemyUnitOfWork(factory) as uow:
            ids = [conversation_a, conversation_b, conversation_c]
            first_turns = await uow.turns.first_turns_for(ids)
            latest_turns = await uow.turns.latest_turns_for(ids)
            # empty id list must short-circuit without querying.
            empty_first = await uow.turns.first_turns_for([])
            empty_latest = await uow.turns.latest_turns_for([])

        assert first_turns[conversation_a].sequence == 1
        assert first_turns[conversation_b].sequence == 1
        assert conversation_c not in first_turns
        assert latest_turns[conversation_a].sequence == 2
        assert latest_turns[conversation_b].sequence == 1
        assert conversation_c not in latest_turns
        assert empty_first == {}
        assert empty_latest == {}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_save_of_unknown_conversation_or_turn_is_explicit(tmp_path: Path) -> None:
    engine, factory = await create_uow_factory(tmp_path)
    try:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            with pytest.raises(RepositoryEntityNotFoundError):
                await uow.conversations.save(conversation())
            with pytest.raises(RepositoryEntityNotFoundError):
                await uow.turns.save(
                    processing_turn(
                        1,
                        turn_id=UUID("10000000-0000-0000-0000-000000000041"),
                    )
                )
    finally:
        await engine.dispose()
