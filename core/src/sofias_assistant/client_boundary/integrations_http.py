"""Authenticated Local Client Boundary routes for approved integrations.

Desktop/Core Interaction Contract v1 SS29: a purpose-specific credential
write path for Sofias Memory, following the exact no-echo/no-plaintext
rules as the provider credential surface (SS25-28). This module does not
create a generic integration secret vault API and does not duplicate the
Sofias Memory domain: it only reports non-secret bootstrap configuration,
safe credential status and the already-computed Memory component health.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from sofias_assistant.client_boundary.sessions import ClientSession
from sofias_assistant.config.models import SofiasMemoryConfig
from sofias_assistant.execution.audit import AuditService
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.host.secret_bridge import (
    SOFIAS_MEMORY_API_KEY_REF,
    credential_write_status,
)
from sofias_assistant.secrets.models import SecretValue
from sofias_assistant.secrets.service import SecretService

_MEMORY_CREDENTIAL_REF = SOFIAS_MEMORY_API_KEY_REF


class IntegrationCredentialRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1)


class IntegrationCredentialResponse(BaseModel):
    credential_ref: str
    configured: bool
    effective_source: str
    writable_source: str
    shadowed: bool


class IntegrationHealthResponse(BaseModel):
    status: str
    detail: str | None


class SofiasMemoryIntegrationResponse(BaseModel):
    enabled: bool
    base_url: str | None
    credential: IntegrationCredentialResponse
    health: IntegrationHealthResponse


def _credential_response(
    secret_service: SecretService,
) -> IntegrationCredentialResponse:
    source, configured, shadowed = credential_write_status(
        _MEMORY_CREDENTIAL_REF, secret_service
    )
    return IntegrationCredentialResponse(
        credential_ref=_MEMORY_CREDENTIAL_REF.identifier,
        configured=configured,
        effective_source=source,
        writable_source="platform_store",
        shadowed=shadowed,
    )


def _memory_health(
    components: tuple[ComponentHealth, ...],
) -> IntegrationHealthResponse:
    for component in components:
        if component.name == "sofias-memory":
            return IntegrationHealthResponse(
                status=component.status.value, detail=component.detail
            )
    return IntegrationHealthResponse(status=HealthStatus.UNKNOWN.value, detail=None)


def register_integration_routes(
    app: FastAPI,
    require_session: Callable[..., Any],
    *,
    secret_service: SecretService,
    memory_config: SofiasMemoryConfig,
    memory_health: Callable[[], tuple[ComponentHealth, ...]],
    audit: AuditService | None,
) -> None:
    @app.get("/api/v1/integrations/sofias-memory")
    async def get_memory_integration(
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> SofiasMemoryIntegrationResponse:
        return SofiasMemoryIntegrationResponse(
            enabled=memory_config.enabled,
            base_url=memory_config.base_url,
            credential=_credential_response(secret_service),
            health=_memory_health(memory_health()),
        )

    @app.put("/api/v1/integrations/sofias-memory/credential")
    async def set_memory_credential(
        body: IntegrationCredentialRequestBody,
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> IntegrationCredentialResponse:
        secret_service.set(_MEMORY_CREDENTIAL_REF, SecretValue(body.value))
        response = _credential_response(secret_service)
        if audit is not None:
            await audit.record(
                event_type="INTEGRATION_CREDENTIAL_UPDATED",
                actor=f"client-session:{session.id}",
                subject="sofias-memory",
                action="integration.credential.update",
                resource=f"integration/{_MEMORY_CREDENTIAL_REF.identifier}",
                outcome="SUCCEEDED",
                origin="client",
                correlation_id=uuid4(),
                metadata={
                    "configured": response.configured,
                    "effective_source": response.effective_source,
                },
            )
        return response

    @app.delete("/api/v1/integrations/sofias-memory/credential")
    async def delete_memory_credential(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> IntegrationCredentialResponse:
        secret_service.delete(_MEMORY_CREDENTIAL_REF)
        response = _credential_response(secret_service)
        if audit is not None:
            await audit.record(
                event_type="INTEGRATION_CREDENTIAL_DELETED",
                actor=f"client-session:{session.id}",
                subject="sofias-memory",
                action="integration.credential.delete",
                resource=f"integration/{_MEMORY_CREDENTIAL_REF.identifier}",
                outcome="SUCCEEDED",
                origin="client",
                correlation_id=uuid4(),
                metadata={
                    "configured": response.configured,
                    "effective_source": response.effective_source,
                },
            )
        return response
