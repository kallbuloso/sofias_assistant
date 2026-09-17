"""Unit tests for `SubprocessCoreLauncher` argv/shell safety."""

import sys
from pathlib import Path
from unittest.mock import patch

from sofias_assistant.client_app.launcher import SubprocessCoreLauncher


def test_launch_uses_explicit_argv_without_a_shell() -> None:
    launcher = SubprocessCoreLauncher()
    captured: dict[str, object] = {}

    class _FakeProcess:
        pid = 4242

    def fake_popen(argv: list[str], **kwargs: object) -> _FakeProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProcess()

    with patch("subprocess.Popen", side_effect=fake_popen) as popen:
        pid = launcher.launch(Path(sys.executable), ["-m", "sofias_assistant.host"])

    assert pid == 4242
    assert captured["argv"] == [sys.executable, "-m", "sofias_assistant.host"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert "shell" not in kwargs
    popen.assert_called_once()


def test_launch_never_passes_a_composed_command_string() -> None:
    launcher = SubprocessCoreLauncher()

    class _FakeProcess:
        pid = 1

    with patch("subprocess.Popen", return_value=_FakeProcess()) as popen:
        launcher.launch(Path("C:/Sofia/SofiaCore.exe"), [])

    (argv,), kwargs = popen.call_args
    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    assert kwargs.get("shell", False) is False
