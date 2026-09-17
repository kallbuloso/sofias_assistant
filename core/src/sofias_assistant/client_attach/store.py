"""ClientAttachStore contract (Desktop/Core Interaction Contract v1 SS8)."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sofias_assistant.client_attach.models import ClientAttachRecord


class ClientAttachStore(Protocol):
    """Publish/read/compare-delete one current attach record per instance_key."""

    def publish(self, instance_key: str, record: ClientAttachRecord) -> None:
        """Replace the current attach record for one logical Core instance."""
        ...

    def read(self, instance_key: str) -> ClientAttachRecord | None:
        """Return the current attach record, or `None` when absent/unreadable.

        A structurally invalid stored record is treated as absent: callers
        (the Desktop attach algorithm) handle "no record" and "stale record"
        through the same rediscovery/launch path (Contract v1 SS12/SS15).
        """
        ...

    def delete_if_current(self, instance_key: str, runtime_session_id: UUID) -> bool:
        """Delete the record only if it still belongs to `runtime_session_id`.

        Returns whether a matching record was deleted. An older Core lifecycle
        can never delete a newer one's record this way (Contract v1 SS11).
        """
        ...


class InMemoryClientAttachStore:
    """Deterministic in-memory `ClientAttachStore` fake required for tests.

    Not used by the packaged Windows product; `WindowsClientAttachStore` is
    the production implementation (Contract v1 SS8-SS9).
    """

    def __init__(self) -> None:
        self._records: dict[str, ClientAttachRecord] = {}

    def publish(self, instance_key: str, record: ClientAttachRecord) -> None:
        self._records[instance_key] = record

    def read(self, instance_key: str) -> ClientAttachRecord | None:
        return self._records.get(instance_key)

    def delete_if_current(self, instance_key: str, runtime_session_id: UUID) -> bool:
        current = self._records.get(instance_key)
        if current is None or current.runtime_session_id != runtime_session_id:
            return False
        del self._records[instance_key]
        return True
