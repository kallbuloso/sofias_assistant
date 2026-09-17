"""Unit tests for `CoreExecutableLocator` (packaged vs. development resolution)."""

import sys
from pathlib import Path

import pytest

from sofias_assistant.client_app.executable_locator import (
    PACKAGED_CORE_EXECUTABLE_NAME,
    CoreExecutableLocator,
    CoreExecutableNotFoundError,
)


def test_development_mode_uses_the_current_interpreter_as_a_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    locator = CoreExecutableLocator()

    executable, argv = locator.locate()

    assert executable == Path(sys.executable)
    assert argv == ["-m", "sofias_assistant.host"]


def test_packaged_mode_looks_for_a_sibling_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desktop_exe = tmp_path / "SofiaAssistant.exe"
    desktop_exe.write_text("stub")
    sibling = tmp_path / PACKAGED_CORE_EXECUTABLE_NAME
    sibling.write_text("stub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(desktop_exe))
    locator = CoreExecutableLocator()

    executable, argv = locator.locate()

    assert executable == sibling
    assert argv == []


def test_packaged_mode_raises_when_the_sibling_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desktop_exe = tmp_path / "SofiaAssistant.exe"
    desktop_exe.write_text("stub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(desktop_exe))
    locator = CoreExecutableLocator()

    with pytest.raises(CoreExecutableNotFoundError):
        locator.locate()
