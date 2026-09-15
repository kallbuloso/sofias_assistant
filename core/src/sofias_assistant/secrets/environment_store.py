"""Environment-backed and layered SecretStore implementations.

Amendment 0003 / Runtime Configuration Contract v1 allow deployment secrets
to arrive through the process environment or an explicitly selected env
file, but the `SecretService` boundary and its non-enumerating contract
never change: only explicitly known `SecretRef` mappings are ever bridged,
and nothing here ever scans the environment for arbitrary variable names.
"""

from collections.abc import Mapping

from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.store import SecretStore


class EnvironmentSecretStore:
    """Read-only SecretStore resolved once from an explicit variable mapping.

    `environment` is expected to already reflect the caller's precedence
    between the real process environment and an explicitly selected env
    file (see `sofias_assistant.config.loader.resolve_environment`), so a
    single lookup here already respects that ordering. Blank values are
    treated as absent, matching the Contract's "missing" secret state.
    """

    def __init__(
        self,
        environment: Mapping[str, str],
        mappings: Mapping[str, SecretRef],
    ) -> None:
        self._values: dict[SecretRef, SecretValue] = {}
        for variable_name, ref in mappings.items():
            raw = environment.get(variable_name)
            if raw:
                self._values[ref] = SecretValue(raw)

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        raise RuntimeError(
            "Environment-backed secrets are read-only; store durable secrets "
            "through the platform SecretStore instead"
        )

    def delete(self, ref: SecretRef) -> bool:
        raise RuntimeError(
            "Environment-backed secrets are read-only; delete durable secrets "
            "through the platform SecretStore instead"
        )


class LayeredSecretStore:
    """Deterministic precedence: `primary` (environment-backed), then `fallback`.

    Writes always target the durable `fallback` store: environment-backed
    values are process-scoped by design and are never meant to be persisted
    back into it (Amendment 0003 SS5).
    """

    def __init__(self, primary: SecretStore, fallback: SecretStore) -> None:
        self._primary = primary
        self._fallback = fallback

    def get(self, ref: SecretRef) -> SecretValue | None:
        value = self._primary.get(ref)
        if value is not None:
            return value
        return self._fallback.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._fallback.set(ref, value)

    def delete(self, ref: SecretRef) -> bool:
        return self._fallback.delete(ref)
