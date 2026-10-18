"""Focused tests for the SAS-03A application composition root."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from sofias_assistant.application.client_adapter import ApplicationCoreApiClient

CORE_ROOT = Path(__file__).resolve().parents[3]


class _FakeDesktop:
    def __init__(self) -> None:
        self.session_id = uuid4()
        self.sync_calls = 0

    async def sync(self):
        self.sync_calls += 1
        return {
            "core": {
                "state": "running",
                "health": {"status": "healthy", "components": []},
            },
            "notifications": [],
            "tasks": [],
        }


class _FakeVoice:
    def __init__(self) -> None:
        self.session_id = uuid4()
        self.interaction_id = uuid4()
        self.open_calls: list[tuple[UUID, str, bool]] = []
        self.audio: list[bytes] = []
        self.commits: list[UUID] = []
        self.interrupts: list[tuple[UUID, UUID]] = []
        self.cancels: list[tuple[UUID, UUID]] = []
        self.closes: list[UUID] = []

    async def open(
        self,
        conversation_id: UUID,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> UUID:
        self.open_calls.append(
            (conversation_id, locality, cloud_context_eligible)
        )
        return self.session_id

    async def start(self, session_id: UUID) -> UUID:
        assert session_id == self.session_id
        return self.interaction_id

    async def send_audio(self, session_id: UUID, audio: bytes) -> None:
        assert session_id == self.session_id
        self.audio.append(audio)

    async def commit(self, session_id: UUID) -> None:
        self.commits.append(session_id)

    async def interrupt(self, session_id: UUID, interaction_id: UUID) -> None:
        self.interrupts.append((session_id, interaction_id))

    async def cancel(self, session_id: UUID, interaction_id: UUID) -> None:
        self.cancels.append((session_id, interaction_id))

    async def close(self, session_id: UUID) -> None:
        self.closes.append(session_id)


class _FakeApplication:
    def __init__(self) -> None:
        self.conversation_id = uuid4()
        self.stream_calls: list[tuple[UUID, str, str, bool]] = []
        self.desktop = _FakeDesktop()
        self.voice = _FakeVoice()
        self.voice_events = [
            {"type": "assistant_audio_chunk", "audio": b"\x01\x02"},
            {"type": "session.closed"},
        ]

    def call(self, coroutine, *, timeout: float = 60.0):
        del timeout
        return asyncio.run(coroutine)

    def stream_voice_events(self, session_id: UUID):
        assert session_id == self.voice.session_id
        yield from self.voice_events

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
    client = ApplicationCoreApiClient(application)

    assert client.create_conversation() == application.conversation_id


def test_application_adapter_streams_text_directly() -> None:
    application = _FakeApplication()
    client = ApplicationCoreApiClient(application)

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
    client = ApplicationCoreApiClient(application)
    client.session_id = uuid4()

    client.close()

    assert client.session_id is None


def test_application_adapter_connects_without_http() -> None:
    application = _FakeApplication()
    client = ApplicationCoreApiClient(application)

    payload = client.connect()

    assert payload["core"]["state"] == "running"
    assert application.desktop.sync_calls == 1
    assert client.session_id == application.desktop.session_id



def test_realtime_voice_uses_native_application_service() -> None:
    application = _FakeApplication()
    client = ApplicationCoreApiClient(application)

    voice = client.realtime()
    voice.open(
        application.conversation_id,
        locality="cloud_allowed",
        cloud_context_eligible=True,
    )
    interaction_id = voice.start()
    voice.send_audio(b"\x10\x20")
    events = list(voice.pump_events())
    voice.commit()
    voice.stop()

    assert interaction_id == application.voice.interaction_id
    assert application.voice.open_calls == [
        (application.conversation_id, "cloud_allowed", True)
    ]
    assert application.voice.audio == [b"\x10\x20"]
    assert application.voice.commits == [application.voice.session_id]
    assert application.voice.closes == [application.voice.session_id]
    assert events == [
        {"type": "assistant_audio_chunk", "audio": b"\x01\x02"},
        {"type": "session.closed"},
    ]



def test_native_voice_reopens_once_when_session_is_not_idle() -> None:
    application = _FakeApplication()
    first_session = uuid4()
    second_session = uuid4()
    interaction_id = uuid4()

    class _RecoveringVoice:
        def __init__(self) -> None:
            self.open_calls = 0
            self.closed: list[UUID] = []

        async def open(
            self,
            conversation_id: UUID,
            *,
            locality: str,
            cloud_context_eligible: bool,
        ) -> UUID:
            del conversation_id, locality, cloud_context_eligible
            self.open_calls += 1
            return first_session if self.open_calls == 1 else second_session

        async def start(self, session_id: UUID) -> UUID:
            if session_id == first_session:
                raise RuntimeError("Realtime session is not idle")
            assert session_id == second_session
            return interaction_id

        async def close(self, session_id: UUID) -> None:
            self.closed.append(session_id)

    application.voice = _RecoveringVoice()
    client = ApplicationCoreApiClient(application)

    voice = client.realtime()
    voice.open(
        application.conversation_id,
        locality="cloud_allowed",
        cloud_context_eligible=True,
    )

    result = voice.start()

    assert result == interaction_id
    assert application.voice.open_calls == 2
    assert application.voice.closed == [first_session]



def test_canonical_application_root_does_not_compose_loopback_boundary() -> None:
    app_text = (
        CORE_ROOT / "src" / "sofias_assistant" / "application" / "app.py"
    ).read_text(encoding="utf-8")

    assert "LocalClientBoundary" not in app_text
    assert "compatibility_access" not in app_text
    assert "create_app_factory" not in app_text
    assert "http://127.0.0.1" not in app_text
    assert "access.credential" not in app_text


def test_native_application_adapter_has_no_transport_constructor_state() -> None:
    application = _FakeApplication()
    client = ApplicationCoreApiClient(application)

    assert not hasattr(client, "_http")
    assert not hasattr(client, "_credential")



def test_ctrl_c_path_closes_desktop_before_runtime() -> None:
    app_text = (
        CORE_ROOT / "src" / "sofias_assistant" / "application" / "app.py"
    ).read_text(encoding="utf-8")

    keyboard_block = app_text.split("except KeyboardInterrupt:", 1)[1].split(
        "finally:", 1
    )[0]
    assert "window._quit()" in keyboard_block
