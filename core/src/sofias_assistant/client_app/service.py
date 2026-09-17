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
        return self.refresh(payload)

    def refresh(self, payload: dict[str, Any] | None = None) -> ClientSnapshot:
        payload = payload or self.api.sync()
        self.snapshot = snapshot_from_wire(
            payload["core"], payload["notifications"], payload["tasks"]
        )
        return self.snapshot

    def start_new_conversation(self) -> UUID:
        """Explicitly create a new Conversation and make it the current one.

        Never called merely because the Desktop started (Contract v1 SS41):
        the current conversation stays `None` until the user starts or
        resumes one, or sends a first message.
        """

        self.conversation_id = self.api.create_conversation()
        return self.conversation_id

    def open_conversation(self, conversation_id: UUID) -> None:
        """Resume an existing Conversation as the current one."""

        self.conversation_id = conversation_id

    def stream_text(
        self, text: str, *, locality: str, cloud_context_eligible: bool
    ) -> Iterator[dict[str, Any]]:
        if self.conversation_id is None:
            self.start_new_conversation()
        assert self.conversation_id is not None
        yield from self.api.stream_text(
            self.conversation_id,
            text,
            locality=locality,
            cloud_context_eligible=cloud_context_eligible,
        )

    def acknowledge(self, notification_id: UUID) -> bool:
        return self.api.acknowledge(notification_id)

    def decide_confirmation(self, confirmation_id: UUID, approved: bool) -> None:
        if approved:
            confirmation = self.api.get_confirmation(confirmation_id)
            lifetime = str(confirmation.get("requested_lifetime", "ONE_SHOT"))
            self.api.approve_confirmation(confirmation_id, lifetime=lifetime)
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
