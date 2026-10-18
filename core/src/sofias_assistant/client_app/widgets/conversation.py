"""Custom conversation presentation widgets for Sofia Desktop."""

from __future__ import annotations

import os
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
        # Rows must occupy their natural height. A Maximum vertical policy
        # still lets Qt distribute surplus space between messages when the
        # host is resized; Fixed prevents that without constraining width.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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
        # A resizable scroll-area child must recompute its natural height when
        # the message layout changes. Without this, the outer widget retains
        # a stale height (1211px vs a 1021px size hint in Windows diagnostics).
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
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
        # Keep all message rows packed at the top even when the host receives
        # surplus height from QScrollArea. Never distribute it between turns.
        self._messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        # Force Qt to refresh the host's minimum/maximum size whenever turns
        # are removed or added; otherwise old fixed geometry can survive a
        # Conversation switch and create a long empty scrollbar range.
        # Let Qt derive its size from the visible rows. SetMinAndMaxSize
        # previously locked the host to a stale minimum (1163px for a
        # 973px size hint), leaving an artificial scrollable tail.
        self._messages_layout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        # The message host must not grow to fill a tall viewport: extra
        # viewport space belongs outside the scrollable message content.
        self._messages_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
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
        self._messages_layout.addWidget(widget)
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
        # Do not fix the host height from a transient size hint.
        self._messages_host.updateGeometry()
        self._layout.invalidate()
        self._layout.activate()
        # Scrolling to a scrollbar maximum can land in blank layout space.
        # Anchor the viewport to the actual last message instead.
        self.ensureWidgetVisible(self._message_widgets[-1], 0, 12)
        QTimer.singleShot(0, self._ensure_latest_visible)
        if os.environ.get("SOFIA_DEBUG_FEED_GEOMETRY") == "1":
            QTimer.singleShot(150, self._debug_feed_geometry)

    def _ensure_latest_visible(self) -> None:
        if self._message_widgets:
            self.ensureWidgetVisible(self._message_widgets[-1], 0, 12)

    def _debug_feed_geometry(self) -> None:
        """Opt-in diagnosis: no resizing, scrolling or mutation."""
        bar = self.verticalScrollBar()
        last = self._message_widgets[-1] if self._message_widgets else None
        last_bottom = (
            last.mapTo(self._content, last.rect().bottomLeft()).y()
            if last is not None else None
        )
        data = {
            "viewport_height": self.viewport().height(),
            "content_height": self._content.height(),
            "content_size_hint": self._content.sizeHint().height(),
            "root_layout_height": self._layout.geometry().height(),
            "content_min_height": self._content.minimumHeight(),
            "content_max_height": self._content.maximumHeight(),
            "hero_visible": self._hero.isVisible(),
            "hero_height": self._hero.height(),
            "hero_stretch": self._layout.stretch(0),
            "messages_host_y": self._messages_host.y(),
            "messages_host_height": self._messages_host.height(),
            "messages_host_size_hint": self._messages_host.sizeHint().height(),
            "messages_host_min_height": self._messages_host.minimumHeight(),
            "messages_host_max_height": self._messages_host.maximumHeight(),
            "messages_layout_size_hint": self._messages_layout.sizeHint().height(),
            "messages_layout_min_size": self._messages_layout.minimumSize().height(),
            "messages_layout_constraint": str(self._messages_layout.sizeConstraint()),
            "row_metrics": [
                {
                    "height": widget.height(),
                    "hint": widget.sizeHint().height(),
                    "min": widget.minimumHeight(),
                    "max": widget.maximumHeight(),
                }
                for widget in self._message_widgets[-4:]
            ],
            "messages_layout_height": self._messages_layout.geometry().height(),
            "message_count": len(self._message_widgets),
            "last_message_bottom_in_content": last_bottom,
            "trailing_height": (
                self._content.height() - last_bottom if last_bottom is not None
                else None
            ),
            "scroll_value": bar.value(),
            "scroll_max": bar.maximum(),
        }
        print(f"[SOFIA_FEED_GEOMETRY] {data}", flush=True)

    def scroll_to_bottom(self) -> None:
        QTimer.singleShot(
            0,
            lambda: self.verticalScrollBar().setValue(
                self.verticalScrollBar().maximum()
            ),
        )
