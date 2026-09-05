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
