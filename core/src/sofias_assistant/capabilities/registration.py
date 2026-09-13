"""Composition helper for the built-in Tool Registry capabilities."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from sofias_assistant.capabilities.desktop import (
    DesktopBackend,
    DesktopCapability,
    FakeDesktopBackend,
    WindowsDesktopBackend,
)
from sofias_assistant.capabilities.filesystem import FilesystemCapability
from sofias_assistant.capabilities.shell import ShellCapability
from sofias_assistant.capabilities.web import WebReader, WebSearchBackend
from sofias_assistant.execution.runtime import ExecutionRuntime


def register_builtin_capabilities(
    runtime: ExecutionRuntime,
    *,
    desktop_backend: DesktopBackend | None = None,
    search_backend: WebSearchBackend | None = None,
    applications: Mapping[str, Path] | None = None,
) -> None:
    """Register production capability specs exactly once during Core composition."""

    for spec in FilesystemCapability().specs():
        runtime.register_tool(spec)
    runtime.register_tool(ShellCapability().spec())
    for spec in WebReader(search_backend=search_backend).specs():
        runtime.register_tool(spec)
    backend = desktop_backend or (
        WindowsDesktopBackend(applications) if os.name == "nt" else FakeDesktopBackend()
    )
    desktop = DesktopCapability(backend, runtime.artifacts)
    for spec in desktop.specs():
        runtime.register_tool(spec)
