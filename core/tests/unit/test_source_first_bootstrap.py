"""Tests for the source-first repository entry points introduced by SAS-02."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requirements_are_runtime_only() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "PySide6" in requirements
    assert "PyInstaller" not in requirements
    assert "uv_build" not in requirements


def test_main_exposes_core_source_to_current_and_child_process(monkeypatch) -> None:
    module = _load_module("source_first_main", ROOT / "main.py")
    source = str((ROOT / "core" / "src").resolve())

    monkeypatch.setattr(module, "CORE_SRC", Path(source))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(sys, "path", [item for item in sys.path if item != source])

    module._prepare_source_path()

    assert sys.path[0] == source
    assert os.environ["PYTHONPATH"].split(os.pathsep)[0] == source


def test_setup_uses_project_venv_and_requirements(monkeypatch, tmp_path) -> None:
    module = _load_module("source_first_setup", ROOT / "setup.py")
    calls: list[list[str]] = []

    module.VENV_DIR = tmp_path / ".venv"
    module.REQUIREMENTS = tmp_path / "requirements.txt"
    module.REQUIREMENTS.write_text("example-package==1.0\n", encoding="utf-8")

    python = module._venv_python()
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")

    def fake_run(argv, **_kwargs):
        calls.append([str(item) for item in argv])

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    resolved = module._ensure_venv()
    module._install_requirements(resolved)

    assert resolved == python
    assert calls == [[str(python), "-m", "pip", "install", "-r", str(module.REQUIREMENTS)]]
