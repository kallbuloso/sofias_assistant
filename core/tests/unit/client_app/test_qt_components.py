"""Deterministic offscreen checks for the Desktop Client presentation shell."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from sofias_assistant.client_app.models import InferencePrivacyPreference
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

    assert "Sofia está pronta" in window._chat.toPlainText()
    assert "Fale ou digite sua mensagem" in window._chat.toPlainText()
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

    rendered = window._chat.toPlainText()
    assert "Você" in rendered
    assert "Olá Sofia" in rendered
    assert "Sofia · voz" in rendered
    assert "Olá Amaral" in rendered

    window._tray.hide()
    window.hide()
    window.deleteLater()
    controller.deleteLater()
