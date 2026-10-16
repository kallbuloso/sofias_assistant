"""Source-first bootstrap for Sofia's Assistant.

This file intentionally is NOT a setuptools/PyInstaller build script.

Usage:
    py setup.py

It creates/updates the project virtual environment and installs only the
runtime dependencies required to run Sofia from source.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MIN_PYTHON = (3, 13)
MAX_PYTHON_EXCLUSIVE = (3, 15)


def _check_python() -> None:
    current = sys.version_info
    version = (current.major, current.minor)
    if not (MIN_PYTHON <= version < MAX_PYTHON_EXCLUSIVE):
        raise SystemExit(
            "Sofia's Assistant currently supports Python 3.13.x or 3.14.x; "
            f"detected {current.major}.{current.minor}.{current.micro}."
        )


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _ensure_venv() -> Path:
    python = _venv_python()
    if python.is_file():
        return python

    print("Creating .venv...")
    subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        check=True,
        cwd=ROOT,
    )
    if not python.is_file():
        raise SystemExit(f"virtual environment python not found: {python}")
    return python


def _install_requirements(python: Path) -> None:
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"requirements file not found: {REQUIREMENTS}")

    print("Installing Sofia's Assistant runtime dependencies...")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(REQUIREMENTS),
        ],
        check=True,
        cwd=ROOT,
    )


def main() -> int:
    _check_python()
    python = _ensure_venv()
    _install_requirements(python)

    print()
    print("Sofia's Assistant is ready.")
    print()
    print("Run:")
    print("    py main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
