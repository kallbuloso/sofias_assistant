"""Premium conversation composer for Sofia Desktop."""

from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from sofias_assistant.client_app.models import VoiceState
from sofias_assistant.client_app.widgets.style import (
    PALETTE,
    desktop_icon,
    RADIUS_LG,
    SPACE_SM,
)


class ComposerWidget(QFrame):
    """Unified text + voice composer with contextual voice controls."""

    send_requested = Signal(str)
    voice_start_requested = Signal()
    voice_commit_requested = Signal()
    voice_interrupt_requested = Signal()
    voice_stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("composerWidget")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(SPACE_SM)

        self.input = QLineEdit()
        self.input.setObjectName("composerInput")
        self.input.setPlaceholderText("Mensagem para Sofia…")
        self.input.returnPressed.connect(self._emit_send)
        layout.addWidget(self.input, 1)

        self.voice_start = QPushButton()
        self.voice_start.setIcon(desktop_icon("mic", 24))
        self.voice_start.setIconSize(QSize(24, 24))
        self.voice_start.setObjectName("composerMic")
        self.voice_start.setToolTip("Falar com Sofia")
        self.voice_start.setFixedSize(44, 44)
        self.voice_start.clicked.connect(self.voice_start_requested.emit)
        layout.addWidget(self.voice_start)

        self.voice_commit = QPushButton("Concluir")
        self.voice_commit.setObjectName("composerContext")
        self.voice_commit.clicked.connect(self.voice_commit_requested.emit)
        layout.addWidget(self.voice_commit)

        self.voice_interrupt = QPushButton("Interromper")
        self.voice_interrupt.setObjectName("composerContext")
        self.voice_interrupt.clicked.connect(self.voice_interrupt_requested.emit)
        layout.addWidget(self.voice_interrupt)

        self.voice_stop = QPushButton("Encerrar voz")
        self.voice_stop.setObjectName("composerSecondary")
        self.voice_stop.clicked.connect(self.voice_stop_requested.emit)
        layout.addWidget(self.voice_stop)

        self.send = QPushButton()
        self.send.setIcon(desktop_icon("send", 24, "#031117"))
        self.send.setIconSize(QSize(24, 24))
        self.send.setObjectName("composerSend")
        self.send.setToolTip("Enviar mensagem")
        self.send.setFixedSize(52, 44)
        self.send.clicked.connect(self._emit_send)
        layout.addWidget(self.send)

        self.set_voice_state(VoiceState.IDLE.value)

        self.setStyleSheet(
            f"""
            QFrame#composerWidget {{
                background: #091c25;
                border: 1px solid {PALETTE.border_strong};
                border-radius: {RADIUS_LG}px;
            }}
            QLineEdit#composerInput {{
                min-height: 42px;
                padding: 0 10px;
                border: 0;
                background: transparent;
                color: {PALETTE.text_primary};
                font-size: 14px;
            }}
            QLineEdit#composerInput:focus {{
                border: 0;
            }}
            QPushButton#composerMic {{
                border: 1px solid {PALETTE.accent};
                border-radius: 22px;
                background: #082630;
                color: {PALETTE.accent};
                font-size: 18px;
            }}
            QPushButton#composerMic:hover {{
                background: #0b3542;
            }}
            QPushButton#composerSend {{
                border: 1px solid {PALETTE.accent};
                border-radius: 10px;
                background: {PALETTE.accent};
                color: #031117;
                font-size: 18px;
                font-weight: 700;
            }}
            QPushButton#composerContext,
            QPushButton#composerSecondary {{
                min-height: 34px;
                padding: 4px 10px;
                border: 1px solid {PALETTE.border_strong};
                border-radius: 8px;
                background: #0a202a;
                color: {PALETTE.text_primary};
            }}
            QPushButton#composerContext:hover,
            QPushButton#composerSecondary:hover {{
                border-color: {PALETTE.accent};
            }}
            """
        )

    def _emit_send(self) -> None:
        text = self.input.text().strip()
        if text:
            self.send_requested.emit(text)

    def clear_text(self) -> None:
        self.input.clear()

    def set_voice_state(self, state: str) -> None:
        value = state.rsplit(".", 1)[-1]

        listening = value == VoiceState.LISTENING.value
        responding = value == VoiceState.RESPONDING.value
        connecting = value == VoiceState.CONNECTING.value
        active = value in {
            VoiceState.CONNECTING.value,
            VoiceState.LISTENING.value,
            VoiceState.RESPONDING.value,
            VoiceState.READY.value,
            VoiceState.INTERRUPTED.value,
        }

        self.voice_start.setEnabled(
            value
            in {
                VoiceState.IDLE.value,
                VoiceState.READY.value,
                VoiceState.ERROR.value,
            }
        )
        self.voice_commit.setVisible(listening)
        self.voice_commit.setEnabled(listening)

        self.voice_interrupt.setVisible(responding)
        self.voice_interrupt.setEnabled(responding)

        self.voice_stop.setVisible(active or value == VoiceState.ERROR.value)
        self.voice_stop.setEnabled(active or value == VoiceState.ERROR.value)

        if listening:
            self.voice_start.setText("")
            self.voice_start.setToolTip("Sofia está ouvindo")
        elif responding:
            self.voice_start.setText("")
            self.voice_start.setToolTip("Sofia está respondendo")
        elif connecting:
            self.voice_start.setText("")
            self.voice_start.setToolTip("Conectando voz")
        else:
            self.voice_start.setText("")
            self.voice_start.setToolTip("Falar com Sofia")
