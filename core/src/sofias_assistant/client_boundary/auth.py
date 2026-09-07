"""Runtime-scoped credential authentication for future local transports."""

import hashlib
import hmac
import secrets
from typing import Self

from sofias_assistant.secrets.models import SecretValue


class ClientAuthenticationError(RuntimeError):
    """Raised when a local client credential cannot be authenticated."""

    def __init__(self) -> None:
        super().__init__("Local client authentication failed")


class LocalClientAuthenticator:
    """Authenticate one ephemeral credential without retaining its plaintext."""

    __slots__ = ("_credential_digest",)

    def __init__(self, credential_digest: bytes) -> None:
        self._credential_digest = credential_digest

    def __repr__(self) -> str:
        return "<LocalClientAuthenticator credential=redacted>"

    @classmethod
    def create(cls) -> tuple[Self, SecretValue]:
        """Create an authenticator and a 256-bit runtime-scoped credential."""

        credential = SecretValue(secrets.token_urlsafe(32))
        return cls(cls._digest(credential)), credential

    def authenticate(self, candidate: SecretValue) -> bool:
        """Return whether the supplied secret value matches this runtime credential."""

        return hmac.compare_digest(self._credential_digest, self._digest(candidate))

    @staticmethod
    def _digest(credential: SecretValue) -> bytes:
        return hashlib.sha256(credential.reveal().encode("utf-8")).digest()
