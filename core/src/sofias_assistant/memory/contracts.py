"""Narrow Assistant-owned Protocols for the Cognitive Memory boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sofias_assistant.memory.models import (
    CreateMemoryRequest,
    MemoryCapabilities,
    MemoryItem,
    MemoryRecallResult,
    MemorySupersedeResult,
    RecallRequest,
    SupersedeMemoryRequest,
)


class MemoryProvider(Protocol):
    """Assistant-owned boundary the rest of the Core depends on.

    No caller outside `memory/` knows about HTTP, Sofias Memory internals, or
    transport-level retry behavior. Implementations: `SofiasMemoryAdapter`
    (production) and `FakeMemoryProvider` (tests).
    """

    async def probe_contract(self) -> MemoryCapabilities:
        """Negotiate Cognitive Memory compatibility via `GET /api/v1/info`."""
        ...

    async def create_memory(
        self, request: CreateMemoryRequest, *, idempotency_key: str
    ) -> MemoryItem:
        """Create one Cognitive MemoryItem, replaying safely on same-key retry."""
        ...

    async def get_memory(self, memory_id: UUID) -> MemoryItem | None:
        """Return one MemoryItem by exact id, or None when not found."""
        ...

    async def recall_memories(self, request: RecallRequest) -> MemoryRecallResult:
        """Return typed, ranked Cognitive Memory recall results."""
        ...

    async def supersede_memory(
        self,
        memory_id: UUID,
        request: SupersedeMemoryRequest,
        *,
        idempotency_key: str,
    ) -> MemorySupersedeResult:
        """Atomically replace one ACTIVE MemoryItem with a new ACTIVE one."""
        ...

    async def forget_memory(
        self, memory_id: UUID, *, idempotency_key: str
    ) -> MemoryItem:
        """Precisely and destructively forget one exact MemoryItem."""
        ...


class MemoryCandidateExtractor(Protocol):
    """Seam turning raw evidence text into a normalized candidate proposal.

    Never authority: the returned content is a proposal that Memory Policy
    still evaluates before any persistence is attempted.
    """

    async def extract(self, *, text: str) -> str:
        """Return normalized candidate content derived from raw evidence text."""
        ...
