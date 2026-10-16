"""Focused tests for the SAS-03A application composition root."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from sofias_assistant.application.client_adapter import ApplicationCoreApiClient

CORE_ROOT = Path(__file__).resolve().parents[3]


class _FakeApplication:
    def __init__(self) -> None:
        self.conversation_id = uuid4()
        self.stream_calls: list[tuple[UUID, str, str, bool]] = []

    def create_conversation(self) -> UUID:
        return self.conversation_id

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
    def __init__(self) -> None:
        self.closed = False
        self.delete_calls = 0

    def delete(self, *_args, **_kwargs):
        self.delete_calls += 1
        raise AssertionError("shutdown must not perform an HTTP DELETE")

    def close(self) -> None:
        self.closed = True


def test_application_adapter_creates_conversation_directly() -> None:
    application = _FakeApplication()
    client = ApplicationCoreApiClient(
        application,
        "http://127.0.0.1:8989",
        "test-credential",
        http_client=_UnusedHttp(),
    )

    assert client.create_conversation() == application.conversation_id


def test_application_adapter_streams_text_directly() -> None:
    application = _FakeApplication()
    client = ApplicationCoreApiClient(
        application,
        "http://127.0.0.1:8989",
        "test-credential",
        http_client=_UnusedHttp(),
    )

    events = list(
        client.stream_text(
            application.conversation_id,
            "Oi Sofia",
            locality="cloud_allowed",
            cloud_context_eligible=True,
        )
    )

    assert events == [
        {"type": "text_delta", "text": "Olá"},
        {"type": "turn_completed"},
    ]
    assert application.stream_calls == [
        (application.conversation_id, "Oi Sofia", "cloud_allowed", True)
    ]


def test_main_uses_sofia_application_root() -> None:
    main_text = (CORE_ROOT / "main.py").read_text(encoding="utf-8")

    assert "from sofias_assistant.application import run_desktop" in main_text
    assert "client_app.in_process" not in main_text
    assert "host.runner" not in main_text



def test_application_adapter_close_is_local_and_nonblocking() -> None:
    application = _FakeApplication()
    http = _UnusedHttp()
    client = ApplicationCoreApiClient(
        application,
        "http://127.0.0.1:8989",
        "test-credential",
        http_client=http,
    )
    client.session_id = uuid4()

    client.close()

    assert client.session_id is None
    assert http.closed is True
    assert http.delete_calls == 0
