"""PySide6 Desktop Client: widgets, tray and worker-backed application flows."""

from __future__ import annotations

import html
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any
from uuid import UUID

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sofias_assistant.client_app.api import (
    CoreApiClient,
    CoreApiError,
    CoreValidationError,
    RealtimeVoiceConnection,
)
from sofias_assistant.client_app.audio import (
    AudioDeviceError,
    AudioInputDevice,
    AudioOutputDevice,
    QtAudioInputDevice,
    QtAudioOutputDevice,
)
from sofias_assistant.client_app.dashboard import (
    AIModelsTab,
    HomeTab,
    MemoryIntegrationsTab,
)
from sofias_assistant.client_app.models import (
    ClientSnapshot,
    ConnectionState,
    HealthItem,
    InferencePrivacyPreference,
    NotificationItem,
    TaskItem,
    VoiceState,
)
from sofias_assistant.client_app.service import ClientApplicationService

_LOCALITY_WIRE_VALUES = ("local_only", "cloud_allowed", "cloud_preferred")
_LOCALITY_LABELS = {
    "local_only": "Local only",
    "cloud_allowed": "Allow cloud",
    "cloud_preferred": "Prefer cloud",
}
_TERMINAL_TASK_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}
_ACTIVE_TASK_STATUSES = {
    "QUEUED",
    "RUNNING",
    "WAITING_SCHEDULE",
    "WAITING_CONFIRMATION",
}


class ClientWorker(QObject):
    state_changed = Signal(str)
    snapshot_ready = Signal(object)
    stream_started = Signal()
    stream_delta = Signal(str)
    stream_finished = Signal()
    conversation_failed = Signal(str, str)
    voice_changed = Signal(str)
    voice_transcript = Signal(str)
    voice_assistant_text = Signal(str)
    voice_audio_chunk = Signal(bytes)
    voice_event = Signal(object, object)
    voice_pump_failed = Signal(object, str)
    failure = Signal(str)
    stopped = Signal()
    ai_dashboard_ready = Signal(object)
    routing_preview_ready = Signal(object)
    credential_write_succeeded = Signal(str)
    conversations_ready = Signal(object)
    conversation_opened = Signal(str, object)
    older_turns_ready = Signal(str, object)
    conversation_recovered = Signal(object)
    confirmation_ready = Signal(object)

    def __init__(
        self,
        base_url: str | None = None,
        credential: str | None = None,
        *,
        api_factory: Callable[[], CoreApiClient] | None = None,
        input_device_factory: Any = QtAudioInputDevice,
        output_device_factory: Any = QtAudioOutputDevice,
    ) -> None:
        super().__init__()
        if api_factory is not None:
            self._api_factory = api_factory
        else:
            if base_url is None or credential is None:
                raise ValueError(
                    "base_url and credential are required for legacy transport mode"
                )
            self._api_factory = lambda: CoreApiClient(base_url, credential)
        self._service: ClientApplicationService | None = None
        self._voice: RealtimeVoiceConnection | None = None
        self._voice_status = VoiceState.IDLE
        self._input_device_factory = input_device_factory
        self._output_device_factory = output_device_factory
        self._input_device: AudioInputDevice | None = None
        self._output_device: AudioOutputDevice | None = None
        self._pump_thread: threading.Thread | None = None
        self.voice_audio_chunk.connect(self._play_voice_audio)
        self.voice_event.connect(self._dispatch_voice_event)
        self.voice_pump_failed.connect(self._on_voice_pump_failed)

    @Slot()
    def connect_core(self) -> None:
        self._state(ConnectionState.CONNECTING)
        try:
            self._service = ClientApplicationService(self._api_factory())
            snapshot = self._service.connect()
            self._publish(snapshot)
        except Exception:
            self._state(ConnectionState.DISCONNECTED)
            self.failure.emit("Core is unavailable or authentication failed")

    @Slot()
    def refresh(self) -> None:
        service = self._service
        if service is None:
            self.connect_core()
            return
        try:
            self._publish(service.refresh())
        except CoreApiError as error:
            if "authentication" in str(error).lower():
                self._state(ConnectionState.DISCONNECTED)
            else:
                self._state(ConnectionState.DEGRADED)
            self.failure.emit("Core connection is temporarily unavailable")
        except Exception:
            self._state(ConnectionState.DEGRADED)
            self.failure.emit("Core state could not be synchronized")

    def _ensure_current_conversation(self) -> UUID:
        service = self._service
        if service is None:
            raise RuntimeError("Sofia is not connected")
        if service.conversation_id is None:
            conversation_id = service.start_new_conversation()
            self.conversation_opened.emit(
                str(conversation_id), {"turns": [], "has_older": False}
            )
            self.load_conversations()
        assert service.conversation_id is not None
        return service.conversation_id

    @Slot(str, str, bool)
    def send_text(self, text: str, locality: str, cloud_context_eligible: bool) -> None:
        service = self._service
        if service is None or service.connection is ConnectionState.DISCONNECTED:
            self.failure.emit("Connect to Core before sending a message")
            return
        try:
            self._ensure_current_conversation()
        except Exception:
            self.failure.emit("Conversation could not be created")
            return
        self.stream_started.emit()
        try:
            for event in service.stream_text(
                text, locality=locality, cloud_context_eligible=cloud_context_eligible
            ):
                kind = event.get("type")
                if kind == "text_delta":
                    self.stream_delta.emit(str(event.get("text", "")))
                elif kind in {"turn_failed", "turn_interrupted"}:
                    code = str(event.get("error_code") or kind)
                    message = str(
                        event.get("error_message") or "Conversation turn did not complete"
                    )
                    if code == "routing_error" and locality == "local_only":
                        message = (
                            f"{message}. Privacy is set to Local only; choose "
                            "Sofia → Privacy… → Allow cloud or configure a local model."
                        )
                    elif code == "context_locality_error":
                        message = (
                            f"{message}. The selected model runs in the cloud, but "
                            "this turn is not marked as cloud-context eligible. Open "
                            "Sofia → Privacy…, choose Allow cloud (or Prefer cloud) "
                            "and enable cloud context for this conversation."
                        )
                    print(
                        f"Sofia conversation failed [{code}]: {message}",
                        file=sys.stderr,
                    )
                    self.conversation_failed.emit(code, message)
            self.stream_finished.emit()
            self.refresh()
        except Exception:
            traceback.print_exc()
            self.stream_finished.emit()
            self.failure.emit(
                "Conversation execution failed unexpectedly; details are in the terminal."
            )
            self._recover_current_conversation()

    def _recover_current_conversation(self) -> None:
        """Reload Core-authoritative state after an uncertain stream failure.

        Never resends the text automatically (Contract v1 SS21/SS42):
        `UNKNOWN != failed`, so this only reports what Core actually
        persisted, leaving any retry to an explicit later user action.
        """

        service = self._service
        if service is None or service.conversation_id is None:
            return
        try:
            page = service.api.list_conversation_turns(service.conversation_id, limit=1)
            self.conversation_recovered.emit(page)
        except Exception:
            pass

    @Slot(str)
    def acknowledge(self, notification_id: str) -> None:
        if self._service is None:
            return
        try:
            self._service.acknowledge(UUID(notification_id))
            self.refresh()
        except Exception:
            self.failure.emit("Notification could not be acknowledged")

    @Slot(str)
    def load_confirmation(self, confirmation_id: str) -> None:
        if self._service is None:
            return
        try:
            self.confirmation_ready.emit(
                self._service.api.get_confirmation(UUID(confirmation_id))
            )
        except Exception:
            self.failure.emit("Confirmation details could not be loaded")

    @Slot(str, bool)
    def decide_confirmation(self, confirmation_id: str, approved: bool) -> None:
        if self._service is None:
            return
        try:
            self._service.decide_confirmation(UUID(confirmation_id), approved)
            self.refresh()
        except Exception:
            self.failure.emit("Confirmation decision could not be sent")

    @Slot(str)
    def cancel_task(self, task_id: str) -> None:
        if self._service is None:
            return
        try:
            result = self._service.cancel_task(UUID(task_id))
            if str(result.get("status")) in _TERMINAL_TASK_STATUSES:
                self.failure.emit("Task already finished; cancel had no effect")
            self.refresh()
        except Exception:
            self.failure.emit("Task could not be cancelled")

    # -- Conversation History (Gate I18, SA-B040) -------------------------

    @Slot()
    def load_conversations(self) -> None:
        service = self._service
        if service is None:
            return
        try:
            self.conversations_ready.emit(service.api.list_conversations(limit=50))
        except Exception:
            self.failure.emit("Conversation list could not be loaded")

    @Slot()
    def start_new_conversation(self) -> None:
        service = self._service
        if service is None:
            return
        try:
            if self._voice is not None:
                self.stop_voice()
            conversation_id = service.start_new_conversation()
            self.conversation_opened.emit(
                str(conversation_id), {"turns": [], "has_older": False}
            )
            self.load_conversations()
        except Exception:
            self.failure.emit("New conversation could not be created")

    @Slot(str)
    def open_conversation(self, conversation_id: str) -> None:
        service = self._service
        if service is None:
            return
        try:
            parsed_id = UUID(conversation_id)
            if self._voice is not None:
                self.stop_voice()
            service.open_conversation(parsed_id)
            page = service.api.list_conversation_turns(parsed_id, limit=50)
            self.conversation_opened.emit(conversation_id, page)
        except Exception:
            self.failure.emit("Conversation could not be opened")

    @Slot(str, str)
    def load_older_turns(self, conversation_id: str, before_sequence: str) -> None:
        service = self._service
        if service is None:
            return
        try:
            page = service.api.list_conversation_turns(
                UUID(conversation_id), limit=50, before_sequence=int(before_sequence)
            )
            self.older_turns_ready.emit(conversation_id, page)
        except Exception:
            self.failure.emit("Older messages could not be loaded")

    # -- Realtime voice (Gate I18, SA-B041) -------------------------------

    @Slot(str, bool)
    def start_voice(self, locality: str, cloud_context_eligible: bool) -> None:
        if self._voice_status in {
            VoiceState.CONNECTING,
            VoiceState.LISTENING,
            VoiceState.RESPONDING,
        }:
            self.failure.emit("Realtime voice is already active")
            return
        service = self._service
        if service is None or service.snapshot is None:
            self.failure.emit("Connect to Core before starting realtime voice")
            return
        try:
            self._ensure_current_conversation()
        except Exception:
            self.failure.emit("Conversation could not be created")
            return
        self._set_voice_state(VoiceState.CONNECTING)
        try:
            if self._voice is None:
                self._voice = service.api.realtime()
                assert service.conversation_id is not None
                self._voice.open(
                    service.conversation_id,
                    locality=locality,
                    cloud_context_eligible=cloud_context_eligible,
                )

            # Start/recover the native interaction before binding the event
            # pump to the session. NativeRealtimeVoiceConnection.start() may
            # replace a transient non-idle session with a fresh session for the
            # same durable Conversation; starting the pump earlier would bind
            # it to the stale session and surface late failures as if they
            # belonged to the new interaction.
            self._voice.start()

            if self._output_device is None:
                self._output_device = self._output_device_factory()
                self._output_device.start()

            if self._pump_thread is None or not self._pump_thread.is_alive():
                voice = self._voice
                self._pump_thread = threading.Thread(
                    target=self._pump_loop,
                    args=(voice,),
                    daemon=True,
                    name="sofia-realtime-pump",
                )
                self._pump_thread.start()

            self._start_input_device()
            self._set_voice_state(VoiceState.LISTENING)
        except AudioDeviceError as error:
            self._set_voice_state(VoiceState.ERROR)
            self.failure.emit(f"Voice unavailable: {error}")
            self._stop_audio_devices()
            self._close_voice()
            self._wait_for_pump()
        except Exception as error:
            traceback.print_exc()
            self._set_voice_state(VoiceState.ERROR)
            detail = str(error).strip()
            self.failure.emit(
                f"Realtime voice could not be started: {detail}"
                if detail
                else "Realtime voice could not be started"
            )
            self._stop_audio_devices()
            self._close_voice()
            self._wait_for_pump()

    def _on_microphone_chunk(self, chunk: bytes) -> None:
        voice = self._voice
        if voice is None:
            return
        try:
            voice.send_audio(chunk)
        except Exception:
            pass  # a real failure surfaces through the pump loop instead

    def _pump_loop(self, voice: RealtimeVoiceConnection) -> None:
        """Sole reader of realtime events on a background thread.

        The pump never mutates ClientWorker/Qt state directly. Every event is
        queued back onto the worker's Qt thread together with the originating
        voice object so late events from a closed session can be ignored.
        """

        try:
            for event in voice.pump_events():
                self.voice_event.emit(voice, event)
        except Exception as error:
            traceback.print_exc()
            self.voice_pump_failed.emit(voice, str(error))

    @Slot(object, object)
    def _dispatch_voice_event(
        self, voice: RealtimeVoiceConnection, event: dict[str, Any]
    ) -> None:
        if voice is not self._voice:
            return
        self._handle_voice_event(event)

    @Slot(object, str)
    def _on_voice_pump_failed(
        self, voice: RealtimeVoiceConnection, detail: str
    ) -> None:
        if voice is not self._voice:
            return
        self.failure.emit(
            f"Realtime connection was lost: {detail}"
            if detail
            else "Realtime connection was lost"
        )
        self._set_voice_state(VoiceState.ERROR)
        self._stop_audio_devices()
        self._close_voice()

    def _handle_voice_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "assistant_audio_chunk":
            self._set_voice_state(VoiceState.RESPONDING)
            audio = event.get("audio")
            if isinstance(audio, bytes) and audio:
                self.voice_audio_chunk.emit(audio)
        elif kind == "user_transcript.final":
            self.voice_transcript.emit(str(event.get("text", "")))
        elif kind == "assistant_transcript.final":
            self.voice_assistant_text.emit(str(event.get("text", "")))
        elif kind == "turn.completed":
            self._set_voice_state(VoiceState.READY)
            self.refresh()
        elif kind in {"turn.failed", "interaction.failed"}:
            self._set_voice_state(VoiceState.ERROR)
            if kind == "interaction.failed":
                detail = str(event.get("message") or "").strip()
            else:
                turn = event.get("turn")
                detail = (
                    str(turn.get("error_message") or "").strip()
                    if isinstance(turn, dict)
                    else ""
                )
            message = (
                f"Realtime interaction did not complete: {detail}"
                if detail
                else "Realtime interaction did not complete"
            )
            print(message, file=sys.stderr)
            self.failure.emit(message)
            self._stop_audio_devices()
            self._close_voice()
            self.refresh()
        elif kind == "turn.interrupted":
            self._set_voice_state(VoiceState.READY)
            self.refresh()
        elif kind in {"session.failed", "error"}:
            self._set_voice_state(VoiceState.ERROR)
            self.failure.emit("Realtime session failed")
            self._stop_audio_devices()
            self._close_voice()
        elif kind == "session.closed":
            self._stop_audio_devices()
            if self._voice is not None:
                self._voice = None
            self._set_voice_state(VoiceState.IDLE)

    @Slot(bytes)
    def _play_voice_audio(self, chunk: bytes) -> None:
        """Write speaker PCM only on ClientWorker's Qt thread.

        QAudioSink/QIODevice have Qt thread affinity. Provider events are
        consumed on the dedicated pump thread, so speaker writes must cross
        back to the worker thread before touching the Qt audio device.
        """

        output_device = self._output_device
        if output_device is None:
            return
        try:
            output_device.write(chunk)
        except AudioDeviceError:
            self.failure.emit("Speaker output failed; voice is degraded")

    @Slot()
    def commit_voice(self) -> None:
        """Explicit push-to-talk "stop speaking" action (Gate I18 baseline).

        No VAD/barge-in is implemented; the user explicitly signals input is
        done, matching Slice 10's "explicit push/stop interaction satisfies
        the Gate" allowance.
        """

        self._stop_input_device()
        if self._voice is None:
            return
        try:
            self._voice.commit()
            self._set_voice_state(VoiceState.RESPONDING)
        except Exception:
            self.failure.emit("Could not stop speaking")

    @Slot()
    def stop_voice(self) -> None:
        """Close only realtime audio; keep the durable Conversation selected."""

        self._stop_audio_devices()
        self._close_voice()
        self._wait_for_pump()
        self._set_voice_state(VoiceState.IDLE)

    @Slot()
    def interrupt_voice(self) -> None:
        if self._voice is None:
            self._set_voice_state(VoiceState.IDLE)
            return
        try:
            self._voice.interrupt()
            self._set_voice_state(VoiceState.INTERRUPTED)
        except Exception:
            self._set_voice_state(VoiceState.ERROR)
            self.failure.emit("Realtime response could not be interrupted")

    @Slot()
    def shutdown(self) -> None:
        """Release Desktop-owned resources and always let the worker thread exit."""

        try:
            self.stop_voice()
            if self._service is not None:
                self._service.api.close()
                self._service = None
        finally:
            self.stopped.emit()

    # -- AI configuration / Memory integration (Gate I17) ----------------
    #
    # These bypass `ClientApplicationService` but resolve through the
    # native SofiaApplication adapter. Realtime voice is native as of SAS-03D;
    # the Desktop no longer depends on localhost HTTP/WebSocket transport.
    # A write never replays automatically on failure (Contract v1 SS21);
    # the caller must re-trigger explicitly.

    def _ai_dashboard_snapshot(self) -> dict[str, Any]:
        service = self._service
        assert service is not None
        return {
            "providers": service.api.list_ai_providers(),
            "models": service.api.list_ai_models(),
            "profiles": service.api.list_ai_profiles(),
            "memory": service.api.get_memory_integration(),
        }

    @Slot()
    def load_ai_dashboard(self) -> None:
        if self._service is None:
            self.failure.emit("Connect to Core before loading AI configuration")
            return
        try:
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except Exception:
            self.failure.emit("AI configuration could not be loaded")

    @Slot(str, object)
    def update_ai_provider(self, provider_id: str, patch: dict[str, Any]) -> None:
        if self._service is None:
            return
        try:
            self._service.api.update_ai_provider(provider_id, patch)
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Provider configuration could not be updated")

    @Slot(str)
    def refresh_ai_models(self, provider_id: str) -> None:
        if self._service is None:
            return
        try:
            self._service.api.refresh_ai_models(provider_id)
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Model discovery refresh failed")

    @Slot(str, object)
    def update_ai_profile(self, key: str, patch: dict[str, Any]) -> None:
        if self._service is None:
            return
        try:
            self._service.api.update_ai_profile(key, patch)
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Profile update failed")

    @Slot(object)
    def preview_ai_routing(self, request: dict[str, Any]) -> None:
        if self._service is None:
            return
        try:
            self.routing_preview_ready.emit(
                self._service.api.preview_ai_routing(request)
            )
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Routing preview failed")

    @Slot(str, str)
    def set_ai_provider_credential(self, provider_id: str, value: str) -> None:
        if self._service is None:
            return
        try:
            self._service.api.set_ai_provider_credential(provider_id, value)
            self.credential_write_succeeded.emit(f"provider:{provider_id}")
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Provider credential could not be saved")

    @Slot(str)
    def delete_ai_provider_credential(self, provider_id: str) -> None:
        if self._service is None:
            return
        try:
            self._service.api.delete_ai_provider_credential(provider_id)
            self.credential_write_succeeded.emit(f"provider:{provider_id}")
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Provider credential could not be removed")

    @Slot(str)
    def set_memory_credential(self, value: str) -> None:
        if self._service is None:
            return
        try:
            self._service.api.set_memory_credential(value)
            self.credential_write_succeeded.emit("memory")
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Memory credential could not be saved")

    @Slot()
    def delete_memory_credential(self) -> None:
        if self._service is None:
            return
        try:
            self._service.api.delete_memory_credential()
            self.credential_write_succeeded.emit("memory")
            self.ai_dashboard_ready.emit(self._ai_dashboard_snapshot())
        except CoreValidationError as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit("Memory credential could not be removed")

    def _publish(self, snapshot: ClientSnapshot) -> None:
        self._state(snapshot.connection)
        self.snapshot_ready.emit(snapshot)

    def _state(self, state: ConnectionState | str) -> None:
        self.state_changed.emit(str(state))

    def _set_voice_state(self, state: VoiceState) -> None:
        self._voice_status = state
        self.voice_changed.emit(state.value)

    def _start_input_device(self) -> None:
        self._stop_input_device()
        self._input_device = self._input_device_factory()
        self._input_device.start(self._on_microphone_chunk)

    def _stop_input_device(self) -> None:
        device = self._input_device
        self._input_device = None
        if device is not None:
            try:
                device.stop()
            except Exception:
                traceback.print_exc()

    def _stop_audio_devices(self) -> None:
        self._stop_input_device()
        device = self._output_device
        self._output_device = None
        if device is not None:
            try:
                device.stop()
            except Exception:
                traceback.print_exc()

    def _wait_for_pump(self) -> None:
        thread = self._pump_thread
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(2.0)
        if thread is not None and not thread.is_alive():
            self._pump_thread = None

    def _close_voice(self) -> None:
        voice = self._voice
        self._voice = None
        if voice is not None:
            try:
                voice.stop()
            except Exception as error:
                traceback.print_exc()
                self.failure.emit(f"Realtime voice could not be closed: {error}")


class DesktopController(QObject):
    request_send = Signal(str, str, bool)
    request_refresh = Signal()
    request_acknowledge = Signal(str)
    request_load_confirmation = Signal(str)
    request_decision = Signal(str, bool)
    request_cancel_task = Signal(str)
    request_voice_start = Signal(str, bool)
    request_voice_commit = Signal()
    request_voice_stop = Signal()
    request_voice_interrupt = Signal()
    request_shutdown = Signal()
    request_ai_dashboard = Signal()
    request_provider_update = Signal(str, object)
    request_model_refresh = Signal(str)
    request_profile_update = Signal(str, object)
    request_routing_preview = Signal(object)
    request_set_provider_credential = Signal(str, str)
    request_delete_provider_credential = Signal(str)
    request_set_memory_credential = Signal(str)
    request_delete_memory_credential = Signal()
    request_load_conversations = Signal()
    request_new_conversation = Signal()
    request_open_conversation = Signal(str)
    request_load_older_turns = Signal(str, str)

    def __init__(
        self,
        base_url: str | None = None,
        credential: str | None = None,
        parent: QObject | None = None,
        *,
        auto_connect: bool = True,
        api_factory: Callable[[], CoreApiClient] | None = None,
        input_device_factory: Any = QtAudioInputDevice,
        output_device_factory: Any = QtAudioOutputDevice,
    ):
        super().__init__(parent)
        self._thread = QThread(self)
        self.worker = ClientWorker(
            base_url,
            credential,
            api_factory=api_factory,
            input_device_factory=input_device_factory,
            output_device_factory=output_device_factory,
        )
        self.worker.moveToThread(self._thread)
        if auto_connect:
            self._thread.started.connect(self.worker.connect_core)
        self.request_send.connect(self.worker.send_text)
        self.request_refresh.connect(self.worker.refresh)
        self.request_acknowledge.connect(self.worker.acknowledge)
        self.request_load_confirmation.connect(self.worker.load_confirmation)
        self.request_decision.connect(self.worker.decide_confirmation)
        self.request_cancel_task.connect(self.worker.cancel_task)
        self.request_voice_start.connect(self.worker.start_voice)
        self.request_voice_commit.connect(self.worker.commit_voice)
        self.request_voice_stop.connect(self.worker.stop_voice)
        self.request_voice_interrupt.connect(self.worker.interrupt_voice)
        self.request_shutdown.connect(self.worker.shutdown)
        self.request_ai_dashboard.connect(self.worker.load_ai_dashboard)
        self.request_provider_update.connect(self.worker.update_ai_provider)
        self.request_model_refresh.connect(self.worker.refresh_ai_models)
        self.request_profile_update.connect(self.worker.update_ai_profile)
        self.request_routing_preview.connect(self.worker.preview_ai_routing)
        self.request_set_provider_credential.connect(
            self.worker.set_ai_provider_credential
        )
        self.request_delete_provider_credential.connect(
            self.worker.delete_ai_provider_credential
        )
        self.request_set_memory_credential.connect(self.worker.set_memory_credential)
        self.request_delete_memory_credential.connect(
            self.worker.delete_memory_credential
        )
        self.request_load_conversations.connect(self.worker.load_conversations)
        self.request_new_conversation.connect(self.worker.start_new_conversation)
        self.request_open_conversation.connect(self.worker.open_conversation)
        self.request_load_older_turns.connect(self.worker.load_older_turns)
        self.worker.stopped.connect(self._thread.quit)
        self._thread_started = auto_connect
        if auto_connect:
            self._thread.start()

    def close(self) -> bool:
        """Stop the worker thread before allowing the Qt application to exit."""

        if not self._thread_started or not self._thread.isRunning():
            return True

        self.request_shutdown.emit()
        # Native service calls are in-process. Allow bounded time for one
        # in-flight operation, voice cleanup, and the worker event loop to stop.
        if self._thread.wait(8_000):
            return True
        return False


class SettingsDialog(QDialog):
    def __init__(
        self,
        notifications_enabled: bool,
        parent: QWidget | None,
        *,
        runtime_label: str = "In-process Python application",
    ):
        super().__init__(parent)
        self.setWindowTitle("Sofia settings")
        self.setModal(True)
        self._runtime = QLineEdit(runtime_label)
        self._runtime.setReadOnly(True)
        self._notifications = QCheckBox("Show native notifications")
        self._notifications.setChecked(notifications_enabled)
        form = QFormLayout(self)
        form.addRow("Runtime", self._runtime)
        form.addRow(self._notifications)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    @property
    def notifications_enabled(self) -> bool:
        return self._notifications.isChecked()


class PrivacyPreferenceDialog(QDialog):
    """First-run/explicit inference privacy choice (Contract v1 SS31-34).

    Maps directly to human wording only; the internal `DataLocality` enum
    names are never shown as primary UI text.
    """

    def __init__(
        self, preference: InferencePrivacyPreference, parent: QWidget | None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sofia privacy")
        self.setModal(True)
        form = QFormLayout(self)
        note = QLabel(
            "Choose how Sofia may process your messages. You can change this "
            "later in Settings."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self._locality = QComboBox()
        for value in _LOCALITY_WIRE_VALUES:
            self._locality.addItem(_LOCALITY_LABELS[value], value)
        self._locality.setCurrentIndex(_LOCALITY_WIRE_VALUES.index(preference.locality))
        form.addRow("Inference location", self._locality)
        self._cloud_context = QCheckBox(
            "Allow this conversation's messages and cognitive context to be sent "
            "to cloud models"
        )
        self._cloud_context.setChecked(preference.cloud_context_eligible)
        form.addRow(self._cloud_context)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    @property
    def preference(self) -> InferencePrivacyPreference:
        return InferencePrivacyPreference(
            locality=str(self._locality.currentData()),
            cloud_context_eligible=self._cloud_context.isChecked(),
        )


class ConfirmationDialog(QDialog):
    """Human-safe confirmation review (Slice 10 SA-B041 Confirmation UX).

    Shows only the bounded, already-safe fields the Core confirmation
    response carries -- never a raw domain object dump.
    """

    def __init__(self, confirmation: dict[str, Any], parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sofia wants to do something")
        self.setModal(True)
        form = QFormLayout(self)
        form.addRow("Capability", QLabel(str(confirmation.get("capability", "—"))))
        form.addRow("Operation", QLabel(str(confirmation.get("operation", "—"))))
        resource = QLabel(str(confirmation.get("resource", "—")))
        resource.setWordWrap(True)
        form.addRow("Target", resource)
        form.addRow(
            "Permission lifetime",
            QLabel(str(confirmation.get("requested_lifetime", "ONE_SHOT"))),
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Approve")
        buttons.button(QDialogButtonBox.StandardButton.No).setText("Deny")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: DesktopController,
        runtime_label: str = "In-process Python application",
    ) -> None:
        super().__init__()
        self._controller = controller
        self._runtime_label = runtime_label
        self._settings = QSettings("Sofia", "SofiaAssistant")
        self._notifications_enabled = bool(
            self._settings.value("notifications/enabled", True, type=bool)
        )
        self._privacy_preference = self._load_privacy_preference()
        self._quitting = False
        self._seen_native: set[UUID] = set()
        self._notification_rows: dict[UUID, QWidget] = {}
        self._task_rows: dict[UUID, QWidget] = {}
        self._last_connection_state: str | None = None
        self._current_conversation_id: str | None = self._settings.value(
            "conversation/current_id", None, type=str
        )
        self._current_conversation_restored = False
        self._pending_confirmation_id: str | None = None
        self._ai_dashboard: dict[str, Any] | None = None
        self._build_ui()
        self._build_tray()
        self._wire_controller()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2500)
        self._refresh_timer.timeout.connect(self._controller.request_refresh.emit)
        self._refresh_timer.start()

    # -- Privacy preference (Contract v1 SS31-34) -------------------------

    def _load_privacy_preference(self) -> InferencePrivacyPreference:
        locality = self._settings.value("privacy/locality", None, type=str)
        if locality not in _LOCALITY_WIRE_VALUES:
            return InferencePrivacyPreference.default()
        cloud_context_eligible = bool(
            self._settings.value("privacy/cloud_context_eligible", False, type=bool)
        )
        return InferencePrivacyPreference(locality, cloud_context_eligible)

    def _save_privacy_preference(self, preference: InferencePrivacyPreference) -> None:
        self._privacy_preference = preference
        self._settings.setValue("privacy/locality", preference.locality)
        self._settings.setValue(
            "privacy/cloud_context_eligible", preference.cloud_context_eligible
        )

    def _has_explicit_privacy_choice(self) -> bool:
        return self._settings.value("privacy/locality", None, type=str) in (
            _LOCALITY_WIRE_VALUES
        )

    def _ensure_privacy_choice(self) -> bool:
        """Block the first real inference until the user resolves a choice.

        Non-inference operations (attach, health, dashboard, routing
        preview, provider/Memory setup) never go through this gate
        (Contract v1 SS33).
        """

        if self._has_explicit_privacy_choice():
            return True
        return self._show_privacy_dialog()

    def _show_privacy_dialog(self) -> bool:
        dialog = PrivacyPreferenceDialog(self._privacy_preference, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_privacy_preference(dialog.preference)
            return True
        return False

    # -- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Sofia's Assistant")
        self.resize(1100, 720)
        self.setMinimumSize(820, 560)
        self.setStatusBar(QStatusBar(self))
        self._connection = QLabel("Connecting…")
        self.statusBar().addPermanentWidget(self._connection)
        menu = self.menuBar().addMenu("Sofia")
        settings = QAction("Settings", self)
        settings.triggered.connect(self._show_settings)
        menu.addAction(settings)
        privacy = QAction("Privacy…", self)
        privacy.triggered.connect(self._show_privacy_dialog)
        menu.addAction(privacy)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._home_tab(), "Home")
        self._tabs.addTab(self._chat_tab(), "Chat")
        self._tabs.addTab(self._ai_models_tab(), "AI & Models")
        self._tabs.addTab(self._memory_tab(), "Memory / Integrations")
        self._tabs.addTab(self._tasks_tab(), "Tasks")
        self._tabs.addTab(self._notifications_tab(), "Notifications")
        self._tabs.addTab(self._health_tab(), "Health")
        self.setCentralWidget(self._tabs)

    def _home_tab(self) -> QWidget:
        self._home = HomeTab()
        self._home.configure_ai_requested.connect(self._open_ai_models_tab)
        return self._home

    def _open_ai_models_tab(self) -> None:
        self._tabs.setCurrentWidget(self._ai_models)

    def _ai_models_tab(self) -> QWidget:
        self._ai_models = AIModelsTab()
        self._ai_models.provider_update_requested.connect(
            self._controller.request_provider_update.emit
        )
        self._ai_models.provider_credential_set_requested.connect(
            self._controller.request_set_provider_credential.emit
        )
        self._ai_models.provider_credential_deleted_requested.connect(
            self._controller.request_delete_provider_credential.emit
        )
        self._ai_models.model_refresh_requested.connect(
            self._controller.request_model_refresh.emit
        )
        self._ai_models.profile_update_requested.connect(
            self._controller.request_profile_update.emit
        )
        self._ai_models.routing_preview_requested.connect(
            self._controller.request_routing_preview.emit
        )
        self._ai_models.set_writes_enabled(False)
        return self._ai_models

    def _memory_tab(self) -> QWidget:
        self._memory = MemoryIntegrationsTab()
        self._memory.credential_set_requested.connect(
            self._controller.request_set_memory_credential.emit
        )
        self._memory.credential_deleted_requested.connect(
            self._controller.request_delete_memory_credential.emit
        )
        self._memory.set_writes_enabled(False)
        return self._memory

    def _chat_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        new_conversation = QPushButton("New conversation")
        new_conversation.clicked.connect(self._controller.request_new_conversation.emit)
        sidebar_layout.addWidget(new_conversation)
        self._conversation_list = QListWidget()
        self._conversation_list.setAccessibleName("Conversation history")
        self._conversation_list.currentItemChanged.connect(
            self._on_conversation_selected
        )
        sidebar_layout.addWidget(self._conversation_list, 1)
        splitter.addWidget(sidebar)

        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        older = QPushButton("Load older messages")
        older.clicked.connect(self._load_older_turns)
        chat_layout.addWidget(older)
        self._chat = QTextBrowser()
        self._chat.setOpenExternalLinks(False)
        self._chat.setPlaceholderText("Conversation output appears here")
        self._chat.setAccessibleName("Conversation transcript")
        chat_layout.addWidget(self._chat, 1)
        row = QHBoxLayout()
        self._draft = QLineEdit()
        self._draft.setPlaceholderText("Message Sofia…")
        self._draft.returnPressed.connect(self._send_draft)
        send = QPushButton("Send")
        send.clicked.connect(self._send_draft)
        row.addWidget(self._draft, 1)
        row.addWidget(send)
        chat_layout.addLayout(row)

        voice_row = QHBoxLayout()
        self._voice_label = QLabel("Voice: IDLE")
        self._voice_label.setAccessibleName("Voice state")
        self._voice_start_button = QPushButton("Start voice")
        self._voice_commit_button = QPushButton("Stop speaking")
        self._voice_interrupt_button = QPushButton("Interrupt")
        self._voice_stop_button = QPushButton("Stop voice")
        self._voice_start_button.clicked.connect(self._start_voice)
        self._voice_commit_button.clicked.connect(
            self._controller.request_voice_commit.emit
        )
        self._voice_interrupt_button.clicked.connect(
            self._controller.request_voice_interrupt.emit
        )
        self._voice_stop_button.clicked.connect(
            self._controller.request_voice_stop.emit
        )
        voice_row.addWidget(self._voice_label)
        voice_row.addStretch(1)
        voice_row.addWidget(self._voice_start_button)
        voice_row.addWidget(self._voice_commit_button)
        voice_row.addWidget(self._voice_interrupt_button)
        voice_row.addWidget(self._voice_stop_button)
        chat_layout.addLayout(voice_row)
        self._update_voice_controls(VoiceState.IDLE.value)

        splitter.addWidget(chat_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        self._oldest_loaded_sequence: int | None = None
        return tab

    def _tasks_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._tasks = QListWidget()
        layout.addWidget(self._tasks)
        return tab

    def _notifications_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._notifications = QListWidget()
        layout.addWidget(self._notifications)
        return tab

    def _health_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._health = QListWidget()
        layout.addWidget(self._health)
        return tab

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(_tray_icon(), self)
        self._tray.setToolTip("Sofia's Assistant")
        menu = QMenu()
        open_action = QAction("Open Sofia", self)
        open_action.triggered.connect(self._show_window)
        chat_action = QAction("Open chat", self)
        chat_action.triggered.connect(self._show_window)
        self._tray_status = QAction("Connecting…", self)
        self._tray_status.setEnabled(False)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(open_action)
        menu.addAction(chat_action)
        menu.addSeparator()
        menu.addAction(self._tray_status)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: (
                self._show_window()
                if reason
                in (
                    QSystemTrayIcon.ActivationReason.Trigger,
                    QSystemTrayIcon.ActivationReason.DoubleClick,
                )
                else None
            )
        )
        self._tray.show()

    def _wire_controller(self) -> None:
        worker = self._controller.worker
        worker.state_changed.connect(self._on_state)
        worker.snapshot_ready.connect(self._on_snapshot)
        worker.stream_started.connect(lambda: self._chat.append("<b>Sofia:</b> "))
        worker.stream_delta.connect(self._chat.insertPlainText)
        worker.stream_finished.connect(lambda: self._chat.append(""))
        worker.conversation_failed.connect(self._on_conversation_failed)
        worker.voice_changed.connect(self._on_voice_state)
        worker.voice_transcript.connect(
            lambda text: self._chat.append(f"<b>You:</b> {text}")
        )
        worker.voice_assistant_text.connect(
            lambda text: self._chat.append(f"<b>Sofia:</b> {text}")
        )
        worker.failure.connect(self._show_error)
        worker.ai_dashboard_ready.connect(self._on_ai_dashboard)
        worker.routing_preview_ready.connect(self._ai_models.show_routing_preview)
        worker.credential_write_succeeded.connect(self._on_credential_write_succeeded)
        worker.conversations_ready.connect(self._on_conversations_ready)
        worker.conversation_opened.connect(self._on_conversation_opened)
        worker.older_turns_ready.connect(self._on_older_turns_ready)
        worker.conversation_recovered.connect(self._on_conversation_recovered)
        worker.confirmation_ready.connect(self._on_confirmation_ready)

    @Slot(str)
    def _on_voice_state(self, state: str) -> None:
        value = state.rsplit(".", 1)[-1]
        self._voice_label.setText(f"Voice: {value}")
        self._update_voice_controls(value)

    def _update_voice_controls(self, state: str) -> None:
        value = state.rsplit(".", 1)[-1]
        active = value in {
            VoiceState.CONNECTING.value,
            VoiceState.LISTENING.value,
            VoiceState.RESPONDING.value,
            VoiceState.READY.value,
            VoiceState.INTERRUPTED.value,
        }
        self._voice_start_button.setEnabled(
            value in {
                VoiceState.IDLE.value,
                VoiceState.READY.value,
                VoiceState.ERROR.value,
            }
        )
        self._voice_commit_button.setEnabled(value == VoiceState.LISTENING.value)
        self._voice_interrupt_button.setEnabled(
            value == VoiceState.RESPONDING.value
        )
        self._voice_stop_button.setEnabled(active or value == VoiceState.ERROR.value)

    @Slot(str)
    def _on_state(self, state: str) -> None:
        value = state.rsplit(".", 1)[-1]
        self._connection.setText(value)
        self._tray_status.setText(value)
        self._home.update_connection(value)
        writes_enabled = value == "CONNECTED"
        self._ai_models.set_writes_enabled(writes_enabled)
        self._memory.set_writes_enabled(writes_enabled)
        if writes_enabled and value != self._last_connection_state:
            self._controller.request_ai_dashboard.emit()
            self._controller.request_load_conversations.emit()
        self._last_connection_state = value

    @Slot(object)
    def _on_ai_dashboard(self, bundle: dict[str, object]) -> None:
        self._ai_dashboard = bundle
        self._home.update_ai_dashboard(bundle)
        self._ai_models.update_ai_dashboard(bundle)
        self._memory.update_ai_dashboard(bundle)

    @Slot(str)
    def _on_credential_write_succeeded(self, _: str) -> None:
        self.statusBar().showMessage("Credential saved", 4000)

    @Slot(object)
    def _on_snapshot(self, snapshot: ClientSnapshot) -> None:
        self._home.update_health(snapshot.health)
        self._render_health(snapshot.health)
        self._render_tasks(snapshot.tasks)
        self._render_notifications(snapshot.notifications)

    # -- Conversation History (Gate I18, SA-B040) -------------------------

    @Slot(object)
    def _on_conversations_ready(self, page: dict[str, Any]) -> None:
        self._conversation_list.blockSignals(True)
        self._conversation_list.clear()
        restored_row: QListWidgetItem | None = None
        for item in page.get("items", []):
            row = QListWidgetItem(str(item.get("preview") or "New conversation"))
            conversation_id = str(item.get("conversation_id"))
            row.setData(Qt.ItemDataRole.UserRole, conversation_id)
            self._conversation_list.addItem(row)
            if conversation_id == self._current_conversation_id:
                restored_row = row
                self._conversation_list.setCurrentItem(row)
        self._conversation_list.blockSignals(False)
        if (
            restored_row is not None
            and not self._current_conversation_restored
            and self._current_conversation_id is not None
        ):
            self._current_conversation_restored = True
            self._controller.request_open_conversation.emit(
                self._current_conversation_id
            )

    def _on_conversation_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            return
        conversation_id = str(current.data(Qt.ItemDataRole.UserRole))
        if conversation_id == self._current_conversation_id:
            return
        self._controller.request_open_conversation.emit(conversation_id)

    @Slot(str, object)
    def _on_conversation_opened(
        self, conversation_id: str, page: dict[str, Any]
    ) -> None:
        self._current_conversation_id = conversation_id
        self._current_conversation_restored = True
        self._settings.setValue("conversation/current_id", conversation_id)
        self._render_turn_page(page, replace=True)

    @Slot(str, object)
    def _on_older_turns_ready(self, conversation_id: str, page: dict[str, Any]) -> None:
        if conversation_id != self._current_conversation_id:
            return
        self._render_turn_page(page, replace=False, prepend=True)

    def _render_turn_page(
        self, page: dict[str, Any], *, replace: bool, prepend: bool = False
    ) -> None:
        turns = page.get("turns", [])
        if replace:
            self._chat.clear()
        html_lines = []
        for turn in turns:
            html_lines.append(f"<b>You:</b> {turn.get('user_text', '')}")
            assistant_text = turn.get("assistant_text")
            if assistant_text:
                html_lines.append(f"<b>Sofia:</b> {assistant_text}")
            elif turn.get("status") == "FAILED":
                html_lines.append(
                    f"<i>Sofia could not complete this turn: "
                    f"{turn.get('error_message', 'unknown error')}</i>"
                )
        rendered = "<br>".join(html_lines)
        if prepend:
            existing = self._chat.toHtml()
            self._chat.setHtml(rendered + "<br>" + existing)
        else:
            for line in html_lines:
                self._chat.append(line)
        if turns:
            self._oldest_loaded_sequence = int(turns[0].get("sequence", 0)) or None
        self._has_older_turns = bool(page.get("has_older", False))

    def _load_older_turns(self) -> None:
        if (
            self._current_conversation_id is None
            or self._oldest_loaded_sequence is None
            or not getattr(self, "_has_older_turns", False)
        ):
            return
        self._controller.request_load_older_turns.emit(
            self._current_conversation_id, str(self._oldest_loaded_sequence)
        )

    @Slot(str, str)
    def _on_conversation_failed(self, error_code: str, error_message: str) -> None:
        code = html.escape(error_code)
        message = html.escape(error_message)
        self._chat.append(
            f"<i>Sofia could not complete this turn [{code}]: {message}</i>"
        )
        self.statusBar().showMessage(f"{error_code}: {error_message}", 8000)

    @Slot(object)
    def _on_conversation_recovered(self, page: dict[str, Any]) -> None:
        turns = page.get("turns", [])
        if not turns:
            self._chat.append(
                "<i>The last message's result is unconfirmed. "
                "Please retry if needed.</i>"
            )
            return
        turn = turns[-1]
        if turn.get("status") == "COMPLETED" and turn.get("assistant_text"):
            self._chat.append(f"<b>Sofia:</b> {turn['assistant_text']}")
        else:
            self._chat.append(
                "<i>The last message's result is unconfirmed. "
                "Please retry if needed.</i>"
            )

    # -- Confirmation UX ----------------------------------------------------

    @Slot(object)
    def _on_confirmation_ready(self, confirmation: dict[str, Any]) -> None:
        dialog = ConfirmationDialog(confirmation, self)
        confirmation_id = self._pending_confirmation_id
        self._pending_confirmation_id = None
        result = dialog.exec()
        if confirmation_id is None:
            return
        if result == QDialog.DialogCode.Accepted:
            self._controller.request_decision.emit(confirmation_id, True)
        else:
            self._controller.request_decision.emit(confirmation_id, False)

    def _render_health(self, health: tuple[HealthItem, ...]) -> None:
        self._health.clear()
        for item in health:
            detail = f" — {item.detail}" if item.detail else ""
            QListWidgetItem(f"{item.name}: {item.status}{detail}", self._health)

    def _render_tasks(self, tasks: tuple[TaskItem, ...]) -> None:
        self._tasks.clear()
        for task in tasks:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 2, 4, 2)
            label = QLabel(f"{task.status} — {task.objective}")
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            if task.status in _ACTIVE_TASK_STATUSES:
                cancel = QPushButton("Cancel")
                cancel.clicked.connect(
                    lambda _checked=False, task_id=task.id: (
                        self._controller.request_cancel_task.emit(str(task_id))
                    )
                )
                layout.addWidget(cancel)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self._tasks.addItem(item)
            self._tasks.setItemWidget(item, row)

    def _render_notifications(
        self, notifications: tuple[NotificationItem, ...]
    ) -> None:
        self._notifications.clear()
        for notification in notifications:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 2, 4, 2)
            label = QLabel(f"{notification.title}: {notification.summary}")
            label.setWordWrap(True)
            layout.addWidget(label, 1)
            if (
                notification.action_reference is not None
                and notification.type == "PermissionRequested"
            ):
                review = QPushButton("Review")
                review.clicked.connect(
                    lambda _checked=False, ref=notification.action_reference: (
                        self._review_confirmation(ref)
                    )
                )
                layout.addWidget(review)
            acknowledge = QPushButton("Acknowledge")
            acknowledge.clicked.connect(
                lambda _checked=False, item_id=notification.id: (
                    self._controller.request_acknowledge.emit(str(item_id))
                )
            )
            layout.addWidget(acknowledge)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self._notifications.addItem(item)
            self._notifications.setItemWidget(item, row)
            if notification.id not in self._seen_native:
                self._seen_native.add(notification.id)
                if self._notifications_enabled:
                    self._tray.showMessage(
                        notification.title,
                        notification.summary,
                        QSystemTrayIcon.MessageIcon.Information,
                        5000,
                    )

    def _review_confirmation(self, confirmation_id: UUID) -> None:
        self._pending_confirmation_id = str(confirmation_id)
        self._controller.request_load_confirmation.emit(str(confirmation_id))

    def _send_draft(self) -> None:
        text = self._draft.text().strip()
        if not text:
            return
        if not self._ensure_privacy_choice():
            return
        self._chat.append(f"<b>You:</b> {text}")
        self._draft.clear()
        preference = self._privacy_preference
        self._controller.request_send.emit(
            text, preference.locality, preference.cloud_context_eligible
        )

    def _start_voice(self) -> None:
        if not self._ensure_privacy_choice():
            return
        preference = self._privacy_preference
        self._controller.request_voice_start.emit(
            preference.locality, preference.cloud_context_eligible
        )

    def _show_settings(self) -> None:
        dialog = SettingsDialog(
            self._notifications_enabled,
            self,
            runtime_label=self._runtime_label,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._notifications_enabled = dialog.notifications_enabled
            self._settings.setValue(
                "notifications/enabled", self._notifications_enabled
            )

    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._refresh_timer.stop()
        if not self._controller.close():
            self._refresh_timer.start()
            self._show_error("Sofia is still finishing background work; try Quit again.")
            return

        self._quitting = True
        self._tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: object) -> None:
        if not self._quitting:
            self._quit()
            if not self._quitting:
                if hasattr(event, "ignore"):
                    event.ignore()
                return
        if hasattr(event, "accept"):
            event.accept()
        else:
            super().closeEvent(event)  # type: ignore[arg-type]


def create_application(
    base_url: str | None = None,
    credential: str | None = None,
    *,
    auto_connect: bool = True,
    api_factory: Callable[[], CoreApiClient] | None = None,
) -> tuple[QApplication, MainWindow]:
    current = QApplication.instance()
    app = current if isinstance(current, QApplication) else QApplication([])
    app.setApplicationName("Sofia's Assistant")
    app.setOrganizationName("Sofia")
    app.setQuitOnLastWindowClosed(False)
    controller = DesktopController(
        base_url,
        credential,
        auto_connect=auto_connect,
        api_factory=api_factory,
    )
    runtime_label = (
        "In-process Python application"
        if api_factory is not None and base_url is None
        else (base_url or "In-process Python application")
    )
    window = MainWindow(controller, runtime_label)
    app.aboutToQuit.connect(controller.close)
    window.show()
    return app, window


def _tray_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#8b5cf6"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setBrush(QColor("#f8fafc"))
    painter.drawEllipse(9, 10, 4, 4)
    painter.drawEllipse(19, 10, 4, 4)
    painter.end()
    return QIcon(pixmap)
