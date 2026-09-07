"""Unit tests for transport-neutral local client authentication and sessions."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from sofias_assistant.client_boundary import (
    ClientAuthenticationError,
    ClientSession,
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.secrets.models import SecretValue


def test_create_generates_a_redacted_non_empty_secret_value() -> None:
    authenticator, credential = LocalClientAuthenticator.create()

    assert isinstance(credential, SecretValue)
    assert credential.reveal()
    assert credential.reveal() not in str(credential)
    assert credential.reveal() not in repr(credential)
    assert credential.reveal() not in repr(authenticator)


def test_authenticate_accepts_the_issued_credential() -> None:
    authenticator, credential = LocalClientAuthenticator.create()

    assert authenticator.authenticate(credential) is True


def test_authenticate_rejects_another_credential() -> None:
    authenticator, _ = LocalClientAuthenticator.create()

    assert authenticator.authenticate(SecretValue("other-client-credential")) is False


def test_authenticator_does_not_expose_its_plaintext_credential() -> None:
    authenticator, credential = LocalClientAuthenticator.create()

    assert not hasattr(authenticator, "credential")
    assert credential.reveal() not in str(authenticator)
    assert credential.reveal() not in repr(authenticator)


def test_invalid_credential_error_and_reprs_redact_the_candidate() -> None:
    authenticator, _ = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(authenticator)
    candidate = SecretValue("client-super-secret-sentinel")

    with pytest.raises(ClientAuthenticationError) as raised:
        registry.open_session(candidate)

    assert candidate.reveal() not in str(raised.value)
    assert candidate.reveal() not in repr(raised.value)
    assert candidate.reveal() not in repr(authenticator)
    assert candidate.reveal() not in repr(registry)


def test_open_session_returns_stored_utc_session() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(authenticator)

    session = registry.open_session(credential)

    assert isinstance(session.id, UUID)
    assert session.created_at.tzinfo is UTC
    assert registry.get(session.id) == session


def test_client_session_direct_utc_construction_is_valid() -> None:
    created_at = datetime(2026, 9, 1, 13, 30, tzinfo=UTC)

    session = ClientSession(id=uuid4(), created_at=created_at)

    assert session.created_at == created_at
    assert session.created_at.tzinfo is UTC


def test_client_session_direct_non_utc_construction_is_normalized() -> None:
    session = ClientSession(
        id=uuid4(),
        created_at=datetime(2026, 9, 1, 10, 30, tzinfo=timezone(-timedelta(hours=3))),
    )

    assert session.created_at == datetime(2026, 9, 1, 13, 30, tzinfo=UTC)
    assert session.created_at.tzinfo is UTC


def test_client_session_direct_naive_construction_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ClientSession(id=uuid4(), created_at=datetime(2026, 9, 1, 10, 30))


def test_invalid_credential_does_not_create_a_session() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(authenticator)
    unknown_id = uuid4()

    with pytest.raises(ClientAuthenticationError):
        registry.open_session(SecretValue("client-super-secret-sentinel"))

    assert registry.get(unknown_id) is None
    assert registry.open_session(credential).id != unknown_id


def test_non_utc_clock_is_normalized_to_utc() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    local_time = datetime(2026, 9, 1, 10, 30, tzinfo=timezone(-timedelta(hours=3)))
    registry = ClientSessionRegistry(authenticator, clock=lambda: local_time)

    session = registry.open_session(credential)

    assert session.created_at == datetime(2026, 9, 1, 13, 30, tzinfo=UTC)


def test_naive_clock_is_rejected_without_creating_session() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(
        authenticator, clock=lambda: datetime(2026, 9, 1, 10, 30)
    )
    unknown_id = uuid4()

    with pytest.raises(ValueError, match="timezone-aware"):
        registry.open_session(credential)

    assert registry.get(unknown_id) is None


def test_close_existing_session_removes_it() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(authenticator)
    session = registry.open_session(credential)

    assert registry.close_session(session.id) is True
    assert registry.get(session.id) is None


def test_close_missing_session_returns_false() -> None:
    authenticator, _ = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(authenticator)

    assert registry.close_session(uuid4()) is False


def test_close_all_revokes_every_open_session() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    registry = ClientSessionRegistry(authenticator)
    first = registry.open_session(credential)
    second = registry.open_session(credential)

    registry.close_all()

    assert registry.get(first.id) is None
    assert registry.get(second.id) is None


def test_client_session_is_immutable() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    session = ClientSessionRegistry(authenticator).open_session(credential)

    with pytest.raises(AttributeError):
        session.id = uuid4()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        session.created_at = datetime.now(UTC)  # type: ignore[misc]


def test_registries_do_not_share_credentials_or_sessions() -> None:
    authenticator_a, credential_a = LocalClientAuthenticator.create()
    authenticator_b, credential_b = LocalClientAuthenticator.create()
    registry_a = ClientSessionRegistry(authenticator_a)
    registry_b = ClientSessionRegistry(authenticator_b)
    session_a = registry_a.open_session(credential_a)

    assert authenticator_b.authenticate(credential_a) is False
    with pytest.raises(ClientAuthenticationError):
        registry_b.open_session(credential_a)
    session_b = registry_b.open_session(credential_b)

    assert registry_a.get(session_b.id) is None
    assert registry_b.get(session_a.id) is None


def test_package_import_creates_no_global_runtime_state() -> None:
    import sofias_assistant.client_boundary as client_boundary

    assert client_boundary.LocalClientAuthenticator is LocalClientAuthenticator
