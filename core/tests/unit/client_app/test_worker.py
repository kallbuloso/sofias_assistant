"""Unit tests for ClientWorker (Gate I18: privacy, history, voice, tasks)."""

from __future__ import annotations

import os
import time
from typing import Any, cast
from uuid import UUID, uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.client_app.audio import (
    FakeAudioInputDevice,
    FakeAudioOutputDevice,
)
from sofias_assistant.client_app.qt_app import ClientWorker
from sofias_assistant.client_app.service import ClientApplicationService


@pytest.fixture(scope="session")
def qapplication() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


class FakeApi:
    def __init__(self) -> None:
        self.conversation_id = uuid4()
        self.cancel_result: dict[str, Any] = {"status": "CANCELLING"}
        self.cancel_calls: list[UUID] = []
        self.turns_page: dict[str, Any] = {"turns": [], "has_older": False}
        self.stream_should_fail = False
        self.realtime_connection: Any = None

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
        return self.conversation_id

    def stream_text(self, conversation_id, text, *, locality, cloud_context_eligible):
        if self.stream_should_fail:
            raise RuntimeError("transport dropped")
        return iter([{"type": "text_delta", "text": "hi"}])

    def cancel_task(self, task_id: UUID) -> dict[str, Any]:
        self.cancel_calls.append(task_id)
        return self.cancel_result

    def list_conversation_turns(
        self, conversation_id, *, limit=50, before_sequence=None
    ):
        return self.turns_page

    def realtime(self):
        return self.realtime_connection


def _worker_with_service(api: FakeApi) -> ClientWorker:
    worker = ClientWorker("http://127.0.0.1:8989", "credential")
    worker._service = ClientApplicationService(cast(CoreApiClient, api))
    worker._service.snapshot = worker._service.refresh()
    return worker


def test_cancel_task_reports_when_already_finished(qapplication: QApplication) -> None:
    api = FakeApi()
    api.cancel_result = {"status": "SUCCEEDED"}
    worker = _worker_with_service(api)
    messages: list[str] = []
    worker.failure.connect(messages.append)

    worker.cancel_task(str(uuid4()))

    assert any("already finished" in message for message in messages)


def test_cancel_task_active_status_has_no_already_finished_message(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    api.cancel_result = {"status": "CANCELLING"}
    worker = _worker_with_service(api)
    messages: list[str] = []
    worker.failure.connect(messages.append)

    worker.cancel_task(str(uuid4()))

    assert not any("already finished" in message for message in messages)


def test_send_text_failure_recovers_without_resending(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    api.stream_should_fail = True
    api.turns_page = {
        "turns": [
            {
                "sequence": 1,
                "status": "COMPLETED",
                "user_text": "hello",
                "assistant_text": "hi there",
            }
        ],
        "has_older": False,
    }
    worker = _worker_with_service(api)
    recovered: list[dict[str, Any]] = []
    worker.conversation_recovered.connect(recovered.append)

    worker.send_text("hello", "local_only", False)

    assert len(recovered) == 1
    assert recovered[0]["turns"][0]["assistant_text"] == "hi there"


def test_handle_voice_event_assistant_audio_chunk_writes_to_output(
    qapplication: QApplication,
) -> None:
    worker = ClientWorker("http://127.0.0.1:8989", "credential")
    output = FakeAudioOutputDevice()
    output.start()
    worker._output_device = output

    worker._handle_voice_event({"type": "assistant_audio_chunk", "audio": b"\x01\x02"})

    assert output.written == [b"\x01\x02"]


def test_handle_voice_event_transcripts_emit_signals(
    qapplication: QApplication,
) -> None:
    worker = ClientWorker("http://127.0.0.1:8989", "credential")
    user_texts: list[str] = []
    assistant_texts: list[str] = []
    worker.voice_transcript.connect(user_texts.append)
    worker.voice_assistant_text.connect(assistant_texts.append)

    worker._handle_voice_event({"type": "user_transcript.final", "text": "hello"})
    worker._handle_voice_event(
        {"type": "assistant_transcript.final", "text": "hi there"}
    )

    assert user_texts == ["hello"]
    assert assistant_texts == ["hi there"]


def test_handle_voice_event_turn_completed_sets_listening_state(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    worker = _worker_with_service(api)
    states: list[str] = []
    worker.voice_changed.connect(states.append)

    worker._handle_voice_event({"type": "turn.completed"})

    assert states[-1] == "LISTENING"


def test_handle_voice_event_turn_failed_emits_failure_and_error_state(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    worker = _worker_with_service(api)
    states: list[str] = []
    messages: list[str] = []
    worker.voice_changed.connect(states.append)
    worker.failure.connect(messages.append)

    worker._handle_voice_event({"type": "turn.failed"})

    assert states[-1] == "ERROR"
    assert messages


def test_handle_voice_event_session_closed_sets_idle(
    qapplication: QApplication,
) -> None:
    worker = ClientWorker("http://127.0.0.1:8989", "credential")
    states: list[str] = []
    worker.voice_changed.connect(states.append)

    worker._handle_voice_event({"type": "session.closed"})

    assert states[-1] == "IDLE"


class FakeRealtimeConnection:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.sent_audio: list[bytes] = []
        self.opened_with: tuple[Any, ...] | None = None
        self.stopped = False

    def open(self, conversation_id, *, locality, cloud_context_eligible) -> None:
        self.opened_with = (conversation_id, locality, cloud_context_eligible)

    def start(self) -> None:
        return None

    def send_audio(self, chunk: bytes) -> None:
        self.sent_audio.append(chunk)

    def pump_events(self):
        yield from self._events

    def stop(self) -> None:
        self.stopped = True


def test_start_voice_captures_microphone_and_sends_audio(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection(
        [{"type": "turn.completed"}, {"type": "session.closed"}]
    )
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    worker._input_device_factory = lambda: FakeAudioInputDevice(
        [b"\x00\x01", b"\x02\x03"]
    )
    worker._output_device_factory = FakeAudioOutputDevice
    states: list[str] = []
    worker.voice_changed.connect(states.append)

    worker.start_voice("local_only", False)
    # The pump runs on a real background thread; give it a bounded moment.
    for _ in range(50):
        if worker._pump_thread is not None and not worker._pump_thread.is_alive():
            break
        time.sleep(0.02)

    assert connection.opened_with == (api.conversation_id, "local_only", False)
    assert connection.sent_audio == [b"\x00\x01", b"\x02\x03"]
    assert "LISTENING" in states


def test_stop_voice_stops_devices_and_connection(qapplication: QApplication) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    input_device = FakeAudioInputDevice([])
    output_device = FakeAudioOutputDevice()
    worker._input_device_factory = lambda: input_device
    worker._output_device_factory = lambda: output_device

    worker.start_voice("local_only", False)
    for _ in range(50):
        if worker._pump_thread is not None and not worker._pump_thread.is_alive():
            break
        time.sleep(0.02)
    worker.stop_voice()

    assert input_device.stopped is True
    assert output_device.stopped is True
    assert connection.stopped is True
