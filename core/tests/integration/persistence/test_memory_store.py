"""Integration tests for Assistant-owned Cognitive Memory runtime persistence."""

from asyncio import to_thread
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
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
from sofias_assistant.memory.store import MemoryStore
from sofias_assistant.persistence.database import create_async_engine
from sofias_assistant.persistence.migration_runner import upgrade_to_head


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"


def _session_factory(url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_candidate_persists_and_reloads_after_simulated_restart(
    tmp_path: Path,
) -> None:
    url = _database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    now = datetime.now(UTC)
    candidate = MemoryCandidate(
        id=uuid4(),
        memory_type=MemoryType.PROFILE,
        scope="global",
        origin_kind=MemoryOriginKind.USER_ASSERTED,
        decision_status=MemoryCandidateDecisionStatus.APPROVED,
        persistence_status=MemoryCandidatePersistenceStatus.PENDING,
        created_at=now,
        updated_at=now,
        conversation_id=uuid4(),
        turn_id=uuid4(),
        cloud_context_eligible=False,
        content="Prefers dark mode.",
    )
    store = MemoryStore(_session_factory(url))
    await store.save_candidate(candidate)

    # Simulate a restart: a fresh store instance against the same database.
    reloaded_store = MemoryStore(_session_factory(url))
    reloaded = await reloaded_store.get_candidate(candidate.id)
    assert reloaded == candidate

    memory_id = uuid4()
    succeeded = replace(
        reloaded,
        persistence_status=MemoryCandidatePersistenceStatus.SUCCEEDED,
        memory_id=memory_id,
        persisted_at=now,
        content=None,
    )
    await reloaded_store.update_candidate(succeeded)

    final_store = MemoryStore(_session_factory(url))
    final = await final_store.get_candidate(candidate.id)
    assert final is not None
    assert final.persistence_status is MemoryCandidatePersistenceStatus.SUCCEEDED
    assert final.memory_id == memory_id
    assert final.content is None


@pytest.mark.asyncio
async def test_operation_persists_and_reloads_after_simulated_restart(
    tmp_path: Path,
) -> None:
    url = _database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    now = datetime.now(UTC)
    operation = MemoryOperation(
        id=uuid4(),
        kind=MemoryOperationKind.FORGET,
        target_memory_id=uuid4(),
        status=MemoryOperationStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    store = MemoryStore(_session_factory(url))
    await store.save_operation(operation)

    reloaded_store = MemoryStore(_session_factory(url))
    reloaded = await reloaded_store.get_operation(operation.id)
    assert reloaded == operation

    succeeded = replace(
        reloaded, status=MemoryOperationStatus.SUCCEEDED, completed_at=now
    )
    await reloaded_store.update_operation(succeeded)

    final_store = MemoryStore(_session_factory(url))
    final = await final_store.get_operation(operation.id)
    assert final is not None
    assert final.status is MemoryOperationStatus.SUCCEEDED
    assert final.completed_at == now


@pytest.mark.asyncio
async def test_get_cloud_context_eligibility_resolves_by_memory_id(
    tmp_path: Path,
) -> None:
    url = _database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    now = datetime.now(UTC)
    store = MemoryStore(_session_factory(url))

    eligible_memory_id = uuid4()
    ineligible_memory_id = uuid4()
    pending_memory_id = uuid4()

    async def _succeeded_candidate(memory_id, cloud_context_eligible: bool) -> None:
        candidate = MemoryCandidate(
            id=uuid4(),
            memory_type=MemoryType.PROFILE,
            scope="global",
            origin_kind=MemoryOriginKind.USER_ASSERTED,
            decision_status=MemoryCandidateDecisionStatus.APPROVED,
            persistence_status=MemoryCandidatePersistenceStatus.SUCCEEDED,
            created_at=now,
            updated_at=now,
            cloud_context_eligible=cloud_context_eligible,
            memory_id=memory_id,
            persisted_at=now,
        )
        await store.save_candidate(candidate)

    await _succeeded_candidate(eligible_memory_id, True)
    await _succeeded_candidate(ineligible_memory_id, False)

    # A PENDING/FAILED persistence attempt is not Assistant-owned truth for
    # this memory_id yet; it must never leak an eligibility value.
    await store.save_candidate(
        MemoryCandidate(
            id=uuid4(),
            memory_type=MemoryType.PROFILE,
            scope="global",
            origin_kind=MemoryOriginKind.USER_ASSERTED,
            decision_status=MemoryCandidateDecisionStatus.APPROVED,
            persistence_status=MemoryCandidatePersistenceStatus.PENDING,
            created_at=now,
            updated_at=now,
            cloud_context_eligible=True,
            memory_id=pending_memory_id,
        )
    )

    assert await store.get_cloud_context_eligibility(eligible_memory_id) is True
    assert await store.get_cloud_context_eligibility(ineligible_memory_id) is False
    assert await store.get_cloud_context_eligibility(pending_memory_id) is None
    assert await store.get_cloud_context_eligibility(uuid4()) is None


@pytest.mark.asyncio
async def test_get_missing_candidate_and_operation_return_none(
    tmp_path: Path,
) -> None:
    url = _database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    store = MemoryStore(_session_factory(url))
    assert await store.get_candidate(uuid4()) is None
    assert await store.get_operation(uuid4()) is None


@pytest.mark.asyncio
async def test_update_missing_candidate_and_operation_raise_key_error(
    tmp_path: Path,
) -> None:
    url = _database_url(tmp_path)
    await to_thread(upgrade_to_head, url)
    store = MemoryStore(_session_factory(url))
    now = datetime.now(UTC)
    with pytest.raises(KeyError):
        await store.update_candidate(
            MemoryCandidate(
                id=uuid4(),
                memory_type=MemoryType.PROFILE,
                scope="global",
                origin_kind=MemoryOriginKind.USER_ASSERTED,
                decision_status=MemoryCandidateDecisionStatus.PENDING,
                persistence_status=MemoryCandidatePersistenceStatus.NOT_REQUESTED,
                created_at=now,
                updated_at=now,
                cloud_context_eligible=False,
            )
        )
    with pytest.raises(KeyError):
        await store.update_operation(
            MemoryOperation(
                id=uuid4(),
                kind=MemoryOperationKind.SUPERSEDE,
                target_memory_id=uuid4(),
                status=MemoryOperationStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
        )
