"""Unit tests for ClientApplicationService (Gate I18 privacy/history changes)."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.client_app.service import ClientApplicationService


class FakeCoreApiClient:
    def __init__(self) -> None:
        self.created_conversation_id = uuid4()
        self.stream_calls: list[tuple[UUID, str, str, bool]] = []
        self.confirmations: dict[UUID, dict[str, Any]] = {}
        self.approve_calls: list[tuple[UUID, str]] = []
        self.deny_calls: list[UUID] = []

    def connect(self) -> dict[str, Any]:
        return {
            "core": {
                "state": "running",
                "health": {"status": "healthy", "components": []},
            },
            "notifications": [],
            "tasks": [],
        }

    def sync(self) -> dict[str, Any]:
        return self.connect()

    def create_conversation(self) -> UUID:
        return self.created_conversation_id

    def stream_text(
        self,
        conversation_id: UUID,
        text: str,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ):
        self.stream_calls.append(
            (conversation_id, text, locality, cloud_context_eligible)
        )
        return iter([{"type": "text_delta", "text": "hi"}])

    def get_confirmation(self, confirmation_id: UUID) -> dict[str, Any]:
        return self.confirmations[confirmation_id]

    def approve_confirmation(
        self, confirmation_id: UUID, *, lifetime: str = "ONE_SHOT"
    ):
        self.approve_calls.append((confirmation_id, lifetime))
        return {"id": str(confirmation_id)}

    def deny_confirmation(self, confirmation_id: UUID) -> None:
        self.deny_calls.append(confirmation_id)


def _service(api: FakeCoreApiClient) -> ClientApplicationService:
    return ClientApplicationService(cast(CoreApiClient, api))


def test_connect_never_auto_creates_a_conversation() -> None:
    api = FakeCoreApiClient()
    service = _service(api)

    service.connect()

    assert service.conversation_id is None


def test_start_new_conversation_creates_and_tracks_it() -> None:
    api = FakeCoreApiClient()
    service = _service(api)

    conversation_id = service.start_new_conversation()

    assert conversation_id == api.created_conversation_id
    assert service.conversation_id == api.created_conversation_id


def test_open_conversation_sets_the_current_conversation_without_creating() -> None:
    api = FakeCoreApiClient()
    service = _service(api)
    existing_id = uuid4()

    service.open_conversation(existing_id)

    assert service.conversation_id == existing_id
    assert api.created_conversation_id != existing_id


def test_stream_text_lazily_creates_a_conversation_and_forwards_privacy_values() -> (
    None
):
    api = FakeCoreApiClient()
    service = _service(api)

    list(
        service.stream_text(
            "hello", locality="cloud_preferred", cloud_context_eligible=True
        )
    )

    assert len(api.stream_calls) == 1
    conversation_id, text, locality, cloud_context_eligible = api.stream_calls[0]
    assert conversation_id == api.created_conversation_id
    assert text == "hello"
    assert locality == "cloud_preferred"
    assert cloud_context_eligible is True


def test_stream_text_reuses_the_current_conversation_once_set() -> None:
    api = FakeCoreApiClient()
    service = _service(api)
    resumed_id = uuid4()
    service.open_conversation(resumed_id)

    list(service.stream_text("hi", locality="local_only", cloud_context_eligible=False))

    assert api.stream_calls[0][0] == resumed_id


def test_decide_confirmation_approves_with_the_confirmations_actual_lifetime() -> None:
    api = FakeCoreApiClient()
    service = _service(api)
    confirmation_id = uuid4()
    api.confirmations[confirmation_id] = {
        "requested_lifetime": "SESSION",
        "capability": "filesystem.write",
    }

    service.decide_confirmation(confirmation_id, True)

    assert api.approve_calls == [(confirmation_id, "SESSION")]


def test_decide_confirmation_deny_never_calls_approve() -> None:
    api = FakeCoreApiClient()
    service = _service(api)
    confirmation_id = uuid4()

    service.decide_confirmation(confirmation_id, False)

    assert api.deny_calls == [confirmation_id]
    assert api.approve_calls == []
