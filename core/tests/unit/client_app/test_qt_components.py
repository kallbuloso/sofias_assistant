"""Deterministic offscreen checks for the Desktop Client presentation shell."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from sofias_assistant.client_app.models import InferencePrivacyPreference
from sofias_assistant.client_app.widgets import ComposerWidget
from sofias_assistant.client_app.qt_app import (
    ConfirmationDialog,
    DesktopController,
    MainWindow,
    PrivacyPreferenceDialog,
    SettingsDialog,
    _tray_icon,
)


@pytest.fixture(scope="session")
def qapplication() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def test_settings_dialog_shows_native_runtime(qapplication: QApplication) -> None:
    dialog = SettingsDialog(True, None)
    assert dialog.windowTitle() == "Sofia settings"
    assert dialog._runtime.text() == "In-process Python application"
    assert dialog._runtime.isReadOnly() is True
    assert dialog.notifications_enabled is True
    dialog.close()


def test_tray_icon_is_renderable(qapplication: QApplication) -> None:
    icon = _tray_icon()
    assert not icon.isNull()


def test_privacy_dialog_defaults_to_the_given_preference(
    qapplication: QApplication,
) -> None:
    dialog = PrivacyPreferenceDialog(InferencePrivacyPreference.default(), None)

    assert dialog.preference == InferencePrivacyPreference.default()
    dialog.close()


def test_privacy_dialog_never_shows_internal_enum_names(
    qapplication: QApplication,
) -> None:
    dialog = PrivacyPreferenceDialog(InferencePrivacyPreference.default(), None)

    labels = [dialog._locality.itemText(i) for i in range(dialog._locality.count())]

    assert labels == ["Local only", "Allow cloud", "Prefer cloud"]
    for label in labels:
        assert "LOCAL_ONLY" not in label
        assert "CLOUD_ALLOWED" not in label
        assert "CLOUD_PREFERRED" not in label
    dialog.close()


def test_privacy_dialog_cloud_context_defaults_false(
    qapplication: QApplication,
) -> None:
    dialog = PrivacyPreferenceDialog(InferencePrivacyPreference.default(), None)

    assert dialog.preference.cloud_context_eligible is False
    dialog.close()


def test_confirmation_dialog_shows_only_safe_bounded_fields(
    qapplication: QApplication,
) -> None:
    from PySide6.QtWidgets import QLabel

    confirmation = {
        "capability": "filesystem.write",
        "operation": "write_file",
        "resource": "C:/dev/report.txt",
        "requested_lifetime": "ONE_SHOT",
    }
    dialog = ConfirmationDialog(confirmation, None)

    labels = " | ".join(label.text() for label in dialog.findChildren(QLabel))
    assert dialog.windowTitle() == "Sofia wants to do something"
    assert "filesystem.write" in labels
    assert "write_file" in labels
    assert "C:/dev/report.txt" in labels
    assert "ONE_SHOT" in labels
    dialog.close()



def test_settings_dialog_hosts_technical_pages(
    qapplication: QApplication,
) -> None:
    status = QLabel("status")
    ai = QLabel("ai")
    memory = QLabel("memory")
    diagnostics = QLabel("diagnostics")
    dialog = SettingsDialog(
        True,
        None,
        status_widget=status,
        ai_models_widget=ai,
        memory_widget=memory,
        health_widget=diagnostics,
    )

    labels = [
        dialog._pages.tabText(index)
        for index in range(dialog._pages.count())
    ]

    assert labels == [
        "General",
        "Status",
        "AI & Models",
        "Memory",
        "Diagnostics",
    ]
    dialog.select_page("AI & Models")
    assert dialog._pages.currentWidget() is ai
    dialog.close()


def test_main_window_is_conversation_first(
    qapplication: QApplication,
) -> None:
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)

    assert window.centralWidget().objectName() == "desktopRoot"
    assert window._conversation_list.accessibleName() == "Conversation history"
    assert window._chat.accessibleName() == "Conversation transcript"
    assert window._tasks.accessibleName() == "Current tasks"
    assert window._notifications.accessibleName() == "Notifications"
    assert window._draft.placeholderText() == "Mensagem para Sofia…"
    assert window._settings_dialog.windowTitle() == "Sofia settings"

    window._tray.hide()
    window.hide()
    window.deleteLater()
    controller.deleteLater()



def test_conversation_workspace_renders_empty_ready_state(
    qapplication: QApplication,
) -> None:
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)

    assert window._chat._hero.isVisible() is False or window._chat._hero is not None
    hero_labels = [label.text() for label in window._chat._hero.findChildren(QLabel)]
    assert "Sofia está pronta" in hero_labels
    assert "Fale ou digite sua mensagem" in hero_labels
    assert window._voice_label.text() == "Voz desligada"

    window._tray.hide()
    window.hide()
    window.deleteLater()
    controller.deleteLater()


def test_conversation_workspace_renders_distinct_user_and_sofia_cards(
    qapplication: QApplication,
) -> None:
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)

    window._conversation_messages = [
        {"role": "user", "text": "Olá Sofia", "modality": "text"},
        {"role": "assistant", "text": "Olá Amaral", "modality": "voice"},
    ]
    window._refresh_conversation_view()

    assert len(window._chat._message_widgets) == 2
    user_widget, sofia_widget = window._chat._message_widgets
    assert user_widget.role == "user"
    assert user_widget.text == "Olá Sofia"
    assert sofia_widget.role == "assistant"
    assert sofia_widget.text == "Olá Amaral"
    assert sofia_widget.modality == "voice"

    window._tray.hide()
    window.hide()
    window.deleteLater()
    controller.deleteLater()



def test_stream_updates_existing_sofia_message_widget(
    qapplication: QApplication,
) -> None:
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)

    window._start_assistant_stream()
    first_widget = window._stream_widget
    window._append_assistant_stream_delta("Olá")
    window._append_assistant_stream_delta(", Amaral")
    window._finish_assistant_stream()

    assert first_widget is not None
    assert first_widget.text == "Olá, Amaral"
    assert len(window._chat._message_widgets) == 1

    window._tray.hide()
    window.hide()
    window.deleteLater()
    controller.deleteLater()



def test_composer_hides_context_controls_while_idle(
    qapplication: QApplication,
) -> None:
    composer = ComposerWidget()

    composer.set_voice_state("IDLE")

    assert composer.input.placeholderText() == "Mensagem para Sofia…"
    assert composer.voice_start.isEnabled() is True
    assert composer.voice_commit.isVisible() is False
    assert composer.voice_interrupt.isVisible() is False
    assert composer.voice_stop.isVisible() is False
    composer.close()


def test_composer_exposes_only_relevant_voice_action(
    qapplication: QApplication,
) -> None:
    composer = ComposerWidget()
    composer.show()
    qapplication.processEvents()

    composer.set_voice_state("LISTENING")
    assert composer.voice_commit.isVisible() is True
    assert composer.voice_interrupt.isVisible() is False
    assert composer.voice_stop.isVisible() is True

    composer.set_voice_state("RESPONDING")
    assert composer.voice_commit.isVisible() is False
    assert composer.voice_interrupt.isVisible() is True
    assert composer.voice_stop.isVisible() is True
    composer.close()


@pytest.mark.parametrize(
    ("input_modality", "expected"),
    [
        ("VOICE", "voice"),
        ("TEXT", "text"),
        (None, "text"),  # Legacy turn without modality metadata
    ],
)
def test_history_restores_persisted_turn_modality(
    qapplication: QApplication, input_modality: str | None, expected: str
) -> None:
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)
    window._render_turn_page(
        {
            "turns": [
                {
                    "sequence": 1,
                    "input_modality": input_modality,
                    "user_text": "Teste de voz",
                    "assistant_text": "Recebi sua mensagem",
                    "status": "COMPLETED",
                }
            ],
            "has_older": False,
        },
        replace=True,
    )

    assert [message["modality"] for message in window._conversation_messages] == [
        expected,
        expected,
    ]
    assert [widget.modality for widget in window._chat._message_widgets] == [
        expected,
        expected,
    ]
    window._tray.hide()
    window.hide()
    window.deleteLater()
    controller.deleteLater()


def test_switching_from_long_to_short_history_recalculates_scroll_height(
    qapplication: QApplication,
) -> None:
    """Old conversation geometry must not leave scrollable space after turns."""
    from sofias_assistant.client_app.widgets import ConversationFeedWidget

    feed = ConversationFeedWidget()
    feed.resize(640, 450)
    feed.show()
    feed.set_messages(
        [{"role": "assistant", "text": f"Long turn {i}: " + "word " * 30,
          "modality": "text"} for i in range(20)]
    )
    qapplication.processEvents()
    assert feed.verticalScrollBar().maximum() > 0

    feed.set_messages(
        [{"role": "assistant", "text": "Short final reply", "modality": "voice"}]
    )
    qapplication.processEvents()
    qapplication.processEvents()

    # With only one short reply, the viewport supplies spare height. There
    # should be no scrollable blank tail inherited from the old conversation.
    assert feed.verticalScrollBar().maximum() == 0
    assert feed._message_widgets[-1].modality == "voice"
    feed.close()


def test_title_bar_keeps_actions_in_compact_and_full_width(
    qapplication: QApplication,
) -> None:
    """SAS-04D: window controls remain usable at the minimum window width."""
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)
    try:
        # At the 1280px minimum, every header action remains available.
        assert not window._maximize_button.icon().isNull()

        window.resize(1280, 800)
        window._update_header_density()
        assert not window._privacy_badge.isHidden()
        assert window._configure_action.text() == "CONFIGURAR"
        assert window._controls_action.text() == "CONTROLES"
        assert window.minimumWidth() == 1280
        assert window.minimumHeight() == 800
        assert not window._configure_action.icon().isNull()
    finally:
        window._tray.hide()
        window.hide()
        window.deleteLater()
        controller.deleteLater()


def test_desktop_chrome_rounded_mask_and_resize_grips(
    qapplication: QApplication,
) -> None:
    """SAS-04D: rounded normal window, hidden footer and directional grips."""
    from PySide6.QtCore import Qt

    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)
    try:
        assert window.minimumWidth() == 1280
        assert window.minimumHeight() == 800
        assert window.statusBar().isHidden()
        assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert len(window._resize_grips) == 8
        window._refresh_window_shape()
        assert not window.mask().isEmpty()
        shapes = {grip.objectName(): grip.cursor().shape()
                  for grip in window._resize_grips}
        assert shapes["resizeGrip_top"] == Qt.CursorShape.SizeVerCursor
        assert shapes["resizeGrip_right"] == Qt.CursorShape.SizeHorCursor
        assert shapes["resizeGrip_top_left"] == Qt.CursorShape.SizeFDiagCursor
        assert shapes["resizeGrip_top_right"] == Qt.CursorShape.SizeBDiagCursor
    finally:
        window._tray.hide()
        window.hide()
        window.deleteLater()
        controller.deleteLater()


def test_conversation_sidebar_collapse_expand_and_restore_preference(
    qapplication: QApplication,
) -> None:
    """SAS-04D Extension 01: sidebar visibility and QSettings persistence."""
    from PySide6.QtCore import QSettings

    settings = QSettings("Sofia", "SofiaAssistant")
    key = "desktop/conversation_sidebar_collapsed"
    original = settings.value(key, None)
    controller = DesktopController(
        auto_connect=False,
        api_factory=lambda: None,  # type: ignore[return-value]
    )
    window = MainWindow(controller)
    try:
        window._set_conversation_sidebar_collapsed(False)
        assert not window._sidebar_panel.isHidden()
        assert window._sidebar_expand.isHidden()

        window._sidebar_toggle.click()
        assert window._sidebar_panel.isHidden()
        assert not window._sidebar_expand.isHidden()
        assert settings.value(key, False, type=bool) is True

        window._sidebar_expand.click()
        assert not window._sidebar_panel.isHidden()
        assert window._sidebar_expand.isHidden()
        assert settings.value(key, True, type=bool) is False

        window._set_conversation_sidebar_collapsed(True, persist=True)
        assert window._sidebar_panel.isHidden()
        window._set_conversation_sidebar_collapsed(False)
        assert not window._sidebar_panel.isHidden()
    finally:
        if original is None:
            settings.remove(key)
        else:
            settings.setValue(key, original)
        window._tray.hide()
        window.hide()
        window.deleteLater()
        controller.deleteLater()
