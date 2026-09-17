"""Unit tests for `WindowsClientAttachStore` translation logic (fake Win32 API)."""

import ctypes
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from sofias_assistant.client_attach.models import CONTRACT_VERSION, ClientAttachRecord
from sofias_assistant.client_attach.windows_store import (
    TARGET_PREFIX,
    WindowsClientAttachStore,
)
from sofias_assistant.secrets._wincred import CREDENTIALW, ERROR_NOT_FOUND
from sofias_assistant.secrets.models import SecretValue


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
        self.writes: list[tuple[str, bytes]] = []

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
        self.writes.append((credential.TargetName, blob))
        # Reflect the write so a subsequent read() in the same test observes it.
        self.read_credential = _credential_with_blob(blob)[0]

    def delete(self, target: str) -> None:
        self.delete_calls.append(target)
        if self.delete_error is not None:
            raise self.delete_error
        self.read_credential = None

    def free(self, credential: Any) -> None:
        self.freed.append(credential)


def _credential_with_blob(blob: bytes) -> tuple[Any, Any]:
    buffer = ctypes.create_string_buffer(blob)
    credential = CREDENTIALW()
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, type(credential.CredentialBlob))
    return ctypes.pointer(credential), buffer


def _record(runtime_session_id: UUID | None = None) -> ClientAttachRecord:
    return ClientAttachRecord(
        contract_version=CONTRACT_VERSION,
        instance_key="b" * 64,
        runtime_session_id=runtime_session_id or uuid4(),
        host="127.0.0.1",
        port=8989,
        credential=SecretValue("super-secret-attach-token"),
        application_version="0.1.0",
        created_at=datetime.now(UTC),
    )


def test_publish_writes_the_serialized_record_under_the_attach_namespace() -> None:
    api = FakeCredentialApi()
    store = WindowsClientAttachStore(api)
    record = _record()

    store.publish("b" * 64, record)

    assert len(api.writes) == 1
    target_name, blob = api.writes[0]
    assert target_name == f"{TARGET_PREFIX}{'b' * 64}"
    assert blob == record.to_json().encode("utf-8")


def test_publish_never_discloses_the_credential_in_a_raised_error() -> None:
    api = FakeCredentialApi()
    api.write_error = _win_error(5)
    store = WindowsClientAttachStore(api)
    record = _record()

    with pytest.raises(OSError) as error:
        store.publish("b" * 64, record)

    assert record.credential.reveal() not in str(error.value)


def test_publish_then_read_round_trips_through_the_fake_store() -> None:
    api = FakeCredentialApi()
    store = WindowsClientAttachStore(api)
    record = _record()

    store.publish("b" * 64, record)
    restored = store.read("b" * 64)

    assert restored is not None
    assert restored.runtime_session_id == record.runtime_session_id
    assert restored.credential.reveal() == record.credential.reveal()
    assert api.freed  # CredFree was called on the read handle


def test_read_returns_none_when_not_found() -> None:
    api = FakeCredentialApi()
    api.read_error = _win_error(ERROR_NOT_FOUND)
    store = WindowsClientAttachStore(api)

    assert store.read("missing") is None


def test_read_returns_none_for_malformed_stored_payload() -> None:
    api = FakeCredentialApi()
    credential, _buffer = _credential_with_blob(b"not-json-at-all")
    api.read_credential = credential
    store = WindowsClientAttachStore(api)

    assert store.read("b" * 64) is None
    assert api.freed == [credential]


def test_unexpected_read_error_is_not_silenced() -> None:
    api = FakeCredentialApi()
    error = _win_error(5)
    api.read_error = error
    store = WindowsClientAttachStore(api)

    with pytest.raises(OSError) as raised:
        store.read("b" * 64)

    assert raised.value is error


def test_delete_if_current_with_matching_lifecycle_deletes() -> None:
    api = FakeCredentialApi()
    store = WindowsClientAttachStore(api)
    session_id = uuid4()
    record = _record(session_id)
    store.publish("b" * 64, record)

    deleted = store.delete_if_current("b" * 64, session_id)

    assert deleted is True
    assert api.delete_calls == [f"{TARGET_PREFIX}{'b' * 64}"]


def test_delete_if_current_with_stale_lifecycle_does_not_delete() -> None:
    api = FakeCredentialApi()
    store = WindowsClientAttachStore(api)
    record = _record(uuid4())
    store.publish("b" * 64, record)

    deleted = store.delete_if_current("b" * 64, uuid4())

    assert deleted is False
    assert api.delete_calls == []


def test_delete_if_current_on_absent_record_returns_false() -> None:
    api = FakeCredentialApi()
    api.read_error = _win_error(ERROR_NOT_FOUND)
    store = WindowsClientAttachStore(api)

    assert store.delete_if_current("b" * 64, uuid4()) is False
    assert api.delete_calls == []
