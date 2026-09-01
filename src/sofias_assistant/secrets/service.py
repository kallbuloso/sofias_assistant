"""Core-wide Secret Service boundary."""

from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.store import SecretStore


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
