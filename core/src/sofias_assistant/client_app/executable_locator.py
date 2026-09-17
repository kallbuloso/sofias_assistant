"""Locate the Core process launch target (Desktop/Core Interaction Contract v1 SS17).

Packaged product: a sibling `SofiaCore.exe` next to the running Desktop
executable. Development/unpackaged fallback: the current Python interpreter
running `sofias_assistant.host` as a module, which starts the exact same
`sofia-core` production lifecycle (`host.runner.main`) as a genuinely
separate OS process. Either way the Desktop launches Core with an explicit
executable path and explicit argv -- never a shell/composed command string.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

PACKAGED_CORE_EXECUTABLE_NAME = "SofiaCore.exe"


class CoreExecutableNotFoundError(RuntimeError):
    """Raised when no Core launch target can be located."""


class ExecutableLocator(Protocol):
    """Structural contract the supervisor depends on (tests inject fakes)."""

    def locate(self) -> tuple[Path, list[str]]: ...


class CoreExecutableLocator:
    """Resolve `(executable, argv)` for launching Core as a separate process."""

    def locate(self) -> tuple[Path, list[str]]:
        if getattr(sys, "frozen", False):
            packaged = (
                Path(sys.executable).resolve().parent / PACKAGED_CORE_EXECUTABLE_NAME
            )
            if not packaged.is_file():
                raise CoreExecutableNotFoundError(
                    f"packaged Core executable not found: {packaged}"
                )
            return packaged, []
        return Path(sys.executable), ["-m", "sofias_assistant.host"]
