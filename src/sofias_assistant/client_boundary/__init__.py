"""Transport-neutral authentication and sessions for trusted local clients."""

from sofias_assistant.client_boundary.auth import (
    ClientAuthenticationError,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.sessions import (
    ClientSession,
    ClientSessionRegistry,
)

__all__ = [
    "ClientAuthenticationError",
    "ClientSession",
    "ClientSessionRegistry",
    "LocalClientAuthenticator",
]
