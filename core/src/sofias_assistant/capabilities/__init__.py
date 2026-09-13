"""Built-in computer capabilities behind the Core Tool Runtime."""

from sofias_assistant.capabilities.desktop import (
    DesktopBackend,
    FakeDesktopBackend,
    WindowsDesktopBackend,
)
from sofias_assistant.capabilities.filesystem import FilesystemCapability
from sofias_assistant.capabilities.shell import ShellCapability
from sofias_assistant.capabilities.web import (
    DuckDuckGoSearchBackend,
    FakeSearchBackend,
    WebReader,
)

__all__ = [
    "DesktopBackend",
    "FakeDesktopBackend",
    "WindowsDesktopBackend",
    "DuckDuckGoSearchBackend",
    "FakeSearchBackend",
    "FilesystemCapability",
    "ShellCapability",
    "WebReader",
]
