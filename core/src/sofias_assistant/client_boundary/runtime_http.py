"""Authenticated runtime identity and graceful shutdown routes.

Desktop/Core Interaction Contract v1 SS14 (`GET /api/v1/runtime/identity`)
and SS23 (`POST /api/v1/runtime/shutdown`). Both routes reuse the existing
authenticated session dependency; this Contract introduces no new
unauthenticated local control surface. Neither route returns the bearer
credential, a provider secret or any internal repository/storage handle.
"""

from collections.abc import Callable
from typing import Annotated, Any, Protocol
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from sofias_assistant.client_boundary.sessions import ClientSession
from sofias_assistant.execution.audit import AuditService
from sofias_assistant.runtime.shutdown import RuntimeShutdownSignal

PROTOCOL_VERSION = 1


class RuntimeIdentityResponse(BaseModel):
    """Safe authenticated identity surface for Desktop attach verification."""

    instance_key: str
    runtime_session_id: UUID | None
    application_version: str
    protocol_version: int
    state: str


class RuntimeShutdownRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_session_id: UUID
    reason: str = Field(default="user_requested", min_length=1)


class RuntimeShutdownResponse(BaseModel):
    accepted: bool


class RuntimeCoreApi(Protocol):
    """Minimal read-only Core contract used by the runtime identity route."""

    @property
    def runtime_session_id(self) -> UUID | None: ...

    @property
    def state(self) -> Any: ...


def register_runtime_routes(
    app: FastAPI,
    require_session: Callable[..., Any],
    *,
    instance_key: str,
    application_version: str,
    core: RuntimeCoreApi,
    shutdown_signal: RuntimeShutdownSignal,
    audit: AuditService | None,
) -> None:
    @app.get("/api/v1/runtime/identity", response_model=RuntimeIdentityResponse)
    async def get_runtime_identity(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> RuntimeIdentityResponse:
        """Return safe identity facts a Desktop uses to verify one attach."""

        if audit is not None:
            await audit.record(
                event_type="CLIENT_CORE_ATTACH",
                actor=f"client-session:{session.id}",
                subject="core",
                action="runtime.identity.read",
                resource=f"instance/{instance_key}",
                outcome="SUCCEEDED",
                origin="client",
                correlation_id=uuid4(),
            )
        return RuntimeIdentityResponse(
            instance_key=instance_key,
            runtime_session_id=core.runtime_session_id,
            application_version=application_version,
            protocol_version=PROTOCOL_VERSION,
            state=str(core.state),
        )

    @app.post(
        "/api/v1/runtime/shutdown",
        response_model=RuntimeShutdownResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def request_shutdown(
        body: RuntimeShutdownRequestBody,
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> RuntimeShutdownResponse:
        """Accept an explicit authenticated graceful Core shutdown request.

        This is a Core lifecycle command, not a Tool invocation: it never
        calls a Tool handler and never terminates a process by PID (Contract
        v1 SS23, Amendment 0004 SS18).
        """

        accepted = shutdown_signal.request(runtime_session_id=body.runtime_session_id)
        if audit is not None:
            await audit.record(
                event_type="CORE_SHUTDOWN_REQUESTED",
                actor=f"client-session:{session.id}",
                subject="core",
                action="runtime.shutdown",
                resource=f"runtime_session/{body.runtime_session_id}",
                outcome="ACCEPTED" if accepted else "REJECTED",
                origin="client",
                correlation_id=uuid4(),
                metadata={"reason": body.reason},
            )
        if not accepted:
            raise HTTPException(status.HTTP_409_CONFLICT, "runtime lifecycle mismatch")
        return RuntimeShutdownResponse(accepted=True)
