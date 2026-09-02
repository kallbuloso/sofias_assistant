"""In-memory authenticated session registry for future local transports."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sofias_assistant.client_boundary.auth import (
    ClientAuthenticationError,
    LocalClientAuthenticator,
)
from sofias_assistant.secrets.models import SecretValue


@dataclass(frozen=True, slots=True)
class ClientSession:
    """Runtime-only session identity; it is not an authentication credential."""

    id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("ClientSession created_at must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


class ClientSessionRegistry:
    """Own in-memory sessions authenticated by one local runtime credential."""

    def __init__(
        self,
        authenticator: LocalClientAuthenticator,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._authenticator = authenticator
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._sessions: dict[UUID, ClientSession] = {}

    def __repr__(self) -> str:
        return "<ClientSessionRegistry sessions=redacted>"

    def open_session(self, credential: SecretValue) -> ClientSession:
        """Authenticate a credential and create a session for this runtime only."""

        if not self._authenticator.authenticate(credential):
            raise ClientAuthenticationError()

        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError(
                "Client session clock must return a timezone-aware datetime"
            )

        session = ClientSession(id=uuid4(), created_at=created_at.astimezone(UTC))
        self._sessions[session.id] = session
        return session

    def get(self, session_id: UUID) -> ClientSession | None:
        """Return a currently open session by its non-secret identity."""

        return self._sessions.get(session_id)

    def close_session(self, session_id: UUID) -> bool:
        """Revoke a session, reporting whether it was present."""

        return self._sessions.pop(session_id, None) is not None

    def close_all(self) -> None:
        """Revoke all sessions belonging to this runtime registry."""

        self._sessions.clear()
