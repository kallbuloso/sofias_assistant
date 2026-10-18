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
        self.stream_events: list[dict[str, Any]] = [
            {"type": "text_delta", "text": "hi"}
        ]
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
        return iter(self.stream_events)

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


def test_send_text_surfaces_safe_turn_failure_details(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    api.stream_events = [
        {
            "type": "turn_failed",
            "error_code": "authentication_error",
            "error_message": "OpenAI authentication failed",
        }
    ]
    worker = _worker_with_service(api)
    failures: list[tuple[str, str]] = []
    worker.conversation_failed.connect(
        lambda code, message: failures.append((code, message))
    )

    worker.send_text("hello", "cloud_allowed", False)

    assert failures == [
        ("authentication_error", "OpenAI authentication failed")
    ]


def test_send_text_local_only_routing_failure_is_actionable(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    api.stream_events = [
        {
            "type": "turn_failed",
            "error_code": "routing_error",
            "error_message": "No compatible text model is available",
        }
    ]
    worker = _worker_with_service(api)
    failures: list[tuple[str, str]] = []
    worker.conversation_failed.connect(
        lambda code, message: failures.append((code, message))
    )

    worker.send_text("hello", "local_only", False)

    assert failures[0][0] == "routing_error"
    assert "Allow cloud" in failures[0][1]


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

    assert states[-1] == "READY"


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



def test_start_voice_failure_closes_open_realtime_session(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)

    class _FailingOutput:
        def start(self) -> None:
            raise RuntimeError("speaker failed")

        def stop(self) -> None:
            pass

    worker._output_device_factory = _FailingOutput

    worker.start_voice("cloud_allowed", True)

    assert connection.opened_with == (
        api.conversation_id,
        "cloud_allowed",
        True,
    )
    assert connection.stopped is True



def test_completed_voice_turn_becomes_ready_without_microphone(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    input_device = FakeAudioInputDevice([])
    worker._input_device = input_device
    states: list[str] = []
    worker.voice_changed.connect(states.append)

    worker._handle_voice_event({"type": "turn.completed"})

    assert states[-1] == "READY"


def test_commit_voice_releases_microphone(qapplication: QApplication) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    worker._voice = connection
    input_device = FakeAudioInputDevice([])
    worker._input_device = input_device

    worker.commit_voice()

    assert input_device.stopped is True
    assert worker._input_device is None


def test_final_voice_transcripts_only_are_emitted(
    qapplication: QApplication,
) -> None:
    worker = ClientWorker("http://127.0.0.1:8989", "credential")
    user: list[str] = []
    assistant: list[str] = []
    worker.voice_transcript.connect(user.append)
    worker.voice_assistant_text.connect(assistant.append)

    worker._handle_voice_event({"type": "user_transcript.partial", "text": "Ol"})
    worker._handle_voice_event({"type": "user_transcript.final", "text": "Olá"})
    worker._handle_voice_event(
        {"type": "assistant_transcript.partial", "text": "Oi"}
    )
    worker._handle_voice_event(
        {"type": "assistant_transcript.final", "text": "Oi, Amaral!"}
    )

    assert user == ["Olá"]
    assert assistant == ["Oi, Amaral!"]



def test_assistant_audio_is_queued_through_worker_signal(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    worker = _worker_with_service(api)
    output = FakeAudioOutputDevice()
    output.start()
    worker._output_device = output

    worker._handle_voice_event(
        {"type": "assistant_audio_chunk", "audio": b"\x00\x01"}
    )
    qapplication.processEvents()

    assert output.written == [b"\x00\x01"]



def test_late_closed_event_from_old_voice_is_ignored(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    old_voice = FakeRealtimeConnection([])
    new_voice = FakeRealtimeConnection([])
    worker = _worker_with_service(api)
    worker._voice = new_voice
    worker._set_voice_state(VoiceState.LISTENING)

    worker.voice_event.emit(old_voice, {"type": "session.closed"})
    qapplication.processEvents()

    assert worker._voice is new_voice
    assert worker._voice_status is VoiceState.LISTENING


def test_current_closed_event_sets_idle(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    voice = FakeRealtimeConnection([])
    worker = _worker_with_service(api)
    worker._voice = voice
    worker._set_voice_state(VoiceState.READY)

    worker.voice_event.emit(voice, {"type": "session.closed"})
    qapplication.processEvents()

    assert worker._voice is None
    assert worker._voice_status is VoiceState.IDLE


def test_turn_interrupted_returns_voice_session_to_ready(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    voice = FakeRealtimeConnection([])
    worker = _worker_with_service(api)
    worker._voice = voice
    worker._set_voice_state(VoiceState.INTERRUPTED)

    worker._handle_voice_event({"type": "turn.interrupted"})

    assert worker._voice_status is VoiceState.READY



def test_stop_voice_keeps_current_conversation(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    worker._service.open_conversation(api.conversation_id)
    worker._voice = connection

    worker.stop_voice()

    assert worker._service.conversation_id == api.conversation_id
    assert connection.stopped is True


def test_switching_conversation_stops_voice_before_rebinding(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    target = uuid4()
    worker._service.open_conversation(api.conversation_id)
    worker._voice = connection

    worker.open_conversation(str(target))

    assert connection.stopped is True
    assert worker._service.conversation_id == target



def test_first_voice_turn_creates_one_current_conversation(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    opened: list[str] = []
    worker.conversation_opened.connect(
        lambda conversation_id, _page: opened.append(conversation_id)
    )

    worker.start_voice("local_only", False)

    assert worker._service.conversation_id == api.conversation_id
    assert opened == [str(api.conversation_id)]


def test_text_after_voice_uses_same_current_conversation(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    connection = FakeRealtimeConnection([])
    api.realtime_connection = connection
    worker = _worker_with_service(api)

    worker.start_voice("local_only", False)
    worker.stop_voice()
    worker.send_text("continue", "local_only", False)

    assert worker._service.conversation_id == api.conversation_id



def test_voice_pump_starts_after_native_interaction_start(
    qapplication: QApplication,
) -> None:
    api = FakeApi()

    class _OrderedRealtime(FakeRealtimeConnection):
        def __init__(self) -> None:
            super().__init__([])
            self.started = False
            self.pump_observed_started = False

        def start(self) -> None:
            self.started = True

        def pump_events(self):
            self.pump_observed_started = self.started
            return
            yield  # pragma: no cover

    connection = _OrderedRealtime()
    api.realtime_connection = connection
    worker = _worker_with_service(api)
    worker._input_device_factory = lambda: FakeAudioInputDevice([])
    worker._output_device_factory = FakeAudioOutputDevice

    worker.start_voice("local_only", False)

    for _ in range(50):
        thread = worker._pump_thread
        if thread is not None and not thread.is_alive():
            break
        time.sleep(0.01)

    assert connection.started is True
    assert connection.pump_observed_started is True


def test_voice_failure_surfaces_provider_detail(
    qapplication: QApplication,
) -> None:
    api = FakeApi()
    worker = _worker_with_service(api)
    messages: list[str] = []
    worker.failure.connect(messages.append)

    worker._handle_voice_event(
        {"type": "interaction.failed", "message": "OpenAI realtime response failed"}
    )

    assert messages[-1] == (
        "Realtime interaction did not complete: OpenAI realtime response failed"
    )
