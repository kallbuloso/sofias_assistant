"""Canonical source-first entry point for Sofia's Assistant.

Usage:
    py main.py

The script automatically re-launches itself inside the project .venv created
by setup.py and exposes core/src directly from the working tree.

SAS-03A starts the canonical SofiaApplication composition root. The legacy
loopback HTTP/WebSocket boundary remains temporarily available only as a
compatibility adapter for Desktop surfaces that have not yet migrated to
direct application services.

For source-first human startup, a conservative default bootstrap model is
provided only when LLM_MODEL is completely absent. Explicit user/environment
configuration always wins.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE_SRC = ROOT / "src"
VENV_DIR = ROOT / ".venv"
DEFAULT_SOURCE_MODEL = "gpt-4o-mini"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _running_inside_project_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def _run_in_project_venv() -> int | None:
    """Re-launch through .venv when main.py was started with system Python."""

    if _running_inside_project_venv():
        return None

    python = _venv_python()
    if not python.is_file():
        raise SystemExit(
            "Project environment not found. Run 'py setup.py' first."
        )

    os.chdir(ROOT)
    os.execv(
        str(python),
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )
    raise AssertionError("os.execv returned unexpectedly")


def _prepare_source_path() -> None:
    """Expose the application source tree to the current process."""

    source = str(CORE_SRC)
    if not CORE_SRC.is_dir():
        raise SystemExit(f"Sofia source directory not found: {CORE_SRC}")

    if source not in sys.path:
        sys.path.insert(0, source)

    current = os.environ.get("PYTHONPATH", "")
    paths = [item for item in current.split(os.pathsep) if item]
    if source not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([source, *paths])


def _prepare_source_bootstrap() -> None:
    """Provide only the minimum bootstrap needed for a visual source run."""

    if "LLM_MODEL" not in os.environ:
        os.environ["LLM_MODEL"] = DEFAULT_SOURCE_MODEL


def main(argv: list[str] | None = None) -> int:
    _prepare_source_path()
    _prepare_source_bootstrap()

    if argv:
        raise SystemExit("source-first main.py does not accept runtime arguments yet")

    from sofias_assistant.application import run_desktop

    return run_desktop()


if __name__ == "__main__":
    relaunched = _run_in_project_venv()
    if relaunched is not None:
        raise SystemExit(relaunched)
    raise SystemExit(main())
