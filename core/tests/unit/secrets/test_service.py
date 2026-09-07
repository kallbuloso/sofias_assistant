"""Unit tests for Secret Service contracts."""

import pytest

from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService


class InMemorySecretStore:
    """Test-only fake store; it is not a secure backend."""

    def __init__(self) -> None:
        self.values: dict[SecretRef, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self.values.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self.values[ref] = value

    def delete(self, ref: SecretRef) -> bool:
        return self.values.pop(ref, None) is not None


def test_secret_ref_validates_identifier() -> None:
    assert SecretRef("provider/test") == SecretRef("provider/test")
    with pytest.raises(ValueError):
        SecretRef("")
    with pytest.raises(ValueError):
        SecretRef("   ")


def test_secret_value_redacts_accidental_representation() -> None:
    value = SecretValue("super-secret-test-value")
    assert "super-secret-test-value" not in repr(value)
    assert "super-secret-test-value" not in str(value)
    assert value.reveal() == "super-secret-test-value"


def test_service_uses_injected_store_for_set_get_delete_and_missing() -> None:
    store = InMemorySecretStore()
    service = SecretService(store)
    ref = SecretRef("provider/test")
    value = SecretValue("super-secret-test-value")

    assert service.get(ref) is None
    service.set(ref, value)
    assert service.get(ref) is value
    assert service.delete(ref) is True
    assert service.get(ref) is None
    assert service.delete(ref) is False
