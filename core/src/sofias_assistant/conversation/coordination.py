"""Process-local coordination of active Conversation operations."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID


class ConversationActivityConflictError(RuntimeError):
    """Raised when an exclusive voice activity conflicts with another activity."""


class ConversationActivityLease:
    """One explicitly released, process-local voice activity lease."""

    def __init__(self, state: "_ConversationActivityState") -> None:
        self._state = state
        self._released = False

    async def release(self) -> None:
        """Release this lease exactly once; repeated release is harmless."""

        if self._released:
            return
        async with self._state.gate:
            if not self._released:
                self._state.voice_active = False
                self._released = True


@dataclass(slots=True)
class _ConversationActivityState:
    gate: asyncio.Lock = field(default_factory=asyncio.Lock)
    text_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending_text: int = 0
    text_active: bool = False
    voice_active: bool = False
    context_revision: int = 0


class ConversationActivityCoordinator:
    """Coordinate process-local text and voice activities for one SofiaCore."""

    def __init__(self) -> None:
        self._states: dict[UUID, _ConversationActivityState] = {}

    @asynccontextmanager
    async def text_activity(self, conversation_id: UUID) -> AsyncIterator[None]:
        """Serialize text while rejecting a currently active voice interaction."""

        state = self._state_for(conversation_id)
        async with state.gate:
            if state.voice_active:
                raise ConversationActivityConflictError(
                    "A voice activity is already active for this conversation"
                )
            state.pending_text += 1
        try:
            async with state.text_lock:
                async with state.gate:
                    state.pending_text -= 1
                    state.text_active = True
                try:
                    yield
                finally:
                    async with state.gate:
                        state.text_active = False
        except BaseException:
            async with state.gate:
                if state.pending_text > 0:
                    state.pending_text -= 1
            raise

    @asynccontextmanager
    async def voice_activity(self, conversation_id: UUID) -> AsyncIterator[None]:
        """Acquire one fail-fast exclusive voice activity for a Conversation."""

        lease = await self.acquire_voice_activity(conversation_id)
        try:
            yield
        finally:
            await lease.release()

    async def acquire_voice_activity(
        self, conversation_id: UUID
    ) -> ConversationActivityLease:
        """Acquire an exclusive lease that may span multiple runtime calls."""

        state = self._state_for(conversation_id)
        async with state.gate:
            if state.voice_active or state.text_active or state.pending_text:
                raise ConversationActivityConflictError(
                    "Another activity is already active for this conversation"
                )
            state.voice_active = True
        return ConversationActivityLease(state)

    async def context_revision(self, conversation_id: UUID) -> int:
        """Return the current process-local durable-context revision."""

        state = self._state_for(conversation_id)
        async with state.gate:
            return state.context_revision

    async def mark_context_changed(self, conversation_id: UUID) -> int:
        """Advance revision after a completed Turn has durably committed."""

        state = self._state_for(conversation_id)
        async with state.gate:
            state.context_revision += 1
            return state.context_revision

    def _state_for(self, conversation_id: UUID) -> _ConversationActivityState:
        if not isinstance(conversation_id, UUID):
            raise ValueError("conversation_id must be a UUID")
        return self._states.setdefault(conversation_id, _ConversationActivityState())
