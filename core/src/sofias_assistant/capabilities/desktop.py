"""Small Windows-first desktop backend and explicit screen capture Tool."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sofias_assistant.execution.artifacts import ArtifactService
from sofias_assistant.execution.models import (
    GrantLifetime,
    ToolResult,
    ToolSpec,
)


class DesktopBackend(Protocol):
    def open_app(self, identifier: str) -> Mapping[str, object]: ...

    def active_window(self) -> Mapping[str, object]: ...

    def capture_screen(self) -> bytes: ...


class FakeDesktopBackend:
    """Deterministic desktop backend used by unit and integration tests."""

    def __init__(self, *, active_title: str = "Fake Desktop") -> None:
        self.active_title = active_title
        self.opened: list[str] = []

    def open_app(self, identifier: str) -> Mapping[str, object]:
        self.opened.append(identifier)
        return {"identifier": identifier, "opened": True}

    def active_window(self) -> Mapping[str, object]:
        return {"title": self.active_title, "handle": "fake-window"}

    def capture_screen(self) -> bytes:
        return b"FAKE-SOFIA-SCREENSHOT\n"


class WindowsDesktopBackend:
    """Native Windows implementation with an explicit application allowlist."""

    def __init__(self, applications: Mapping[str, Path] | None = None) -> None:
        defaults = {
            "notepad": Path(os.environ.get("WINDIR", r"C:\\Windows"))
            / "System32"
            / "notepad.exe"
        }
        self._applications = {**defaults, **dict(applications or {})}

    def open_app(self, identifier: str) -> Mapping[str, object]:
        if os.name != "nt":
            raise RuntimeError("Windows desktop backend is unavailable")
        path = self._applications.get(identifier)
        if path is None:
            raise ValueError("application is not registered")
        if not path.is_file():
            raise ValueError("registered application does not exist")
        os.startfile(str(path))
        return {"identifier": identifier, "opened": True}

    def active_window(self) -> Mapping[str, object]:
        if os.name != "nt":
            raise RuntimeError("Windows desktop backend is unavailable")
        user32 = ctypes.windll.user32
        handle = user32.GetForegroundWindow()
        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(handle, buffer, len(buffer))
        return {"title": buffer.value, "handle": int(handle)}

    def capture_screen(self) -> bytes:
        if os.name != "nt":
            raise RuntimeError("Windows desktop backend is unavailable")
        return _capture_screen_bmp()


class DesktopCapability:
    def __init__(self, backend: DesktopBackend, artifacts: ArtifactService) -> None:
        self.backend = backend
        self.artifacts = artifacts

    def specs(self) -> tuple[ToolSpec, ...]:
        return (
            ToolSpec(
                name="desktop.open_app",
                version="1",
                description="Open one known application through the desktop backend",
                capability="desktop.open_app",
                handler=self.open_app,
                resource_resolver=lambda args: (
                    "desktop.app:" + str(args["application"])
                ),
                input_validator=self._validate_application,
                confirmation_required=True,
                confirmation_lifetime=GrantLifetime.ONE_SHOT,
            ),
            ToolSpec(
                name="desktop.active_window",
                version="1",
                description="Read the current foreground window metadata",
                capability="desktop.active_window",
                handler=self.active_window,
                resource_resolver=lambda _: "desktop.window:foreground",
            ),
            ToolSpec(
                name="desktop.capture_screen",
                version="1",
                description="Capture one explicit screen image as an ArtifactRef",
                capability="desktop.capture_screen",
                handler=self.capture_screen,
                resource_resolver=lambda _: "desktop.screen:primary",
                confirmation_required=True,
                confirmation_lifetime=GrantLifetime.ONE_SHOT,
            ),
        )

    @staticmethod
    def _validate_application(arguments: Mapping[str, object]) -> Mapping[str, object]:
        value = arguments.get("application")
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise ValueError("application identifier is invalid")
        return {"application": value.strip()}

    def open_app(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        return self.backend.open_app(str(arguments["application"]))

    def active_window(self, _: Mapping[str, object]) -> Mapping[str, object]:
        return self.backend.active_window()

    async def capture_screen(self, _: Mapping[str, object]) -> ToolResult:
        data = self.backend.capture_screen()
        ref = await self.artifacts.create(
            data,
            kind="desktop-screenshot",
            media_type="image/bmp",
        )
        return ToolResult(
            status="SUCCEEDED",
            call_id=UUID(int=0),
            value={"artifact_id": str(ref.id), "media_type": ref.media_type},
            artifact_refs=(ref,),
        )


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _capture_screen_bmp() -> bytes:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(
            memory_dc, 0, 0, width, height, screen_dc, 0, 0, 0x00CC0020
        ):
            raise RuntimeError("screen capture failed")
        header = _BitmapInfoHeader(
            ctypes.sizeof(_BitmapInfoHeader), width, height, 1, 32, 0, 0, 0, 0, 0, 0
        )
        size = width * height * 4
        pixels = (ctypes.c_ubyte * size)()
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0)
        file_header = (
            b"BM"
            + (54 + size).to_bytes(4, "little")
            + b"\0\0\0\0"
            + (54).to_bytes(4, "little")
        )
        return file_header + bytes(header) + bytes(pixels)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, screen_dc)
