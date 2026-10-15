"""Source-first bootstrap for Sofia's Assistant.

This file intentionally is NOT a setuptools/PyInstaller build script.

Usage:
    py setup.py

It validates the supported Python runtime and installs the human-facing
runtime dependencies from requirements.txt. The application itself continues
to run directly from source via py main.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
SUPPORTED_MAJOR = 3
SUPPORTED_MINOR = 13


def _check_python() -> None:
    current = sys.version_info
    if (current.major, current.minor) != (SUPPORTED_MAJOR, SUPPORTED_MINOR):
        raise SystemExit(
            "Sofia's Assistant currently requires Python "
            f"{SUPPORTED_MAJOR}.{SUPPORTED_MINOR}.x; "
            f"detected {current.major}.{current.minor}.{current.micro}."
        )


def _ensure_pip() -> None:
    probe = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode == 0:
        return

    print("pip was not found; bootstrapping it with ensurepip...")
    subprocess.run(
        [sys.executable, "-m", "ensurepip", "--upgrade"],
        check=True,
    )


def _install_requirements() -> None:
    if not REQUIREMENTS.is_file():
        raise SystemExit(f"requirements file not found: {REQUIREMENTS}")

    print("Installing Sofia's Assistant runtime dependencies...")
    subprocess.run(
        [
            sys.executable,
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
    _ensure_pip()
    _install_requirements()

    print()
    print("Sofia's Assistant is ready.")
    print()
    print("Run:")
    print("    py main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
