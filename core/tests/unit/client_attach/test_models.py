"""Unit tests for `ClientAttachRecord` validation, redaction and round-trip."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sofias_assistant.client_attach.models import (
    CONTRACT_VERSION,
    ClientAttachRecord,
    InvalidAttachRecordError,
)
from sofias_assistant.secrets.models import SecretValue


def _record(**overrides: object) -> ClientAttachRecord:
    defaults: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "instance_key": "a" * 64,
        "runtime_session_id": uuid4(),
        "host": "127.0.0.1",
        "port": 8989,
        "credential": SecretValue("super-secret-attach-credential"),
        "application_version": "0.1.0",
        "process_id": 4242,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return ClientAttachRecord(**defaults)  # type: ignore[arg-type]


def test_repr_never_contains_the_credential() -> None:
    record = _record()

    assert "super-secret-attach-credential" not in repr(record)
    assert "redacted" in repr(record).lower() or "credential" not in repr(record)


def test_str_of_credential_field_is_redacted() -> None:
    record = _record()

    assert str(record.credential) == "<SecretValue redacted>"


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "example.com"])
def test_non_loopback_host_is_rejected(host: str) -> None:
    with pytest.raises(InvalidAttachRecordError):
        _record(host=host)


@pytest.mark.parametrize("port", [0, -1, 65536, 100_000])
def test_out_of_range_port_is_rejected(port: int) -> None:
    with pytest.raises(InvalidAttachRecordError):
        _record(port=port)


def test_blank_instance_key_is_rejected() -> None:
    with pytest.raises(InvalidAttachRecordError):
        _record(instance_key="   ")


def test_naive_created_at_is_rejected() -> None:
    with pytest.raises(InvalidAttachRecordError):
        _record(created_at=datetime.now())  # noqa: DTZ005


def test_unsupported_contract_version_is_rejected() -> None:
    with pytest.raises(InvalidAttachRecordError):
        _record(contract_version=CONTRACT_VERSION + 1)


def test_json_round_trip_preserves_every_field() -> None:
    record = _record()

    restored = ClientAttachRecord.from_json(record.to_json())

    assert restored.contract_version == record.contract_version
    assert restored.instance_key == record.instance_key
    assert restored.runtime_session_id == record.runtime_session_id
    assert restored.host == record.host
    assert restored.port == record.port
    assert restored.credential.reveal() == record.credential.reveal()
    assert restored.application_version == record.application_version
    assert restored.process_id == record.process_id
    assert restored.created_at == record.created_at


def test_json_blob_stays_well_under_the_windows_credential_blob_limit() -> None:
    record = _record()

    # CRED_MAX_CREDENTIAL_BLOB_SIZE is 2560 bytes (5*512); a compact bounded
    # record must comfortably fit even with a generous credential token.
    assert len(record.to_json().encode("utf-8")) < 1024


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "42",
        "null",
        "{}",
        '{"contract_version": 1}',
        '{"contract_version": 1, "instance_key": "a", "runtime_session_id": "not-a-uuid", '
        '"host": "127.0.0.1", "port": 8989, "credential": "x", '
        '"application_version": "0.1.0", "created_at": "2026-01-01T00:00:00+00:00"}',
    ],
)
def test_from_json_rejects_malformed_payloads(raw: str) -> None:
    with pytest.raises(InvalidAttachRecordError):
        ClientAttachRecord.from_json(raw)
