"""Runtime shutdown signal wiring (Desktop/Core Interaction Contract v1 SS23).

The authenticated `POST /api/v1/runtime/shutdown` transport handler calls
`RuntimeShutdownSignal.request(...)`. The host's existing `_wait_for_shutdown`
wakes on the very same `asyncio.Event` it already accepts as `shutdown_event`,
so no second shutdown mechanism or global kill hack is introduced.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID


@dataclass(slots=True)
class RuntimeShutdownSignal:
    """Validate a shutdown request against the currently active Core lifecycle."""

    event: asyncio.Event
    runtime_session_id_provider: Callable[[], UUID | None]

    def request(self, *, runtime_session_id: UUID) -> bool:
        """Accept a shutdown request only for the currently active lifecycle.

        Returns whether the request matched the active lifecycle. Idempotent
        for repeated valid requests: a second accepted request for the same
        lifecycle simply observes the event already set (Contract v1 SS23).
        """

        current = self.runtime_session_id_provider()
        if current is None or current != runtime_session_id:
            return False
        if not self.event.is_set():
            self.event.set()
        return True
