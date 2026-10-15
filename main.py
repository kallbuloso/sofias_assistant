"""Canonical source-first entry point for Sofia's Assistant.

Usage:
    py main.py

SAS-02 deliberately reuses the existing Desktop/Core implementation while
removing build/dist/PyInstaller from the development critical path.

The unpackaged Desktop supervisor already knows how to launch the Core with
the current Python interpreter. SAS-03 will replace that temporary two-process
transport path with the approved single-process SofiaApplication composition.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE_SRC = ROOT / "core" / "src"


def _prepare_source_path() -> None:
    """Expose core/src to this process and the supervised Core child."""

    source = str(CORE_SRC)
    if not CORE_SRC.is_dir():
        raise SystemExit(f"Sofia source directory not found: {CORE_SRC}")

    if source not in sys.path:
        sys.path.insert(0, source)

    current = os.environ.get("PYTHONPATH", "")
    paths = [item for item in current.split(os.pathsep) if item]
    if source not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([source, *paths])


def main(argv: list[str] | None = None) -> int:
    _prepare_source_path()

    from sofias_assistant.client_app.__main__ import main as desktop_main

    return desktop_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
