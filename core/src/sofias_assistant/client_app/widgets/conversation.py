"""Custom conversation presentation widgets for Sofia Desktop."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypedDict

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLayout,
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
        # Keep each turn at its natural height; spare space belongs below the feed.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(6)

        if role == "user":
            row.addStretch(1)

        bubble = QFrame()
        bubble.setObjectName(
            "userMessage"
            if role == "user"
            else "sofiaMessage"
            if role == "assistant"
            else "systemMessage"
        )
        bubble.setMaximumWidth(620)
        bubble.setMinimumWidth(220 if role == "user" else 360)
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

        row.addWidget(bubble, 0, Qt.AlignmentFlag.AlignTop)
        if role != "user":
            row.addStretch(1)

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
        self._layout.setContentsMargins(24, 24, 24, 24)
        self._layout.setSpacing(5)
        self.setWidget(self._content)

        self._message_widgets: list[ConversationMessageWidget] = []
        self._hero = self._build_hero()
        self._layout.addWidget(self._hero, 1)

        # Isolate message rows from the expanding scroll-area layout.
        # Only the bottom spacer may absorb unused vertical space.
        self._messages_host = QWidget(self._content)
        # The host should follow its layout's natural height, not expand to
        # the scroll viewport and leave scrollable whitespace below messages.
        self._messages_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(0, 0, 0, 0)
        self._messages_layout.setSpacing(5)
        # Force Qt to refresh the host's minimum/maximum size whenever turns
        # are removed or added; otherwise old fixed geometry can survive a
        # Conversation switch and create a long empty scrollbar range.
        self._messages_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        # Do not insert an expanding spacer into the scrollable document.
        # On short conversations the viewport itself supplies empty space;
        # on long ones the scroll range must end at the last message.
        self._layout.addWidget(self._messages_host, 0, Qt.AlignmentFlag.AlignTop)
        self._messages_host.hide()

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
                line-height: 1.35;
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
            self._messages_layout.removeWidget(widget)
            widget.deleteLater()
        self._message_widgets.clear()
        self._messages_layout.invalidate()
        self._messages_host.updateGeometry()

    def clear_messages(self) -> None:
        self._clear_layout_messages()
        self._messages_host.hide()
        self._layout.setStretch(0, 1)
        self._hero.show()

    def set_messages(self, messages: Iterable[ConversationMessage]) -> None:
        self._clear_layout_messages()
        message_list = list(messages)
        self._hero.setVisible(not message_list)
        self._layout.setStretch(0, 0 if message_list else 1)
        self._messages_host.setVisible(bool(message_list))
        for message in message_list:
            self.add_message(
                message["role"],
                message["text"],
                message.get("modality", "text"),
                scroll=False,
            )
        self._messages_layout.invalidate()
        self._messages_host.updateGeometry()
        self._layout.invalidate()
        self._content.updateGeometry()
        if message_list:
            self.scroll_to_latest_on_restore()

    def add_message(
        self,
        role: str,
        text: str,
        modality: str = "text",
        *,
        scroll: bool = True,
    ) -> ConversationMessageWidget:
        self._hero.hide()
        # The hidden empty-state hero must not retain its expanding stretch.
        # Otherwise Qt can allocate a large scrollable void after the turns.
        self._layout.setStretch(0, 0)
        self._messages_host.show()
        widget = ConversationMessageWidget(role, text, modality, self._messages_host)
        self._messages_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
        self._message_widgets.append(widget)
        self._messages_host.updateGeometry()
        if scroll:
            self.scroll_to_bottom()
        return widget

    def scroll_to_latest_on_restore(self) -> None:
        """Open a restored conversation at its latest turn after geometry settles."""
        # Restoring many QLabel bubbles can change document heights after the
        # first scrollbar update. Recompute geometry before positioning.
        QTimer.singleShot(0, self._finish_restore_scroll)

    def _finish_restore_scroll(self) -> None:
        if not self._message_widgets:
            return
        self._messages_layout.activate()
        self._messages_host.updateGeometry()
        self._layout.activate()
        # Scrolling to a scrollbar maximum can land in blank layout space.
        # Anchor the viewport to the actual last message instead.
        self.ensureWidgetVisible(self._message_widgets[-1], 0, 12)
        QTimer.singleShot(0, self._ensure_latest_visible)

    def _ensure_latest_visible(self) -> None:
        if self._message_widgets:
            self.ensureWidgetVisible(self._message_widgets[-1], 0, 12)

    def scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum()
            ),
        )
