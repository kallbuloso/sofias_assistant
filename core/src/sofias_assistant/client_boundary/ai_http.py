"""Authenticated Local Client Boundary routes for AI configuration/routing.

Runtime Configuration Contract v1 SS30-SS34: providers, model catalog,
discovery refresh, inference profiles and deterministic routing preview.
Every endpoint calls `AIConfigurationService`; none touches persistence or
`CapabilityRouter` directly. No endpoint accepts or returns a raw secret
value (only a safe `configured: bool` diagnostic).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sofias_assistant.ai.contracts import Capability, DataLocality, ModelIdentity
from sofias_assistant.ai.routing_policy import FallbackPolicy
from sofias_assistant.ai_config.models import ModelCatalogEntry, ProviderConfiguration
from sofias_assistant.ai_config.service import (
    AIConfigurationError,
    AIConfigurationService,
    ProfileBindingInput,
    ProfileNotFoundError,
    ProfilePatch,
    SnapshotPublicationError,
)
from sofias_assistant.client_boundary.sessions import ClientSession


class CredentialRepresentation(BaseModel):
    ref: str | None
    configured: bool


class ProviderResponse(BaseModel):
    id: str
    display_name: str
    adapter_type: str
    base_url: str
    enabled: bool
    execution_location: str
    credential: CredentialRepresentation


class CapabilityClaimResponse(BaseModel):
    capability: str
    provenance: str


class ModelResponse(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int | None
    execution_location: str
    availability: str
    enabled: bool
    discovery_source: str
    capabilities: list[CapabilityClaimResponse]
    last_seen_at: datetime | None


class ModelRefreshRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1)


class BindingResponse(BaseModel):
    provider_id: str
    model_id: str
    priority: int
    enabled: bool
    source: str


class ProfileResponse(BaseModel):
    key: str
    display_name: str
    description: str
    required_capabilities: list[str]
    preferred_capabilities: list[str]
    locality: str
    enabled: bool
    fallback_policy: str
    bindings: list[BindingResponse] = Field(default_factory=list)


class ProfileBindingRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    priority: int
    enabled: bool = True


class ProfilePatchRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    preferred_capabilities: list[str] | None = None
    locality: Literal["local_only", "cloud_allowed", "cloud_preferred"] | None = None
    fallback_policy: Literal["ordered_only", "ordered_then_canonical"] | None = None
    bindings: list[ProfileBindingRequestBody] | None = None


class RoutingPreviewRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = Field(min_length=1)
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    locality: Literal["local_only", "cloud_allowed", "cloud_preferred"] = (
        "cloud_allowed"
    )
    override: dict[str, str] | None = None


class RoutingSelectionResponse(BaseModel):
    provider_id: str
    model_id: str


class RoutingPreviewResponse(BaseModel):
    profile: str
    selected: RoutingSelectionResponse | None
    fallback: bool
    reason_code: str
    reason: str


def _provider_response(
    provider: ProviderConfiguration, service: AIConfigurationService
) -> ProviderResponse:
    return ProviderResponse(
        id=provider.id,
        display_name=provider.display_name,
        adapter_type=provider.adapter_type,
        base_url=provider.base_url,
        enabled=provider.enabled,
        execution_location=provider.execution_location.value,
        credential=CredentialRepresentation(
            ref=provider.credential_ref.identifier if provider.credential_ref else None,
            configured=service.is_credential_configured(provider.credential_ref),
        ),
    )


def _model_response(entry: ModelCatalogEntry) -> ModelResponse:
    return ModelResponse(
        provider_id=entry.provider_id,
        model_id=entry.model_id,
        display_name=entry.display_name,
        context_window=entry.context_window,
        execution_location=entry.execution_location.value,
        availability=entry.availability.value,
        enabled=entry.enabled,
        discovery_source=entry.discovery_source.value,
        capabilities=[
            CapabilityClaimResponse(
                capability=claim.capability.value, provenance=claim.provenance.value
            )
            for claim in entry.capabilities
        ],
        last_seen_at=entry.last_seen_at,
    )


async def _profile_response(
    service: AIConfigurationService, key: str
) -> ProfileResponse | None:
    profile = await service.get_profile(key)
    if profile is None:
        return None
    bindings = await service.list_bindings(key)
    return ProfileResponse(
        key=profile.key,
        display_name=profile.display_name,
        description=profile.description,
        required_capabilities=sorted(
            capability.value for capability in profile.required_capabilities
        ),
        preferred_capabilities=sorted(
            capability.value for capability in profile.preferred_capabilities
        ),
        locality=profile.locality.value,
        enabled=profile.enabled,
        fallback_policy=profile.fallback_policy.value,
        bindings=[
            BindingResponse(
                provider_id=binding.provider_id,
                model_id=binding.model_id,
                priority=binding.priority,
                enabled=binding.enabled,
                source=binding.source,
            )
            for binding in sorted(bindings, key=lambda value: value.priority)
        ],
    )


def register_ai_configuration_routes(
    app: FastAPI,
    require_session: Callable[..., Any],
    service: AIConfigurationService,
) -> None:
    @app.get("/api/v1/ai/providers")
    async def list_providers(
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> list[ProviderResponse]:
        providers = await service.list_providers()
        return [_provider_response(provider, service) for provider in providers]

    @app.get("/api/v1/ai/models")
    async def list_models(
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> list[ModelResponse]:
        models = await service.list_models()
        return [_model_response(entry) for entry in models]

    @app.post("/api/v1/ai/models/refresh")
    async def refresh_models(
        body: ModelRefreshRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> list[ModelResponse]:
        try:
            refreshed = await service.refresh_models(body.provider_id)
        except AIConfigurationError as error:
            raise HTTPException(422, str(error)) from None
        return [_model_response(entry) for entry in refreshed]

    @app.get("/api/v1/ai/profiles")
    async def list_profiles(
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> list[ProfileResponse]:
        profiles = await service.list_profiles()
        responses = []
        for profile in profiles:
            response = await _profile_response(service, profile.key)
            if response is not None:
                responses.append(response)
        return responses

    @app.get("/api/v1/ai/profiles/{key}")
    async def get_profile(
        key: str, _: Annotated[ClientSession, Depends(require_session)]
    ) -> ProfileResponse:
        response = await _profile_response(service, key)
        if response is None:
            raise HTTPException(404, "Profile not found")
        return response

    @app.patch("/api/v1/ai/profiles/{key}")
    async def patch_profile(
        key: str,
        body: ProfilePatchRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> ProfileResponse:
        patch = ProfilePatch(
            enabled=body.enabled,
            preferred_capabilities=(
                frozenset(Capability(value) for value in body.preferred_capabilities)
                if body.preferred_capabilities is not None
                else None
            ),
            locality=DataLocality(body.locality) if body.locality is not None else None,
            fallback_policy=(
                FallbackPolicy(body.fallback_policy)
                if body.fallback_policy is not None
                else None
            ),
            bindings=(
                tuple(
                    ProfileBindingInput(
                        provider_id=binding.provider_id,
                        model_id=binding.model_id,
                        priority=binding.priority,
                        enabled=binding.enabled,
                    )
                    for binding in body.bindings
                )
                if body.bindings is not None
                else None
            ),
        )
        try:
            await service.update_profile(key, patch)
        except ProfileNotFoundError:
            raise HTTPException(404, "Profile not found") from None
        except (AIConfigurationError, SnapshotPublicationError) as error:
            raise HTTPException(422, str(error)) from None
        response = await _profile_response(service, key)
        assert response is not None
        return response

    @app.post("/api/v1/ai/routing/preview")
    async def preview_routing(
        body: RoutingPreviewRequestBody,
        _: Annotated[ClientSession, Depends(require_session)],
    ) -> RoutingPreviewResponse:
        from sofias_assistant.ai.contracts import AIRequestRequirements

        required = frozenset(Capability(value) for value in body.required_capabilities)
        preferred = frozenset(
            Capability(value) for value in body.preferred_capabilities
        )
        requirements = AIRequestRequirements(
            required_capabilities=required,
            preferred_capabilities=preferred - required,
            locality=DataLocality(body.locality),
        )
        override = (
            ModelIdentity(body.override["provider_id"], body.override["model_id"])
            if body.override
            else None
        )
        decision = service.preview_routing(
            body.profile, requirements, model_override=override
        )
        return RoutingPreviewResponse(
            profile=decision.profile_key,
            selected=(
                RoutingSelectionResponse(
                    provider_id=decision.route.descriptor.identity.provider_id,
                    model_id=decision.route.descriptor.identity.model_id,
                )
                if decision.route is not None
                else None
            ),
            fallback=decision.fallback,
            reason_code=decision.reason_code.value,
            reason=decision.reason,
        )
