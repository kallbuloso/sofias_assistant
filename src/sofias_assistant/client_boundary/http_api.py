"""In-process ASGI contract for the future loopback local client boundary."""

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel

from sofias_assistant.client_boundary.auth import LocalClientAuthenticator
from sofias_assistant.client_boundary.sessions import (
    ClientSession,
    ClientSessionRegistry,
)
from sofias_assistant.core.core import CoreState
from sofias_assistant.health.models import (
    ComponentHealth,
    HealthStatus,
    RuntimeHealthSnapshot,
)
from sofias_assistant.secrets.models import SecretValue

_AUTHENTICATION_FAILURE_DETAIL = "Local client authentication failed"


class ClientSessionResponse(BaseModel):
    """HTTP representation of a local client session without credentials."""

    id: UUID
    created_at: datetime

    @classmethod
    def from_session(cls, session: ClientSession) -> "ClientSessionResponse":
        """Create the transport representation for a runtime session."""

        return cls(id=session.id, created_at=session.created_at)


class CoreReadApi(Protocol):
    """Minimal read-only Core contract exposed by the local HTTP adapter."""

    @property
    def state(self) -> CoreState: ...

    @property
    def runtime_session_id(self) -> UUID | None: ...

    @property
    def health(self) -> RuntimeHealthSnapshot: ...


class ComponentHealthResponse(BaseModel):
    """Transport-only representation of one Core health component."""

    name: str
    status: HealthStatus
    detail: str | None

    @classmethod
    def from_component(cls, component: ComponentHealth) -> "ComponentHealthResponse":
        """Create the transport representation while preserving component fields."""

        return cls(
            name=component.name,
            status=component.status,
            detail=component.detail,
        )


class RuntimeHealthResponse(BaseModel):
    """Transport-only representation of the ordered Core health snapshot."""

    status: HealthStatus
    components: list[ComponentHealthResponse]

    @classmethod
    def from_snapshot(cls, snapshot: RuntimeHealthSnapshot) -> "RuntimeHealthResponse":
        """Create an ordered transport health response from the Core snapshot."""

        return cls(
            status=snapshot.status,
            components=[
                ComponentHealthResponse.from_component(component)
                for component in snapshot.components
            ],
        )


class CoreResponse(BaseModel):
    """Transport-safe read-only snapshot of the Core runtime."""

    state: CoreState
    runtime_session_id: UUID | None
    health: RuntimeHealthResponse

    @classmethod
    def from_core(cls, core: CoreReadApi) -> "CoreResponse":
        """Create a response without exposing Core resources or configuration."""

        return cls(
            state=core.state,
            runtime_session_id=core.runtime_session_id,
            health=RuntimeHealthResponse.from_snapshot(core.health),
        )


def create_local_http_app(
    authenticator: LocalClientAuthenticator,
    sessions: ClientSessionRegistry,
    *,
    core: CoreReadApi | None = None,
) -> FastAPI:
    """Create an unbound ASGI app for one explicitly composed local boundary."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def require_bearer(
        authorization: Annotated[str | None, Header()] = None,
    ) -> SecretValue:
        credential = _credential_from_authorization(authorization)
        if credential is None or not authenticator.authenticate(credential):
            raise _authentication_failure()
        return credential

    async def require_session(
        _: Annotated[SecretValue, Depends(require_bearer)],
        session_id: Annotated[
            str | None, Header(alias="X-Sofia-Client-Session-ID")
        ] = None,
    ) -> ClientSession:
        if session_id is None:
            raise _authentication_failure()
        try:
            parsed_session_id = UUID(session_id)
        except ValueError:
            raise _authentication_failure() from None

        session = sessions.get(parsed_session_id)
        if session is None:
            raise _authentication_failure()
        return session

    @app.post(
        "/api/v1/client-sessions",
        response_model=ClientSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def open_session(
        credential: Annotated[SecretValue, Depends(require_bearer)],
    ) -> ClientSessionResponse:
        """Open a runtime session after authenticating the bearer credential."""

        return ClientSessionResponse.from_session(sessions.open_session(credential))

    @app.get("/api/v1/client-session", response_model=ClientSessionResponse)
    async def get_current_session(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> ClientSessionResponse:
        """Return the session associated with both required authentication headers."""

        return ClientSessionResponse.from_session(session)

    @app.delete("/api/v1/client-session", status_code=status.HTTP_204_NO_CONTENT)
    async def close_current_session(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> Response:
        """Close only the session associated with the authenticated request."""

        sessions.close_session(session.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if core is not None:

        @app.get("/api/v1/core", response_model=CoreResponse)
        async def get_core(
            _: Annotated[ClientSession, Depends(require_session)],
        ) -> CoreResponse:
            """Return the authenticated, transport-safe Core runtime snapshot."""

            return CoreResponse.from_core(core)

    return app


def _credential_from_authorization(authorization: str | None) -> SecretValue | None:
    if authorization is None:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if scheme != "Bearer" or not separator or not credential.strip():
        return None
    if credential != credential.strip() or " " in credential:
        return None
    return SecretValue(credential)


def _authentication_failure() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTHENTICATION_FAILURE_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )
