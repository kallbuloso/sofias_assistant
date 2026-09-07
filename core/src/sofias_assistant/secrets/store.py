"""Storage contract for the Secret Service."""

from typing import Protocol

from sofias_assistant.secrets.models import SecretRef, SecretValue


class SecretStore(Protocol):
    """Minimal non-enumerating secret backend contract."""

    def get(self, ref: SecretRef) -> SecretValue | None: ...

    def set(self, ref: SecretRef, value: SecretValue) -> None: ...

    def delete(self, ref: SecretRef) -> bool: ...
