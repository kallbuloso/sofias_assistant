"""Windows single-instance ownership for one Operational Store."""

import hashlib
import os
from pathlib import Path
from typing import Any, Protocol

from sofias_assistant.runtime._winmutex import (
    WAIT_ABANDONED,
    WAIT_FAILED,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
    Kernel32MutexApi,
    WinMutexApi,
)

_MUTEX_PREFIX = "Global\\SofiasAssistant.Core.v1."


class CoreAlreadyRunningError(RuntimeError):
    """Raised when another Core already owns the same Operational Store."""

    def __init__(self) -> None:
        super().__init__(
            "Another SofiaCore instance already owns this Operational Store"
        )


class InstanceOwnership(Protocol):
    """Minimal lifecycle contract for the Core's exclusive store ownership."""

    def acquire(self) -> None: ...

    def release(self) -> None: ...


def mutex_name_for_data_dir(data_dir: Path) -> str:
    """Return a stable, non-plaintext Win32 mutex name for a data directory."""

    absolute_path = os.path.abspath(os.fspath(data_dir))
    normalized_path = os.path.normcase(os.path.normpath(absolute_path))
    windows_identity = normalized_path.replace("/", "\\").casefold()
    store_key = hashlib.sha256(windows_identity.encode("utf-8")).hexdigest()
    return f"{_MUTEX_PREFIX}{store_key}"


class CoreInstanceOwnership:
    """Own a named Win32 mutex for the lifetime of one SofiaCore instance."""

    def __init__(self, data_dir: Path, api: WinMutexApi | None = None) -> None:
        self._mutex_name = mutex_name_for_data_dir(data_dir)
        self._api = api if api is not None else Kernel32MutexApi()
        self._handle: Any | None = None

    def acquire(self) -> None:
        """Immediately acquire ownership, or fail if another Core owns it."""

        if self._handle is not None:
            raise RuntimeError("Core instance ownership has already been acquired")

        handle = self._api.create_mutex(self._mutex_name)
        try:
            result = self._api.wait_for_single_object(handle, 0)
            if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
                self._handle = handle
                return
            if result == WAIT_TIMEOUT:
                raise CoreAlreadyRunningError()
            if result == WAIT_FAILED:
                raise OSError("WaitForSingleObject failed")
            raise RuntimeError(f"Unexpected WaitForSingleObject result: {result}")
        except BaseException:
            try:
                self._api.close_handle(handle)
            except BaseException:
                pass
            raise

    def release(self) -> None:
        """Release ownership and close its handle exactly once."""

        handle = self._handle
        if handle is None:
            raise RuntimeError("Core instance ownership is not acquired")

        self._handle = None
        release_error: BaseException | None = None
        try:
            self._api.release_mutex(handle)
        except BaseException as error:
            release_error = error
        try:
            self._api.close_handle(handle)
        except BaseException:
            if release_error is None:
                raise
        if release_error is not None:
            raise release_error
