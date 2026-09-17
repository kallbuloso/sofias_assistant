"""PySide6 Desktop Client: widgets, tray and worker-backed application flows."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
from sofias_assistant.client_app.dashboard import (
    AIModelsTab,
    HomeTab,
    MemoryIntegrationsTab,
)
from sofias_assistant.client_app.models import (
    ClientSnapshot,
    ConnectionState,
    HealthItem,
    NotificationItem,
    TaskItem,
    VoiceState,
)
from sofias_assistant.client_app.service import ClientApplicationService


class ClientWorker(QObject):
    state_changed = Signal(str)
    snapshot_ready = Signal(object)
    stream_started = Signal()
    stream_delta = Signal(str)
    stream_finished = Signal()
    voice_changed = Signal(str)
    failure = Signal(str)
    stopped = Signal()
    ai_dashboard_ready = Signal(object)
    routing_preview_ready = Signal(object)
    credential_write_succeeded = Signal(str)

    def __init__(
        self,
        base_url: str,
        credential: str,
        runtime_session_id: UUID | None = None,
    ) -> None:
        super().__init__()
        self._base_url = base_url
        self._credential = credential
        self._runtime_session_id = runtime_session_id
        self._service: ClientApplicationService | None = None
        self._voice: RealtimeVoiceConnection | None = None
        self._voice_status = VoiceState.IDLE

    @Slot()
    def connect_core(self) -> None:
        self._state(ConnectionState.CONNECTING)
        try:
            self._service = ClientApplicationService(
                CoreApiClient(self._base_url, self._credential)
            )
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

    @Slot(str)
    def send_text(self, text: str) -> None:
        service = self._service
        if service is None or service.connection is ConnectionState.DISCONNECTED:
            self.failure.emit("Connect to Core before sending a message")
            return
        self.stream_started.emit()
        try:
            for event in service.stream_text(text):
                kind = event.get("type")
                if kind == "text_delta":
                    self.stream_delta.emit(str(event.get("text", "")))
                elif kind in {"turn_failed", "turn_interrupted"}:
                    self.failure.emit("Conversation turn did not complete")
            self.stream_finished.emit()
            self.refresh()
        except Exception:
            self.failure.emit("Conversation request failed")
            self.stream_finished.emit()

    @Slot(str)
    def acknowledge(self, notification_id: str) -> None:
        if self._service is None:
            return
        try:
            self._service.acknowledge(UUID(notification_id))
            self.refresh()
        except Exception:
            self.failure.emit("Notification could not be acknowledged")

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
            self._service.cancel_task(UUID(task_id))
            self.refresh()
        except Exception:
            self.failure.emit("Task could not be cancelled")

    @Slot()
    def start_voice(self) -> None:
        service = self._service
        if service is None or service.snapshot is None:
            self.failure.emit("Connect to Core before starting realtime voice")
            return
        if service.conversation_id is None:
            self.failure.emit("Conversation is not available")
            return
        self._set_voice_state(VoiceState.CONNECTING)
        try:
            self._voice = service.api.realtime()
            self._voice.open(service.conversation_id)
            self._voice.start()
            self._set_voice_state(VoiceState.LISTENING)
        except Exception:
            self._set_voice_state(VoiceState.ERROR)
            self.failure.emit("Realtime voice could not be started")
            self._close_voice()

    @Slot()
    def stop_voice(self) -> None:
        if self._voice is not None:
            try:
                self._voice.stop()
            except Exception:
                pass
        self._close_voice()
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
        self.stop_voice()
        if self._service is not None:
            self._service.api.close()
        self.stopped.emit()

    @Slot()
    def stop_sofia(self) -> None:
        """Request an explicit authenticated graceful Core shutdown.

        This is the only path that may stop Core; ordinary window close and
        Quit Desktop never call it (Desktop/Core Interaction Contract v1
        SS24). It requires an active session and a known `runtime_session_id`
        obtained during attach.
        """

        service = self._service
        if service is None or self._runtime_session_id is None:
            self.failure.emit("Sofia is not attached to a running Core")
            return
        try:
            accepted = service.api.request_runtime_shutdown(
                self._runtime_session_id, reason="user_requested"
            )
        except Exception:
            self.failure.emit("Stop Sofia request failed")
            return
        if not accepted:
            self.failure.emit("Stop Sofia was rejected (Core lifecycle changed)")
            return
        self._state(ConnectionState.DISCONNECTED)

    # -- AI configuration / Memory integration (Gate I17) ----------------
    #
    # These bypass `ClientApplicationService` and call `CoreApiClient`
    # directly, matching the existing `start_voice`/`service.api.realtime()`
    # precedent: the service layer only wraps Conversation/Task/Notification
    # orchestration, while transport-shaped reads/writes go straight through
    # the authenticated `CoreApiClient`. A write never replays automatically
    # on failure (Contract v1 SS21); the caller must re-trigger explicitly.

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

    def _close_voice(self) -> None:
        self._voice = None


class DesktopController(QObject):
    request_send = Signal(str)
    request_refresh = Signal()
    request_acknowledge = Signal(str)
    request_decision = Signal(str, bool)
    request_cancel_task = Signal(str)
    request_voice_start = Signal()
    request_voice_stop = Signal()
    request_voice_interrupt = Signal()
    request_shutdown = Signal()
    request_stop_sofia = Signal()
    request_ai_dashboard = Signal()
    request_provider_update = Signal(str, object)
    request_model_refresh = Signal(str)
    request_profile_update = Signal(str, object)
    request_routing_preview = Signal(object)
    request_set_provider_credential = Signal(str, str)
    request_delete_provider_credential = Signal(str)
    request_set_memory_credential = Signal(str)
    request_delete_memory_credential = Signal()

    def __init__(
        self,
        base_url: str,
        credential: str,
        parent: QObject | None = None,
        *,
        auto_connect: bool = True,
        runtime_session_id: UUID | None = None,
    ):
        super().__init__(parent)
        self._thread = QThread(self)
        self.worker = ClientWorker(base_url, credential, runtime_session_id)
        self.worker.moveToThread(self._thread)
        if auto_connect:
            self._thread.started.connect(self.worker.connect_core)
        self.request_send.connect(self.worker.send_text)
        self.request_refresh.connect(self.worker.refresh)
        self.request_acknowledge.connect(self.worker.acknowledge)
        self.request_decision.connect(self.worker.decide_confirmation)
        self.request_cancel_task.connect(self.worker.cancel_task)
        self.request_voice_start.connect(self.worker.start_voice)
        self.request_voice_stop.connect(self.worker.stop_voice)
        self.request_voice_interrupt.connect(self.worker.interrupt_voice)
        self.request_shutdown.connect(self.worker.shutdown)
        self.request_stop_sofia.connect(self.worker.stop_sofia)
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
        self.worker.stopped.connect(self._thread.quit)
        self._thread_started = auto_connect
        if auto_connect:
            self._thread.start()

    def close(self) -> None:
        if self._thread_started and self._thread.isRunning():
            self.request_shutdown.emit()
            self._thread.wait(3000)


class SettingsDialog(QDialog):
    def __init__(
        self, base_url: str, notifications_enabled: bool, parent: QWidget | None
    ):
        super().__init__(parent)
        self.setWindowTitle("Sofia settings")
        self.setModal(True)
        self._url = QLineEdit(base_url)
        self._url.setReadOnly(True)
        self._notifications = QCheckBox("Show native notifications")
        self._notifications.setChecked(notifications_enabled)
        form = QFormLayout(self)
        form.addRow("Core URL", self._url)
        form.addRow(self._notifications)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        form.addRow(buttons)

    @property
    def notifications_enabled(self) -> bool:
        return self._notifications.isChecked()


class MainWindow(QMainWindow):
    def __init__(self, controller: DesktopController, base_url: str) -> None:
        super().__init__()
        self._controller = controller
        self._base_url = base_url
        self._settings = QSettings("Sofia", "SofiaAssistant")
        self._notifications_enabled = bool(
            self._settings.value("notifications/enabled", True, type=bool)
        )
        self._quitting = False
        self._seen_native: set[UUID] = set()
        self._notification_rows: dict[UUID, QWidget] = {}
        self._task_rows: dict[UUID, QWidget] = {}
        self._last_connection_state: str | None = None
        self._build_ui()
        self._build_tray()
        self._wire_controller()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2500)
        self._refresh_timer.timeout.connect(self._controller.request_refresh.emit)
        self._refresh_timer.start()

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
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        tabs = QTabWidget(self)
        tabs.addTab(self._home_tab(), "Home")
        tabs.addTab(self._chat_tab(), "Chat")
        tabs.addTab(self._ai_models_tab(), "AI & Models")
        tabs.addTab(self._memory_tab(), "Memory / Integrations")
        tabs.addTab(self._tasks_tab(), "Tasks")
        tabs.addTab(self._notifications_tab(), "Notifications")
        tabs.addTab(self._voice_tab(), "Voice")
        tabs.addTab(self._health_tab(), "Health")
        self.setCentralWidget(tabs)

    def _home_tab(self) -> QWidget:
        self._home = HomeTab()
        return self._home

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
        layout = QVBoxLayout(tab)
        self._chat = QTextBrowser()
        self._chat.setOpenExternalLinks(False)
        self._chat.setPlaceholderText("Conversation output appears here")
        self._chat.setAccessibleName("Conversation transcript")
        layout.addWidget(self._chat, 1)
        row = QHBoxLayout()
        self._draft = QLineEdit()
        self._draft.setPlaceholderText("Message Sofia…")
        self._draft.returnPressed.connect(self._send_draft)
        send = QPushButton("Send")
        send.clicked.connect(self._send_draft)
        row.addWidget(self._draft, 1)
        row.addWidget(send)
        layout.addLayout(row)
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

    def _voice_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        box = QGroupBox("Realtime voice")
        box_layout = QVBoxLayout(box)
        self._voice_label = QLabel("IDLE")
        self._voice_label.setAccessibleName("Voice state")
        box_layout.addWidget(self._voice_label)
        controls = QHBoxLayout()
        start = QPushButton("Start")
        stop = QPushButton("Stop")
        interrupt = QPushButton("Interrupt")
        start.clicked.connect(self._controller.request_voice_start.emit)
        stop.clicked.connect(self._controller.request_voice_stop.emit)
        interrupt.clicked.connect(self._controller.request_voice_interrupt.emit)
        controls.addWidget(start)
        controls.addWidget(stop)
        controls.addWidget(interrupt)
        box_layout.addLayout(controls)
        layout.addWidget(box)
        note = QLabel(
            "Microphone/provider audio is controlled by Core's realtime boundary."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
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
        stop_sofia_action = QAction("Stop Sofia", self)
        stop_sofia_action.triggered.connect(self._confirm_stop_sofia)
        menu.addAction(open_action)
        menu.addAction(chat_action)
        menu.addSeparator()
        menu.addAction(self._tray_status)
        menu.addSeparator()
        menu.addAction(stop_sofia_action)
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
        worker.voice_changed.connect(self._voice_label.setText)
        worker.failure.connect(self._show_error)
        worker.ai_dashboard_ready.connect(self._on_ai_dashboard)
        worker.routing_preview_ready.connect(self._ai_models.show_routing_preview)
        worker.credential_write_succeeded.connect(self._on_credential_write_succeeded)

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
        self._last_connection_state = value

    @Slot(object)
    def _on_ai_dashboard(self, bundle: dict[str, object]) -> None:
        self._home.update_ai_dashboard(bundle)
        self._ai_models.update_ai_dashboard(bundle)
        self._memory.update_ai_dashboard(bundle)

    @Slot(str)
    def _on_credential_write_succeeded(self, _: str) -> None:
        self.statusBar().showMessage("Credential saved", 4000)

    @Slot(object)
    def _on_snapshot(self, snapshot: ClientSnapshot) -> None:
        self._render_health(snapshot.health)
        self._render_tasks(snapshot.tasks)
        self._render_notifications(snapshot.notifications)

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
            if task.status in {
                "QUEUED",
                "RUNNING",
                "WAITING_SCHEDULE",
                "WAITING_CONFIRMATION",
            }:
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
                approve = QPushButton("Approve")
                deny = QPushButton("Deny")
                approve.clicked.connect(
                    lambda _checked=False, ref=notification.action_reference: (
                        self._controller.request_decision.emit(str(ref), True)
                    )
                )
                deny.clicked.connect(
                    lambda _checked=False, ref=notification.action_reference: (
                        self._controller.request_decision.emit(str(ref), False)
                    )
                )
                layout.addWidget(approve)
                layout.addWidget(deny)
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

    def _send_draft(self) -> None:
        text = self._draft.text().strip()
        if not text:
            return
        self._chat.append(f"<b>You:</b> {text}")
        self._draft.clear()
        self._controller.request_send.emit(text)

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self._base_url, self._notifications_enabled, self)
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

    def _confirm_stop_sofia(self) -> None:
        """Require explicit human confirmation before requesting Core shutdown.

        Ordinary window close and Quit Desktop never reach this path
        (Desktop/Core Interaction Contract v1 SS24); only this explicit,
        separate action does.
        """

        answer = QMessageBox.question(
            self,
            "Stop Sofia",
            "This stops Sofia's Core: background reminders, tasks and "
            "notifications will stop until Sofia is started again. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.request_stop_sofia.emit()

    def _quit(self) -> None:
        self._quitting = True
        self._refresh_timer.stop()
        self._controller.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: object) -> None:
        if not self._quitting and self._tray.isVisible():
            self.hide()
            if hasattr(event, "ignore"):
                event.ignore()
            return
        super().closeEvent(event)  # type: ignore[arg-type]


def create_application(
    base_url: str,
    credential: str,
    *,
    auto_connect: bool = True,
    runtime_session_id: UUID | None = None,
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
        runtime_session_id=runtime_session_id,
    )
    window = MainWindow(controller, base_url)
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
