"""Core-wide Secret Service boundary."""

from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.store import (
    SecretSource,
    SecretSourceAwareStore,
    SecretStore,
)


class SecretService:
    """Controlled secret access through an explicitly injected store."""

    def __init__(self, store: SecretStore) -> None:
        self._store = store

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._store.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._store.set(ref, value)

    def delete(self, ref: SecretRef) -> bool:
        return self._store.delete(ref)

    def describe(self, ref: SecretRef) -> SecretSource:
        """Safe, value-free provenance: environment|platform_store|missing.

        Delegates to the injected store's `describe` when it reports layered
        source provenance (`LayeredSecretStore`); otherwise falls back to a
        two-state `platform_store`/`missing` diagnostic. Never reveals the
        secret value.
        """

        if isinstance(self._store, SecretSourceAwareStore):
            return self._store.describe(ref)
        return "platform_store" if self._store.get(ref) is not None else "missing"
