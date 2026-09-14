"""PySide6 Desktop Client: widgets, tray and worker-backed application flows."""

from __future__ import annotations

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
    RealtimeVoiceConnection,
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

    def __init__(self, base_url: str, credential: str) -> None:
        super().__init__()
        self._base_url = base_url
        self._credential = credential
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

    def __init__(
        self,
        base_url: str,
        credential: str,
        parent: QObject | None = None,
        *,
        auto_connect: bool = True,
    ):
        super().__init__(parent)
        self._thread = QThread(self)
        self.worker = ClientWorker(base_url, credential)
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
        tabs.addTab(self._chat_tab(), "Chat")
        tabs.addTab(self._tasks_tab(), "Tasks")
        tabs.addTab(self._notifications_tab(), "Notifications")
        tabs.addTab(self._voice_tab(), "Voice")
        tabs.addTab(self._health_tab(), "Health")
        self.setCentralWidget(tabs)

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
        worker.voice_changed.connect(self._voice_label.setText)
        worker.failure.connect(self._show_error)

    @Slot(str)
    def _on_state(self, state: str) -> None:
        value = state.rsplit(".", 1)[-1]
        self._connection.setText(value)
        self._tray_status.setText(value)

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
    base_url: str, credential: str, *, auto_connect: bool = True
) -> tuple[QApplication, MainWindow]:
    current = QApplication.instance()
    app = current if isinstance(current, QApplication) else QApplication([])
    app.setApplicationName("Sofia's Assistant")
    app.setOrganizationName("Sofia")
    app.setQuitOnLastWindowClosed(False)
    controller = DesktopController(base_url, credential, auto_connect=auto_connect)
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
