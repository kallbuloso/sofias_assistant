"""Tests for the SAS-03A in-process desktop bridge."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

from sofias_assistant.client_app.in_process import InProcessCoreApiClient


class _FakeConversationRuntime:
    def __init__(self, conversation_id: UUID) -> None:
        self.conversation_id = conversation_id

    async def create_conversation(self):
        return SimpleNamespace(id=self.conversation_id)


class _FakeHost:
    def __init__(self) -> None:
        self.conversation_id = uuid4()
        self.core = SimpleNamespace(
            conversation_runtime=_FakeConversationRuntime(self.conversation_id)
        )
        self.stream_calls: list[tuple[UUID, str, str, bool]] = []

    def call(self, coroutine, *, timeout: float = 60.0):
        del timeout
        return asyncio.run(coroutine)

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
        yield {"type": "text_delta", "text": "Olá"}
        yield {"type": "turn_completed"}


class _UnusedHttp:
    def close(self) -> None:
        pass


def test_create_conversation_bypasses_http() -> None:
    host = _FakeHost()
    client = InProcessCoreApiClient(
        host,
        "http://127.0.0.1:8989",
        "test-credential",
        http_client=_UnusedHttp(),
    )

    assert client.create_conversation() == host.conversation_id


def test_stream_text_bypasses_http_and_preserves_wire_shape() -> None:
    host = _FakeHost()
    client = InProcessCoreApiClient(
        host,
        "http://127.0.0.1:8989",
        "test-credential",
        http_client=_UnusedHttp(),
    )

    events = list(
        client.stream_text(
            host.conversation_id,
            "Oi Sofia",
            locality="cloud_allowed",
            cloud_context_eligible=True,
        )
    )

    assert events == [
        {"type": "text_delta", "text": "Olá"},
        {"type": "turn_completed"},
    ]
    assert host.stream_calls == [
        (host.conversation_id, "Oi Sofia", "cloud_allowed", True)
    ]
