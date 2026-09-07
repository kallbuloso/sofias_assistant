"""Core-independent composition and lifecycle for the local client boundary."""

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import FastAPI

from sofias_assistant.client_boundary.auth import LocalClientAuthenticator
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.client_boundary.server import (
    DEFAULT_LOCAL_API_PORT,
    LocalHttpServer,
)
from sofias_assistant.client_boundary.sessions import ClientSessionRegistry
from sofias_assistant.secrets.models import SecretValue


@dataclass(frozen=True, slots=True)
class LocalClientAccess:
    """Ephemeral delivery data for a trusted local client process."""

    host: str
    port: int
    credential: SecretValue = field(repr=False)


class LocalClientBoundary:
    """Compose and own one ephemeral authenticator, registry, app, and server."""

    def __init__(
        self,
        *,
        port: int = DEFAULT_LOCAL_API_PORT,
        app_factory: Callable[
            [LocalClientAuthenticator, ClientSessionRegistry], FastAPI
        ] = create_local_http_app,
    ) -> None:
        self._port = port
        self._app_factory = app_factory
        self._server: LocalHttpServer | None = None
        self._sessions: ClientSessionRegistry | None = None
        self._started = False
        self._start_attempted = False

    async def start(self) -> LocalClientAccess:
        """Start the local boundary and return its caller-owned access credential."""

        if self._start_attempted:
            raise RuntimeError("LocalClientBoundary can only be started once")
        self._start_attempted = True

        authenticator, credential = LocalClientAuthenticator.create()
        sessions = ClientSessionRegistry(authenticator)
        self._sessions = sessions
        server: LocalHttpServer | None = None
        try:
            server = LocalHttpServer(
                self._app_factory(authenticator, sessions), port=self._port
            )
            self._server = server
            await server.start()
            bound_port = server.bound_port
            if bound_port is None:
                raise RuntimeError("LocalHttpServer did not expose a bound port")
            self._started = True
            return LocalClientAccess(
                host=server.host,
                port=bound_port,
                credential=credential,
            )
        except BaseException:
            if server is not None and server.bound_port is not None:
                try:
                    await server.stop()
                except BaseException:
                    pass
            sessions.close_all()
            self._clear_references()
            raise

    async def stop(self) -> None:
        """Stop serving first, then revoke all runtime-only client sessions."""

        if not self._started:
            raise RuntimeError(
                "LocalClientBoundary can only stop after a successful start"
            )

        server = self._server
        sessions = self._sessions
        if server is None or sessions is None:
            self._clear_references()
            raise RuntimeError("LocalClientBoundary is missing active resources")

        try:
            await server.stop()
        finally:
            sessions.close_all()
            self._clear_references()

    def _clear_references(self) -> None:
        self._server = None
        self._sessions = None
        self._started = False
