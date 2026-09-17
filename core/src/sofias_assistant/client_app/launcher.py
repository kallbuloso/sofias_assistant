"""Explicit-argv Core process launcher (Desktop/Core Interaction Contract v1 SS18).

Never `shell=True`, never a composed command string, never a credential in
argv. The launched Core process is detached: it is not owned by the
launching process and keeps running after that process exits (Amendment
0004 SS4/SS6). The returned PID is diagnostic evidence only, never lifecycle
authority (Amendment 0004 SS6).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol

_DETACHED_CREATION_FLAGS = 0
if sys.platform == "win32":
    _DETACHED_CREATION_FLAGS = (
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    )


class ProcessLauncher(Protocol):
    """Start a Core process from an explicit executable and argv."""

    def launch(self, executable: Path, argv: list[str]) -> int | None:
        """Start the detached process; return its PID as diagnostic evidence."""
        ...


class SubprocessCoreLauncher:
    """`subprocess.Popen`-based launcher for development and deterministic tests.

    On Windows the child is created detached (`CREATE_NEW_PROCESS_GROUP |
    DETACHED_PROCESS`) so it survives this process's exit, matching the
    packaged `QtProcessLauncher` behavior without depending on Qt.
    """

    def launch(self, executable: Path, argv: list[str]) -> int | None:
        process = subprocess.Popen(  # noqa: S603
            [str(executable), *argv],
            creationflags=_DETACHED_CREATION_FLAGS,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return process.pid


class QtProcessLauncher:
    """Production launcher using `QProcess.startDetached` (Qt for Python).

    A detached process keeps running when the Desktop application exits and
    Qt provides no further control/communication with it after this call --
    exactly the boundary Contract v1 requires. PySide6 is imported lazily so
    this module stays importable without the optional `client` dependency
    group in supervisor unit tests.
    """

    def launch(self, executable: Path, argv: list[str]) -> int | None:
        from PySide6.QtCore import QProcess

        started, pid = QProcess.startDetached(str(executable), argv)
        if not started:
            raise RuntimeError(f"failed to start Core process: {executable}")
        return pid
