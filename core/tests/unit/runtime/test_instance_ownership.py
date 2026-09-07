"""Unit tests for named-mutex mapping and Win32 result translation."""

from pathlib import Path
from typing import Any

import pytest

from sofias_assistant.runtime._winmutex import (
    WAIT_ABANDONED,
    WAIT_FAILED,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
)
from sofias_assistant.runtime.instance_ownership import (
    CoreAlreadyRunningError,
    CoreInstanceOwnership,
    mutex_name_for_data_dir,
)


class FakeMutexApi:
    """Recording low-level mutex fake that never uses Win32."""

    def __init__(self, wait_result: int = WAIT_OBJECT_0) -> None:
        self.wait_result = wait_result
        self.release_error: OSError | None = None
        self.close_error: OSError | None = None
        self.create_calls: list[str] = []
        self.wait_calls: list[tuple[Any, int]] = []
        self.release_calls: list[Any] = []
        self.close_calls: list[Any] = []
        self.handle = object()

    def create_mutex(self, name: str) -> Any:
        self.create_calls.append(name)
        return self.handle

    def wait_for_single_object(self, handle: Any, timeout_ms: int) -> int:
        self.wait_calls.append((handle, timeout_ms))
        return self.wait_result

    def release_mutex(self, handle: Any) -> None:
        self.release_calls.append(handle)
        if self.release_error is not None:
            raise self.release_error

    def close_handle(self, handle: Any) -> None:
        self.close_calls.append(handle)
        if self.close_error is not None:
            raise self.close_error


def test_same_data_dir_produces_same_mutex_name() -> None:
    assert mutex_name_for_data_dir(Path("C:/Sofia/data")) == mutex_name_for_data_dir(
        Path("C:/Sofia/data")
    )


def test_windows_path_case_does_not_change_mutex_name() -> None:
    assert mutex_name_for_data_dir(Path("C:/Sofia/Data")) == mutex_name_for_data_dir(
        Path("c:/sofia/data")
    )


def test_different_data_dirs_produce_different_mutex_names() -> None:
    assert mutex_name_for_data_dir(Path("C:/Sofia/one")) != mutex_name_for_data_dir(
        Path("C:/Sofia/two")
    )


def test_mutex_name_is_global_prefixed_and_hides_path_plaintext(tmp_path: Path) -> None:
    data_dir = tmp_path / "private-store"
    name = mutex_name_for_data_dir(data_dir)

    assert name.startswith("Global\\SofiasAssistant.Core.v1.")
    assert str(data_dir) not in name
    assert not data_dir.exists()


@pytest.mark.parametrize("wait_result", [WAIT_OBJECT_0, WAIT_ABANDONED])
def test_acquire_accepts_normal_or_abandoned_mutex(wait_result: int) -> None:
    api = FakeMutexApi(wait_result)
    ownership = CoreInstanceOwnership(Path("C:/Sofia/data"), api)

    ownership.acquire()

    assert api.wait_calls == [(api.handle, 0)]


def test_timeout_closes_handle_and_reports_already_running() -> None:
    api = FakeMutexApi(WAIT_TIMEOUT)
    ownership = CoreInstanceOwnership(Path("C:/Sofia/data"), api)

    with pytest.raises(CoreAlreadyRunningError):
        ownership.acquire()

    assert api.close_calls == [api.handle]


def test_wait_failed_closes_handle_and_raises_os_error() -> None:
    api = FakeMutexApi(WAIT_FAILED)
    ownership = CoreInstanceOwnership(Path("C:/Sofia/data"), api)

    with pytest.raises(OSError, match="WaitForSingleObject failed"):
        ownership.acquire()

    assert api.close_calls == [api.handle]


def test_release_calls_release_mutex_then_close_handle() -> None:
    api = FakeMutexApi()
    ownership = CoreInstanceOwnership(Path("C:/Sofia/data"), api)
    ownership.acquire()

    ownership.release()

    assert api.release_calls == [api.handle]
    assert api.close_calls == [api.handle]


def test_release_error_still_closes_handle() -> None:
    api = FakeMutexApi()
    api.release_error = OSError("release failed")
    ownership = CoreInstanceOwnership(Path("C:/Sofia/data"), api)
    ownership.acquire()

    with pytest.raises(OSError, match="release failed"):
        ownership.release()

    assert api.close_calls == [api.handle]


def test_close_error_is_propagated_when_release_succeeds() -> None:
    api = FakeMutexApi()
    api.close_error = OSError("close failed")
    ownership = CoreInstanceOwnership(Path("C:/Sofia/data"), api)
    ownership.acquire()

    with pytest.raises(OSError, match="close failed"):
        ownership.release()
