"""Deterministic offscreen checks for the Desktop Client presentation shell."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from sofias_assistant.client_app.models import InferencePrivacyPreference
from sofias_assistant.client_app.qt_app import (
    ConfirmationDialog,
    PrivacyPreferenceDialog,
    SettingsDialog,
    _tray_icon,
)


@pytest.fixture(scope="session")
def qapplication() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def test_settings_dialog_keeps_core_url_read_only(qapplication: QApplication) -> None:
    dialog = SettingsDialog("http://127.0.0.1:8989", True, None)
    assert dialog.windowTitle() == "Sofia settings"
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
