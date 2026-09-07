"""Minimal lazy ctypes boundary for the Win32 mutex APIs used by the Core."""

import ctypes
import os
from ctypes import wintypes
from typing import Any, Protocol

WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF


class WinMutexApi(Protocol):
    """Small low-level contract for named mutex ownership."""

    def create_mutex(self, name: str) -> Any: ...

    def wait_for_single_object(self, handle: Any, timeout_ms: int) -> int: ...

    def release_mutex(self, handle: Any) -> None: ...

    def close_handle(self, handle: Any) -> None: ...


class Kernel32MutexApi:
    """Lazy wrapper around only the Kernel32 APIs needed for this mutex."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError(
                "Win32 named mutex ownership is only available on Windows"
            )

        api = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        api.CreateMutexW.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.ReleaseMutex.argtypes = [wintypes.HANDLE]
        api.ReleaseMutex.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        self._api = api

    def create_mutex(self, name: str) -> Any:
        handle = self._api.CreateMutexW(None, False, name)
        if not handle:
            self._raise_last_error()
        return handle

    def wait_for_single_object(self, handle: Any, timeout_ms: int) -> int:
        result = int(self._api.WaitForSingleObject(handle, timeout_ms))
        if result == WAIT_FAILED:
            self._raise_last_error()
        return result

    def release_mutex(self, handle: Any) -> None:
        if not self._api.ReleaseMutex(handle):
            self._raise_last_error()

    def close_handle(self, handle: Any) -> None:
        if not self._api.CloseHandle(handle):
            self._raise_last_error()

    @staticmethod
    def _raise_last_error() -> None:
        error_code = ctypes.get_last_error()
        raise OSError(0, ctypes.FormatError(error_code), None, error_code)
