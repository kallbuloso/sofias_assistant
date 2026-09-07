"""Value objects for Secret Service contracts."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Opaque stable identifier for a secret."""

    identifier: str

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("SecretRef identifier must not be blank")


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Secret text that requires explicit reveal for access."""

    _value: str = field(repr=False)

    def __str__(self) -> str:
        return "<SecretValue redacted>"

    def reveal(self) -> str:
        """Return the secret value intentionally."""
        return self._value
