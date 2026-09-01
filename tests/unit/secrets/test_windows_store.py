"""Unit tests for Windows Credential Manager translation logic."""

import ctypes
from typing import Any

import pytest

from sofias_assistant.secrets._wincred import (
    CRED_MAX_CREDENTIAL_BLOB_SIZE,
    CRED_MAX_GENERIC_TARGET_NAME_LENGTH,
    CRED_PERSIST_LOCAL_MACHINE,
    CRED_TYPE_GENERIC,
    CREDENTIALW,
    ERROR_NOT_FOUND,
)
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.windows_store import WindowsCredentialStore


def _win_error(error_code: int) -> OSError:
    return OSError(0, "Win32 failure", None, error_code)


class FakeCredentialApi:
    """In-memory low-level fake; it never calls the real Windows APIs."""

    def __init__(self) -> None:
        self.read_error: OSError | None = None
        self.write_error: OSError | None = None
        self.delete_error: OSError | None = None
        self.read_credential: Any = None
        self.freed: list[Any] = []
        self.read_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.writes: list[tuple[str, int, int, bytes]] = []

    def read(self, target: str) -> Any:
        self.read_calls.append(target)
        if self.read_error is not None:
            raise self.read_error
        return self.read_credential

    def write(self, credential: CREDENTIALW) -> None:
        if self.write_error is not None:
            raise self.write_error
        blob = ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        )
        self.writes.append(
            (
                credential.TargetName,
                credential.Type,
                credential.Persist,
                blob,
            )
        )

    def delete(self, target: str) -> None:
        self.delete_calls.append(target)
        if self.delete_error is not None:
            raise self.delete_error

    def free(self, credential: Any) -> None:
        self.freed.append(credential)


def _credential_with_blob(blob: bytes) -> tuple[Any, Any]:
    buffer = ctypes.create_string_buffer(blob)
    credential = CREDENTIALW()
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, type(credential.CredentialBlob))
    return ctypes.pointer(credential), buffer


def test_target_name_is_deterministic_and_namespaced() -> None:
    ref = SecretRef("provider/openai/api-key")

    assert (
        WindowsCredentialStore._target_name(ref)
        == "SofiasAssistant/v1/70726f76696465722f6f70656e61692f6170692d6b6579"
    )


def test_target_name_uses_utf8_hex_encoding() -> None:
    target_name = WindowsCredentialStore._target_name(
        SecretRef("caf\u00e9/\u4e16\u754c")
    )

    assert target_name == "SofiasAssistant/v1/636166c3a92fe4b896e7958c"


def test_target_names_preserve_case_sensitive_secret_ref_identity() -> None:
    upper_case = WindowsCredentialStore._target_name(
        SecretRef("provider/OpenAI/api-key")
    )
    lower_case = WindowsCredentialStore._target_name(
        SecretRef("provider/openai/api-key")
    )

    assert (
        upper_case
        == "SofiasAssistant/v1/70726f76696465722f4f70656e41492f6170692d6b6579"
    )
    assert (
        lower_case
        == "SofiasAssistant/v1/70726f76696465722f6f70656e61692f6170692d6b6579"
    )
    assert upper_case != lower_case


def test_target_name_within_win32_limit_is_accepted() -> None:
    maximum_identifier = "a" * (
        (CRED_MAX_GENERIC_TARGET_NAME_LENGTH - len("SofiasAssistant/v1/")) // 2
    )

    target_name = WindowsCredentialStore._target_name(SecretRef(maximum_identifier))

    assert len(target_name) == CRED_MAX_GENERIC_TARGET_NAME_LENGTH


def test_oversized_target_name_is_rejected_before_a_win32_call() -> None:
    api = FakeCredentialApi()
    store = WindowsCredentialStore(api)
    oversized_identifier = "a" * (
        (CRED_MAX_GENERIC_TARGET_NAME_LENGTH - len("SofiasAssistant/v1/")) // 2 + 1
    )
    value = SecretValue("super-secret-test-value")

    with pytest.raises(ValueError) as error:
        store.set(SecretRef(oversized_identifier), value)

    assert value.reveal() not in str(error.value)
    assert api.writes == []


def test_set_uses_utf8_generic_local_machine_credential() -> None:
    api = FakeCredentialApi()
    store = WindowsCredentialStore(api)
    value = SecretValue("ol\u00e1 \u4e16\u754c")

    store.set(SecretRef("unicode"), value)

    assert api.writes == [
        (
            "SofiasAssistant/v1/756e69636f6465",
            CRED_TYPE_GENERIC,
            CRED_PERSIST_LOCAL_MACHINE,
            value.reveal().encode("utf-8"),
        )
    ]


def test_get_decodes_utf8_to_a_secret_value() -> None:
    api = FakeCredentialApi()
    value = "ol\u00e1 \u4e16\u754c"
    credential, buffer = _credential_with_blob(value.encode())
    api.read_credential = credential
    store = WindowsCredentialStore(api)

    result = store.get(SecretRef("unicode"))

    assert buffer.raw.startswith(value.encode())
    assert result is not None
    assert result.reveal() == value
    assert api.freed == [credential]


def test_oversized_utf8_value_is_rejected_before_write_without_disclosure() -> None:
    api = FakeCredentialApi()
    store = WindowsCredentialStore(api)
    value = SecretValue("\u00e9" * (CRED_MAX_CREDENTIAL_BLOB_SIZE // 2 + 1))

    with pytest.raises(ValueError) as error:
        store.set(SecretRef("large"), value)

    assert value.reveal() not in str(error.value)
    assert api.writes == []


def test_missing_get_and_delete_are_not_errors() -> None:
    api = FakeCredentialApi()
    api.read_error = _win_error(ERROR_NOT_FOUND)
    api.delete_error = _win_error(ERROR_NOT_FOUND)
    store = WindowsCredentialStore(api)

    assert store.get(SecretRef("missing")) is None
    assert store.delete(SecretRef("missing")) is False


@pytest.mark.parametrize("operation", ["get", "delete"])
def test_unexpected_win32_errors_are_not_silenced(operation: str) -> None:
    api = FakeCredentialApi()
    error = _win_error(5)
    if operation == "get":
        api.read_error = error
    else:
        api.delete_error = error
    store = WindowsCredentialStore(api)

    with pytest.raises(OSError) as raised:
        if operation == "get":
            store.get(SecretRef("access-denied"))
        else:
            store.delete(SecretRef("access-denied"))

    assert raised.value is error


def test_get_frees_windows_buffer_when_utf8_decode_fails() -> None:
    api = FakeCredentialApi()
    credential, buffer = _credential_with_blob(b"\xff")
    api.read_credential = credential
    store = WindowsCredentialStore(api)

    with pytest.raises(UnicodeDecodeError):
        store.get(SecretRef("invalid-utf8"))

    assert buffer.raw.startswith(b"\xff")
    assert api.freed == [credential]


def test_write_errors_do_not_disclose_secret_value() -> None:
    api = FakeCredentialApi()
    original_error = _win_error(5)
    api.write_error = original_error
    store = WindowsCredentialStore(api)
    value = SecretValue("super-secret-test-value")

    with pytest.raises(OSError) as error:
        store.set(SecretRef("provider/test"), value)

    assert error.value is original_error
    assert value.reveal() not in str(error.value)
    assert value.reveal() not in repr(error.value)
