"""Client application service layer between Qt and the Core API adapter."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.client_app.models import (
    ClientSnapshot,
    ConnectionState,
    NotificationItem,
    snapshot_from_wire,
)


@dataclass(slots=True)
class ClientApplicationService:
    api: CoreApiClient
    conversation_id: UUID | None = None
    snapshot: ClientSnapshot | None = None

    def connect(self) -> ClientSnapshot:
        payload = self.api.connect()
        self._ensure_conversation()
        return self.refresh(payload)

    def refresh(self, payload: dict[str, Any] | None = None) -> ClientSnapshot:
        payload = payload or self.api.sync()
        if self.conversation_id is not None:
            conversation = self.api.get_conversation(self.conversation_id)
        else:
            conversation = None
        self.snapshot = snapshot_from_wire(
            payload["core"], payload["notifications"], payload["tasks"], conversation
        )
        return self.snapshot

    def _ensure_conversation(self) -> None:
        if self.conversation_id is None:
            self.conversation_id = self.api.create_conversation()

    def stream_text(self, text: str) -> Iterator[dict[str, Any]]:
        self._ensure_conversation()
        assert self.conversation_id is not None
        yield from self.api.stream_text(self.conversation_id, text)

    def acknowledge(self, notification_id: UUID) -> bool:
        return self.api.acknowledge(notification_id)

    def decide_confirmation(self, confirmation_id: UUID, approved: bool) -> None:
        if approved:
            self.api.approve_confirmation(confirmation_id)
        else:
            self.api.deny_confirmation(confirmation_id)

    def cancel_task(self, task_id: UUID) -> dict[str, Any]:
        return self.api.cancel_task(task_id)

    def notification(self, notification_id: UUID) -> NotificationItem | None:
        if self.snapshot is None:
            return None
        return next(
            (
                item
                for item in self.snapshot.notifications
                if item.id == notification_id
            ),
            None,
        )

    @property
    def connection(self) -> ConnectionState:
        return (
            self.snapshot.connection
            if self.snapshot is not None
            else ConnectionState.DISCONNECTED
        )
