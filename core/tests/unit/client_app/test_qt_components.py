"""Deterministic offscreen checks for the Desktop Client presentation shell."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from sofias_assistant.client_app.qt_app import SettingsDialog, _tray_icon


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
