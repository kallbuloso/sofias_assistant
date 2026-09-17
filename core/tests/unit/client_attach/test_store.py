"""Unit tests for `InMemoryClientAttachStore` publish/read/delete_if_current."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sofias_assistant.client_attach.models import CONTRACT_VERSION, ClientAttachRecord
from sofias_assistant.client_attach.store import InMemoryClientAttachStore
from sofias_assistant.secrets.models import SecretValue


def _record(
    instance_key: str, runtime_session_id: UUID | None = None
) -> ClientAttachRecord:
    return ClientAttachRecord(
        contract_version=CONTRACT_VERSION,
        instance_key=instance_key,
        runtime_session_id=runtime_session_id or uuid4(),
        host="127.0.0.1",
        port=8989,
        credential=SecretValue("token"),
        application_version="0.1.0",
        created_at=datetime.now(UTC),
    )


def test_read_returns_none_when_absent() -> None:
    store = InMemoryClientAttachStore()

    assert store.read("missing-instance") is None


def test_publish_then_read_round_trips() -> None:
    store = InMemoryClientAttachStore()
    record = _record("instance-a")

    store.publish("instance-a", record)

    assert store.read("instance-a") == record


def test_publish_replaces_the_previous_record_for_the_same_instance() -> None:
    store = InMemoryClientAttachStore()
    first = _record("instance-a")
    second = _record("instance-a")

    store.publish("instance-a", first)
    store.publish("instance-a", second)

    assert store.read("instance-a") == second


def test_delete_if_current_with_old_lifecycle_fails() -> None:
    store = InMemoryClientAttachStore()
    old_session = uuid4()
    new_session = uuid4()
    store.publish("instance-a", _record("instance-a", new_session))

    deleted = store.delete_if_current("instance-a", old_session)

    assert deleted is False
    assert store.read("instance-a") is not None


def test_delete_if_current_with_current_lifecycle_succeeds() -> None:
    store = InMemoryClientAttachStore()
    session_id = uuid4()
    store.publish("instance-a", _record("instance-a", session_id))

    deleted = store.delete_if_current("instance-a", session_id)

    assert deleted is True
    assert store.read("instance-a") is None


def test_delete_if_current_on_missing_instance_returns_false() -> None:
    store = InMemoryClientAttachStore()

    assert store.delete_if_current("never-published", uuid4()) is False


def test_different_instances_do_not_interfere() -> None:
    store = InMemoryClientAttachStore()
    store.publish("instance-a", _record("instance-a"))

    assert store.read("instance-b") is None
