"""Custom conversation presentation widgets for Sofia Desktop."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sofias_assistant.client_app.widgets.style import (
    PALETTE,
    RADIUS_LG,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
)


class ConversationMessage(TypedDict):
    role: str
    text: str
    modality: str


class ConversationMessageWidget(QWidget):
    """One aligned conversation bubble with stable streaming updates."""

    def __init__(
        self,
        role: str,
        text: str,
        modality: str = "text",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        self.modality = modality

        row = QHBoxLayout(self)
        row.setContentsMargins(0, SPACE_SM, 0, SPACE_SM)
        row.setSpacing(SPACE_SM)

        if role == "user":
            row.addStretch(1)

        self._avatar = QLabel("◉" if role == "assistant" else "●")
        self._avatar.setFixedSize(30, 30)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setObjectName(
            "sofiaAvatar" if role == "assistant" else "userAvatar"
        )

        bubble = QFrame()
        bubble.setObjectName(
            "userMessage"
            if role == "user"
            else "sofiaMessage"
            if role == "assistant"
            else "systemMessage"
        )
        bubble.setMaximumWidth(680)
        bubble.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum,
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(SPACE_MD, SPACE_SM, SPACE_MD, SPACE_MD)
        bubble_layout.setSpacing(5)

        author = (
            "Você"
            if role == "user"
            else "Sofia"
            if role == "assistant"
            else "Sistema"
        )
        modality_suffix = " · voz" if modality == "voice" else ""
        self._meta = QLabel(f"{author}{modality_suffix}")
        self._meta.setObjectName("messageMeta")

        self._body = QLabel()
        self._body.setObjectName("messageBody")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._body.setTextFormat(Qt.TextFormat.PlainText)

        bubble_layout.addWidget(self._meta)
        bubble_layout.addWidget(self._body)

        if role == "assistant":
            row.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignTop)
        if role != "user":
            row.addStretch(1)
        else:
            row.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)

        self.set_text(text)

    @property
    def text(self) -> str:
        return self._body.text()

    def set_text(self, text: str) -> None:
        self._body.setText(text)


class ConversationFeedWidget(QScrollArea):
    """Scrollable widget feed for durable text and voice turns."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setAccessibleName("Conversation transcript")
        self.setObjectName("conversationFeed")

        self._content = QWidget()
        self._content.setObjectName("conversationFeedContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(SPACE_LG, SPACE_LG, SPACE_LG, SPACE_LG)
        self._layout.setSpacing(2)
        self.setWidget(self._content)

        self._message_widgets: list[ConversationMessageWidget] = []
        self._hero = self._build_hero()
        self._layout.addWidget(self._hero, 1)
        self._layout.addStretch(0)

        self.setStyleSheet(
            f"""
            QScrollArea#conversationFeed {{
                background: {PALETTE.background};
                border: 1px solid {PALETTE.border};
                border-radius: {RADIUS_LG}px;
            }}
            QWidget#conversationFeedContent {{
                background: {PALETTE.background};
            }}
            QFrame#userMessage {{
                background: {PALETTE.surface_user};
                border: 1px solid #13506e;
                border-radius: {RADIUS_LG}px;
            }}
            QFrame#sofiaMessage {{
                background: {PALETTE.surface_raised};
                border: 1px solid #183d49;
                border-radius: {RADIUS_LG}px;
            }}
            QFrame#systemMessage {{
                background: #2a2020;
                border: 1px solid #6f4040;
                border-radius: {RADIUS_LG}px;
            }}
            QLabel#messageMeta {{
                color: {PALETTE.text_secondary};
                font-size: 11px;
            }}
            QLabel#messageBody {{
                color: {PALETTE.text_primary};
                font-size: 14px;
            }}
            QLabel#sofiaAvatar {{
                color: {PALETTE.accent};
                font-size: 22px;
                border: 1px solid {PALETTE.accent};
                border-radius: 15px;
                background: #082630;
            }}
            QLabel#userAvatar {{
                color: #9fd7ff;
                font-size: 16px;
                border: 1px solid #315b7a;
                border-radius: 15px;
                background: #102b3f;
            }}
            """
        )

    def _build_hero(self) -> QWidget:
        hero = QWidget()
        layout = QVBoxLayout(hero)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(7)

        orb = QLabel("◉")
        orb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        orb.setStyleSheet(
            f"color:{PALETTE.accent}; font-size:52px; font-weight:600;"
        )
        title = QLabel("Sofia está pronta")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:{PALETTE.text_primary}; font-size:20px; font-weight:600;"
        )
        subtitle = QLabel("Fale ou digite sua mensagem")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"color:{PALETTE.text_secondary}; font-size:13px;"
        )

        layout.addStretch(1)
        layout.addWidget(orb)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return hero

    def _clear_layout_messages(self) -> None:
        for widget in self._message_widgets:
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._message_widgets.clear()

    def clear_messages(self) -> None:
        self._clear_layout_messages()
        self._hero.show()

    def set_messages(self, messages: Iterable[ConversationMessage]) -> None:
        self._clear_layout_messages()
        message_list = list(messages)
        self._hero.setVisible(not message_list)
        for message in message_list:
            self.add_message(
                message["role"],
                message["text"],
                message.get("modality", "text"),
                scroll=False,
            )
        if message_list:
            self.scroll_to_bottom()

    def add_message(
        self,
        role: str,
        text: str,
        modality: str = "text",
        *,
        scroll: bool = True,
    ) -> ConversationMessageWidget:
        self._hero.hide()
        widget = ConversationMessageWidget(role, text, modality, self._content)
        # Insert before the trailing stretch.
        self._layout.insertWidget(self._layout.count() - 1, widget)
        self._message_widgets.append(widget)
        if scroll:
            self.scroll_to_bottom()
        return widget

    def scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum()
            ),
        )
