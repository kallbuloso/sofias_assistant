"""Storage contract for the Secret Service."""

from typing import Literal, Protocol, runtime_checkable

from sofias_assistant.secrets.models import SecretRef, SecretValue

SecretSource = Literal["environment", "platform_store", "missing"]


class SecretStore(Protocol):
    """Minimal non-enumerating secret backend contract."""

    def get(self, ref: SecretRef) -> SecretValue | None: ...

    def set(self, ref: SecretRef, value: SecretValue) -> None: ...

    def delete(self, ref: SecretRef) -> bool: ...


@runtime_checkable
class SecretSourceAwareStore(Protocol):
    """Optional extension for stores that can report safe source provenance.

    Only `LayeredSecretStore` (Amendment 0003/0004) implements this today.
    Plain single-layer stores (used directly in tests/CLI) do not, and
    `SecretService.describe` falls back to a two-state configured/missing
    diagnostic for those. Never reveals the secret value.
    """

    def describe(self, ref: SecretRef) -> SecretSource: ...
