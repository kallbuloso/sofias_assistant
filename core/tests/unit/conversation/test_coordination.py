"""Deterministic tests for shared Conversation activity coordination."""

import asyncio
from uuid import uuid4

import pytest

from sofias_assistant.conversation.coordination import (
    ConversationActivityConflictError,
    ConversationActivityCoordinator,
)


@pytest.mark.asyncio
async def test_text_activities_serialize_and_different_conversations_overlap() -> None:
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    other_conversation_id = uuid4()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()
    other_entered = asyncio.Event()

    async def first() -> None:
        async with coordinator.text_activity(conversation_id):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        async with coordinator.text_activity(conversation_id):
            second_entered.set()

    async def other() -> None:
        async with coordinator.text_activity(other_conversation_id):
            other_entered.set()

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    other_task = asyncio.create_task(other())
    await other_entered.wait()
    assert not second_entered.is_set()
    release_first.set()
    await asyncio.gather(first_task, second_task, other_task)
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_voice_conflicts_and_leases_release_after_exception_and_cancellation() -> (
    None
):
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    async with coordinator.voice_activity(conversation_id):
        with pytest.raises(ConversationActivityConflictError):
            async with coordinator.text_activity(conversation_id):
                pass
        with pytest.raises(ConversationActivityConflictError):
            async with coordinator.voice_activity(conversation_id):
                pass
    with pytest.raises(RuntimeError):
        async with coordinator.text_activity(conversation_id):
            raise RuntimeError("expected")
    async with coordinator.voice_activity(conversation_id):
        pass
    entered = asyncio.Event()

    async def cancelled_voice() -> None:
        async with coordinator.voice_activity(conversation_id):
            entered.set()
            await asyncio.Future[None]()

    task = asyncio.create_task(cancelled_voice())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with coordinator.text_activity(conversation_id):
        pass


@pytest.mark.asyncio
async def test_text_activity_conflicts_with_voice_and_context_revision_is_explicit() -> (
    None
):
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    async with coordinator.text_activity(conversation_id):
        with pytest.raises(ConversationActivityConflictError):
            async with coordinator.voice_activity(conversation_id):
                pass
    assert await coordinator.context_revision(conversation_id) == 0
    assert await coordinator.mark_context_changed(conversation_id) == 1
    assert await coordinator.context_revision(conversation_id) == 1


@pytest.mark.asyncio
async def test_voice_transitions_serialize_for_one_conversation() -> None:
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()
    second_attempted = asyncio.Event()

    async def first() -> None:
        async with coordinator.voice_transition(conversation_id):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        second_attempted.set()
        async with coordinator.voice_transition(conversation_id):
            second_entered.set()

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await second_attempted.wait()
    assert not second_entered.is_set()
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_voice_transitions_are_independent_between_conversations() -> None:
    coordinator = ConversationActivityCoordinator()
    first_conversation = uuid4()
    second_conversation = uuid4()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with coordinator.voice_transition(first_conversation):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        async with coordinator.voice_transition(second_conversation):
            second_entered.set()

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await second_entered.wait()
    assert not release_first.is_set()
    release_first.set()
    await asyncio.gather(first_task, second_task)


@pytest.mark.asyncio
async def test_voice_transition_does_not_acquire_or_block_voice_activity() -> None:
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()

    async with coordinator.voice_transition(conversation_id):
        lease = await coordinator.acquire_voice_activity(conversation_id)
        await lease.release()

    lease = await coordinator.acquire_voice_activity(conversation_id)
    await lease.release()


@pytest.mark.asyncio
async def test_voice_transition_coexists_with_owned_lease_and_context_revision() -> (
    None
):
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    lease = await coordinator.acquire_voice_activity(conversation_id)
    try:
        async with coordinator.voice_transition(conversation_id):
            assert await coordinator.context_revision(conversation_id) == 0
            assert await coordinator.mark_context_changed(conversation_id) == 1
    finally:
        await lease.release()
    assert await coordinator.context_revision(conversation_id) == 1


@pytest.mark.asyncio
async def test_cancelled_waiting_voice_transition_does_not_poison_lock() -> None:
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    entered = asyncio.Event()
    attempting = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with coordinator.voice_transition(conversation_id):
            entered.set()
            await release.wait()

    async def waiter() -> None:
        attempting.set()
        async with coordinator.voice_transition(conversation_id):
            raise AssertionError("cancelled waiter acquired the transition")

    holder_task = asyncio.create_task(holder())
    await entered.wait()
    waiter_task = asyncio.create_task(waiter())
    await attempting.wait()
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task
    release.set()
    await holder_task

    async with coordinator.voice_transition(conversation_id):
        pass


@pytest.mark.asyncio
async def test_cancelled_voice_transition_releases_lock() -> None:
    coordinator = ConversationActivityCoordinator()
    conversation_id = uuid4()
    entered = asyncio.Event()

    async def cancelled_holder() -> None:
        async with coordinator.voice_transition(conversation_id):
            entered.set()
            await asyncio.Future[None]()

    task = asyncio.create_task(cancelled_holder())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with coordinator.voice_transition(conversation_id):
        pass
