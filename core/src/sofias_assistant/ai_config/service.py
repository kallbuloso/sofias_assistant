"""Application service boundary for persistent AI configuration and routing.

Owns everything the Slice 09 / Gate I15 plan forbids scattering through HTTP
handlers or the domain: provider/model/profile/binding persistence, discovery
reconciliation, atomic `RoutingSnapshot` publication, routing preview and
safe Audit emission. `CapabilityRouter` stays pure and is only ever
constructed here, from already-validated snapshot data; nothing in this
module lets persistence leak into the router itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelIdentity,
)
from sofias_assistant.ai.discovery import DiscoveredModel, ModelDiscoveryAdapter
from sofias_assistant.ai.registry import (
    ModelAvailability,
    ModelDescriptor,
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.ai.routing_policy import (
    BindingSpec,
    FallbackPolicy,
    ModelDiagnostic,
    ProfileSpec,
    RoutingDecision,
    RoutingPolicy,
    RoutingSnapshot,
)
from sofias_assistant.ai_config.models import (
    CapabilityClaim,
    DiscoverySource,
    InferenceProfile,
    ModelCatalogEntry,
    ProfileModelBinding,
    ProviderConfiguration,
)
from sofias_assistant.config.models import require_safe_http_url
from sofias_assistant.host.secret_bridge import (
    credential_write_status,
    provider_api_key_ref,
)
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService

if TYPE_CHECKING:
    # Deferred to break the execution -> ai_config -> execution.audit import
    # cycle (execution/__init__.py eagerly imports DevelopmentAnalysisAgent
    # and ResearchAgent, which import this module). Safe because every
    # annotation in this file is a string (`from __future__ import annotations`).
    from sofias_assistant.execution.audit import AuditService

ProviderBindingFactory = Callable[
    [ProviderConfiguration, SecretService], ProviderBinding
]
DiscoveryAdapterFactory = Callable[
    [ProviderConfiguration, SecretService], ModelDiscoveryAdapter
]

_DEFAULT_PROFILE_REQUIREMENTS: dict[str, tuple[frozenset[Capability], DataLocality]] = {
    "chat.general": (
        frozenset({Capability.TEXT_GENERATION}),
        DataLocality.CLOUD_ALLOWED,
    ),
    "coding": (
        frozenset({Capability.TEXT_GENERATION, Capability.TOOL_CALLING}),
        DataLocality.CLOUD_ALLOWED,
    ),
    "research": (
        frozenset({Capability.TEXT_GENERATION, Capability.TOOL_CALLING}),
        DataLocality.CLOUD_ALLOWED,
    ),
    "vision": (frozenset({Capability.IMAGE_INPUT}), DataLocality.CLOUD_ALLOWED),
    "realtime": (
        frozenset(
            {Capability.REALTIME, Capability.AUDIO_INPUT, Capability.AUDIO_OUTPUT}
        ),
        DataLocality.CLOUD_ALLOWED,
    ),
}


class AIConfigurationError(RuntimeError):
    """Raised when a proposed AI configuration change is deterministically invalid."""


class ProfileNotFoundError(AIConfigurationError):
    """Raised when an operation references an unknown InferenceProfile key."""


class ProviderNotFoundError(AIConfigurationError):
    """Raised when an operation references an unknown ProviderConfiguration id."""


class SnapshotPublicationError(RuntimeError):
    """Raised when a rebuilt snapshot cannot be published; previous snapshot stands."""


@dataclass(frozen=True, slots=True)
class CanonicalBootstrap:
    """Bootstrap seed derived from the canonical `.env` provider/model."""

    provider_id: str
    display_name: str
    adapter_type: str
    base_url: str
    execution_location: ExecutionLocation
    credential_ref: SecretRef | None
    model_id: str
    model_display_name: str
    capabilities: frozenset[CapabilityClaim]


@dataclass(frozen=True, slots=True)
class ProfileBindingInput:
    """One caller-supplied ordered binding for a profile write."""

    provider_id: str
    model_id: str
    priority: int
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ProviderPatch:
    """Sparse non-secret update for `PATCH /api/v1/ai/providers/{id}` (Slice 10 SS23).

    Only the fields Contract v1 SS16 marks safe to mutate from a human
    dashboard: display metadata, non-secret base URL and enabled state.
    `adapter_type`, `execution_location` and `credential_ref` are never
    mutated through this patch.
    """

    display_name: str | None = None
    base_url: str | None = None
    enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class ProviderCredentialStatus:
    """Safe write/delete outcome for a provider credential (Contract v1 SS26)."""

    provider_id: str
    credential_ref: str
    configured: bool
    effective_source: str
    writable_source: str
    shadowed: bool


@dataclass(frozen=True, slots=True)
class ProfilePatch:
    """Sparse update for `PATCH /api/v1/ai/profiles/{key}` (Contract v1 SS33)."""

    enabled: bool | None = None
    preferred_capabilities: frozenset[Capability] | None = None
    locality: DataLocality | None = None
    fallback_policy: FallbackPolicy | None = None
    bindings: tuple[ProfileBindingInput, ...] | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _routing_event(decision: RoutingDecision) -> str:
    if decision.route is None:
        return "AI_ROUTING_FAILED"
    if decision.fallback:
        return "AI_ROUTING_FALLBACK"
    return "AI_ROUTING_SELECTED"


async def record_routing_decision(
    audit: AuditService | None,
    decision: RoutingDecision,
    *,
    correlation_id: UUID,
    actor: str,
    subject: str,
    origin: str,
    causation_id: UUID | None = None,
) -> None:
    """Shared safe Audit emission for one RoutingDecision.

    Reused by `AIConfigurationService.route_with_audit` and by every direct
    consumer (Conversation, Realtime, Vision, Agents) that resolves routing
    through an injected `RoutingPolicy` instead of the service itself. Never
    includes a secret, prompt or hidden reasoning (Contract v1 SS36).
    """

    if audit is None:
        return
    route = decision.route
    await audit.record(
        event_type=_routing_event(decision),
        actor=actor,
        subject=subject,
        action="ai.routing.resolve",
        resource=(
            f"{route.descriptor.identity.provider_id}/{route.descriptor.identity.model_id}"
            if route is not None
            else f"profile/{decision.profile_key}"
        ),
        outcome="SUCCEEDED" if route is not None else "FAILED",
        origin=origin,
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata={
            "profile": decision.profile_key,
            "provider_id": route.descriptor.identity.provider_id if route else None,
            "model_id": route.descriptor.identity.model_id if route else None,
            "reason_code": decision.reason_code.value,
            "fallback": decision.fallback,
        },
    )


class AIConfigurationService:
    """Single application boundary for AI provider/model/profile configuration."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], SqlAlchemyUnitOfWork],
        secret_service: SecretService,
        provider_binding_factories: Mapping[str, ProviderBindingFactory],
        discovery_adapter_factories: Mapping[str, DiscoveryAdapterFactory]
        | None = None,
        audit: AuditService | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._uow_factory = uow_factory
        self._secret_service = secret_service
        self._provider_binding_factories = dict(provider_binding_factories)
        self._discovery_adapter_factories = dict(discovery_adapter_factories or {})
        self._audit = audit
        self._clock = clock
        self._lock = asyncio.Lock()
        self._canonical: ModelIdentity | None = None
        self._snapshot: RoutingSnapshot = RoutingSnapshot(
            profiles={},
            bindings={},
            canonical=None,
            router=CapabilityRouter(ModelRegistry()),
        )

    # -- lifecycle -----------------------------------------------------

    def attach_audit(self, audit: AuditService) -> None:
        """Bind the Core-composed `AuditService` after construction.

        `build_conversation_dependencies_factory` (host composition) builds
        this service before `ExecutionRuntime`/`AuditService` are threaded
        through the shared `ConversationDependenciesFactory` signature, so
        `SofiaCore._compose_conversation_runtime` calls this once the real
        `AuditService` is available. Safe to call more than once; every safe
        Audit event this service emits (`AI_PROVIDER_CONFIG_CHANGED`,
        `AI_MODEL_CATALOG_REFRESHED`, `AI_PROFILE_CHANGED`,
        `PROVIDER_CREDENTIAL_UPDATED`, `PROVIDER_CREDENTIAL_DELETED`) is a
        no-op until this is called.
        """

        self._audit = audit

    async def bootstrap(self, canonical: CanonicalBootstrap) -> None:
        """Idempotently seed canonical provider/model/profiles, then publish."""

        self._canonical = ModelIdentity(canonical.provider_id, canonical.model_id)
        async with self._lock:
            async with self._uow_factory() as uow:
                now = self._clock()
                if (
                    await uow.provider_configurations.get_by_id(canonical.provider_id)
                    is None
                ):
                    uow.provider_configurations.add(
                        ProviderConfiguration(
                            id=canonical.provider_id,
                            display_name=canonical.display_name,
                            adapter_type=canonical.adapter_type,
                            base_url=canonical.base_url,
                            enabled=True,
                            execution_location=canonical.execution_location,
                            credential_ref=canonical.credential_ref,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                if (
                    await uow.model_catalog_entries.get_by_identity(
                        canonical.provider_id, canonical.model_id
                    )
                    is None
                ):
                    uow.model_catalog_entries.add(
                        ModelCatalogEntry(
                            provider_id=canonical.provider_id,
                            model_id=canonical.model_id,
                            display_name=canonical.model_display_name,
                            context_window=None,
                            execution_location=canonical.execution_location,
                            availability=ModelAvailability.AVAILABLE,
                            enabled=True,
                            discovery_source=DiscoverySource.BOOTSTRAP,
                            capabilities=canonical.capabilities,
                            metadata={},
                            last_seen_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                for profile in _default_profiles(now):
                    if await uow.inference_profiles.get_by_key(profile.key) is None:
                        uow.inference_profiles.add(profile)
                if not await uow.profile_model_bindings.list_for_profile(
                    "chat.general"
                ):
                    uow.profile_model_bindings.add(
                        ProfileModelBinding(
                            profile_key="chat.general",
                            provider_id=canonical.provider_id,
                            model_id=canonical.model_id,
                            priority=1,
                            enabled=True,
                            source="bootstrap",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                await uow.commit()
            await self._rebuild_and_publish()
        await self._emit(
            event_type="AI_PROVIDER_CONFIG_CHANGED",
            actor="sofia-core",
            subject=canonical.provider_id,
            action="ai.provider.bootstrap",
            resource=f"provider/{canonical.provider_id}",
            outcome="SUCCEEDED",
            origin="BOOTSTRAP",
            correlation_id=_fresh_uuid(),
            metadata={"provider_id": canonical.provider_id},
        )

    async def initialize(self) -> None:
        """Load already-persisted configuration and publish it (no seeding)."""

        async with self._lock:
            await self._rebuild_and_publish()

    # -- reads -----------------------------------------------------------

    async def list_providers(self) -> tuple[ProviderConfiguration, ...]:
        async with self._uow_factory() as uow:
            return tuple(await uow.provider_configurations.list_all())

    async def list_models(self) -> tuple[ModelCatalogEntry, ...]:
        async with self._uow_factory() as uow:
            return tuple(await uow.model_catalog_entries.list_all())

    async def list_profiles(self) -> tuple[InferenceProfile, ...]:
        async with self._uow_factory() as uow:
            return tuple(await uow.inference_profiles.list_all())

    async def get_profile(self, key: str) -> InferenceProfile | None:
        async with self._uow_factory() as uow:
            return await uow.inference_profiles.get_by_key(key)

    async def list_bindings(self, profile_key: str) -> tuple[ProfileModelBinding, ...]:
        async with self._uow_factory() as uow:
            return tuple(await uow.profile_model_bindings.list_for_profile(profile_key))

    def is_credential_configured(self, ref: SecretRef | None) -> bool:
        """Safe boolean-only diagnostic; never exposes the secret value."""

        if ref is None:
            return False
        return self._secret_service.get(ref) is not None

    def current_snapshot(self) -> RoutingSnapshot:
        return self._snapshot

    def routing_policy_for(self, profile_key: str) -> RoutingPolicy:
        return RoutingPolicy(lambda: self._snapshot, profile_key=profile_key)

    def preview_routing(
        self,
        profile_key: str,
        requirements: AIRequestRequirements,
        *,
        model_override: ModelIdentity | None = None,
    ) -> RoutingDecision:
        """Deterministic routing evidence; never invokes a provider."""

        return self.routing_policy_for(profile_key).resolve(
            requirements, model_override=model_override
        )

    async def route_with_audit(
        self,
        profile_key: str,
        requirements: AIRequestRequirements,
        *,
        model_override: ModelIdentity | None = None,
        correlation_id: UUID,
        actor: str,
        subject: str,
        origin: str,
        causation_id: UUID | None = None,
    ) -> RoutingDecision:
        """Resolve one routing decision and emit its safe Audit evidence."""

        decision = self.preview_routing(
            profile_key, requirements, model_override=model_override
        )
        await record_routing_decision(
            self._audit,
            decision,
            correlation_id=correlation_id,
            actor=actor,
            subject=subject,
            origin=origin,
            causation_id=causation_id,
        )
        return decision

    # -- writes ------------------------------------------------------------

    async def refresh_models(self, provider_id: str) -> tuple[ModelCatalogEntry, ...]:
        """Discover, reconcile (never physically delete), and republish."""

        async with self._lock:
            async with self._uow_factory() as uow:
                provider = await uow.provider_configurations.get_by_id(provider_id)
                if provider is None:
                    raise AIConfigurationError(f"Unknown provider: {provider_id}")
                factory = self._discovery_adapter_factories.get(provider.adapter_type)
                discovered: tuple[DiscoveredModel, ...] = ()
                if factory is not None:
                    adapter = factory(provider, self._secret_service)
                    discovered = tuple(await adapter.discover_models())
                now = self._clock()
                existing = {
                    entry.model_id: entry
                    for entry in await uow.model_catalog_entries.list_for_provider(
                        provider_id
                    )
                }
                seen_model_ids = {model.model_id for model in discovered}
                for model in discovered:
                    current = existing.get(model.model_id)
                    if current is None:
                        uow.model_catalog_entries.add(
                            ModelCatalogEntry(
                                provider_id=provider_id,
                                model_id=model.model_id,
                                display_name=model.display_name,
                                context_window=None,
                                execution_location=provider.execution_location,
                                availability=ModelAvailability.AVAILABLE,
                                enabled=False,
                                discovery_source=DiscoverySource.DISCOVERED,
                                capabilities=frozenset(),
                                metadata={},
                                last_seen_at=now,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    else:
                        await uow.model_catalog_entries.save(
                            _with_last_seen(
                                current,
                                availability=ModelAvailability.AVAILABLE,
                                last_seen_at=now,
                                updated_at=now,
                            )
                        )
                for model_id, current in existing.items():
                    if (
                        model_id not in seen_model_ids
                        and current.discovery_source is DiscoverySource.DISCOVERED
                    ):
                        await uow.model_catalog_entries.save(
                            _with_last_seen(
                                current,
                                availability=ModelAvailability.UNAVAILABLE,
                                last_seen_at=current.last_seen_at,
                                updated_at=now,
                            )
                        )
                await uow.commit()
                refreshed = tuple(
                    await uow.model_catalog_entries.list_for_provider(provider_id)
                )
            await self._rebuild_and_publish()
        await self._emit(
            event_type="AI_MODEL_CATALOG_REFRESHED",
            actor="sofia-core",
            subject=provider_id,
            action="ai.models.refresh",
            resource=f"provider/{provider_id}",
            outcome="SUCCEEDED",
            origin="AI_CONFIGURATION_API",
            correlation_id=_fresh_uuid(),
            metadata={"provider_id": provider_id, "discovered_count": len(discovered)},
        )
        return refreshed

    async def update_provider(
        self, provider_id: str, patch: ProviderPatch
    ) -> ProviderConfiguration:
        """Validate, persist and republish a non-secret provider config change.

        `enabled`/`base_url` affect routing eligibility and adapter
        construction, so this always rebuilds and atomically republishes the
        `RoutingSnapshot` (Amendment 0003 SS13/SS17), exactly like
        `update_profile`.
        """

        async with self._lock:
            async with self._uow_factory() as uow:
                current = await uow.provider_configurations.get_by_id(provider_id)
                if current is None:
                    raise ProviderNotFoundError(f"Unknown provider: {provider_id}")
                if patch.base_url is not None:
                    try:
                        require_safe_http_url(patch.base_url, field_name="base_url")
                    except ValueError as error:
                        raise AIConfigurationError(str(error)) from error
                now = self._clock()
                updated = ProviderConfiguration(
                    id=current.id,
                    display_name=(
                        patch.display_name
                        if patch.display_name is not None
                        else current.display_name
                    ),
                    adapter_type=current.adapter_type,
                    base_url=(
                        patch.base_url
                        if patch.base_url is not None
                        else current.base_url
                    ),
                    enabled=(
                        patch.enabled if patch.enabled is not None else current.enabled
                    ),
                    execution_location=current.execution_location,
                    credential_ref=current.credential_ref,
                    created_at=current.created_at,
                    updated_at=now,
                )
                await uow.provider_configurations.save(updated)
                await uow.commit()
            try:
                await self._rebuild_and_publish()
            except Exception as error:
                raise SnapshotPublicationError(
                    "Routing snapshot rebuild failed after provider update"
                ) from error
        await self._emit(
            event_type="AI_PROVIDER_CONFIG_CHANGED",
            actor="dashboard",
            subject=provider_id,
            action="ai.provider.update",
            resource=f"provider/{provider_id}",
            outcome="SUCCEEDED",
            origin="AI_CONFIGURATION_API",
            correlation_id=_fresh_uuid(),
            metadata={
                "provider_id": provider_id,
                "enabled": updated.enabled,
            },
        )
        return updated

    async def set_provider_credential(
        self, provider_id: str, value: SecretValue
    ) -> ProviderCredentialStatus:
        """Write a provider credential through `SecretService` (Contract v1 SS25-28).

        The `SecretRef` is always derived server-side from the known
        `provider_id`; the caller never supplies or chooses one. Never
        rebuilds the routing snapshot: adapters resolve the secret value
        through `SecretService` at call time, not at snapshot-build time.
        """

        async with self._uow_factory() as uow:
            provider = await uow.provider_configurations.get_by_id(provider_id)
        if provider is None:
            raise ProviderNotFoundError(f"Unknown provider: {provider_id}")
        ref = provider_api_key_ref(provider_id)
        self._secret_service.set(ref, value)
        status = self._credential_status(provider_id, ref)
        await self._emit(
            event_type="PROVIDER_CREDENTIAL_UPDATED",
            actor="dashboard",
            subject=provider_id,
            action="ai.provider.credential.update",
            resource=f"provider/{provider_id}",
            outcome="SUCCEEDED",
            origin="AI_CONFIGURATION_API",
            correlation_id=_fresh_uuid(),
            metadata={
                "provider_id": provider_id,
                "credential_ref": ref.identifier,
                "configured": status.configured,
                "effective_source": status.effective_source,
            },
        )
        return status

    async def delete_provider_credential(
        self, provider_id: str
    ) -> ProviderCredentialStatus:
        """Delete a durable platform-store provider credential (Contract v1 SS25-28).

        Deleting the writable platform-store copy never removes a
        higher-priority environment-backed secret (Amendment 0004 SS22).
        """

        async with self._uow_factory() as uow:
            provider = await uow.provider_configurations.get_by_id(provider_id)
        if provider is None:
            raise ProviderNotFoundError(f"Unknown provider: {provider_id}")
        ref = provider_api_key_ref(provider_id)
        self._secret_service.delete(ref)
        status = self._credential_status(provider_id, ref)
        await self._emit(
            event_type="PROVIDER_CREDENTIAL_DELETED",
            actor="dashboard",
            subject=provider_id,
            action="ai.provider.credential.delete",
            resource=f"provider/{provider_id}",
            outcome="SUCCEEDED",
            origin="AI_CONFIGURATION_API",
            correlation_id=_fresh_uuid(),
            metadata={
                "provider_id": provider_id,
                "credential_ref": ref.identifier,
                "configured": status.configured,
                "effective_source": status.effective_source,
            },
        )
        return status

    def _credential_status(
        self, provider_id: str, ref: SecretRef
    ) -> ProviderCredentialStatus:
        source, configured, shadowed = credential_write_status(
            ref, self._secret_service
        )
        return ProviderCredentialStatus(
            provider_id=provider_id,
            credential_ref=ref.identifier,
            configured=configured,
            effective_source=source,
            writable_source="platform_store",
            shadowed=shadowed,
        )

    async def update_profile(self, key: str, patch: ProfilePatch) -> InferenceProfile:
        """Validate, persist, rebuild and atomically publish a profile change."""

        async with self._lock:
            async with self._uow_factory() as uow:
                current = await uow.inference_profiles.get_by_key(key)
                if current is None:
                    raise ProfileNotFoundError(f"Unknown profile: {key}")
                now = self._clock()
                updated = InferenceProfile(
                    key=current.key,
                    display_name=current.display_name,
                    description=current.description,
                    required_capabilities=current.required_capabilities,
                    preferred_capabilities=(
                        patch.preferred_capabilities
                        if patch.preferred_capabilities is not None
                        else current.preferred_capabilities
                    ),
                    locality=(
                        patch.locality
                        if patch.locality is not None
                        else current.locality
                    ),
                    enabled=patch.enabled
                    if patch.enabled is not None
                    else current.enabled,
                    fallback_policy=(
                        patch.fallback_policy
                        if patch.fallback_policy is not None
                        else current.fallback_policy
                    ),
                    created_at=current.created_at,
                    updated_at=now,
                )
                if patch.bindings is not None:
                    models_by_identity = {
                        entry.identity: entry
                        for entry in await uow.model_catalog_entries.list_all()
                    }
                    for candidate in patch.bindings:
                        _validate_binding_or_raise(
                            updated, candidate, models_by_identity
                        )
                    await uow.profile_model_bindings.replace_for_profile(
                        key,
                        [
                            ProfileModelBinding(
                                profile_key=key,
                                provider_id=candidate.provider_id,
                                model_id=candidate.model_id,
                                priority=candidate.priority,
                                enabled=candidate.enabled,
                                source="user",
                                created_at=now,
                                updated_at=now,
                            )
                            for candidate in patch.bindings
                        ],
                    )
                await uow.inference_profiles.save(updated)
                await uow.commit()
            try:
                await self._rebuild_and_publish()
            except Exception as error:
                raise SnapshotPublicationError(
                    "Routing snapshot rebuild failed after profile update"
                ) from error
        await self._emit(
            event_type="AI_PROFILE_CHANGED",
            actor="sofia-core",
            subject=key,
            action="ai.profile.update",
            resource=f"profile/{key}",
            outcome="SUCCEEDED",
            origin="AI_CONFIGURATION_API",
            correlation_id=_fresh_uuid(),
            metadata={"profile": key},
        )
        return updated

    # -- internal ------------------------------------------------------

    async def _rebuild_and_publish(self) -> None:
        """Build a complete candidate snapshot and only then replace the active one."""

        async with self._uow_factory() as uow:
            providers = {p.id: p for p in await uow.provider_configurations.list_all()}
            models = await uow.model_catalog_entries.list_all()
            profiles = await uow.inference_profiles.list_all()
            raw_bindings = await uow.profile_model_bindings.list_all()

        registry = ModelRegistry()
        diagnostics: dict[ModelIdentity, ModelDiagnostic] = {}
        for model in models:
            identity = model.identity
            provider = providers.get(model.provider_id)
            provider_enabled = provider is not None and provider.enabled
            adapter_incompatible = False
            if (
                provider is not None
                and provider_enabled
                and model.enabled
                and (model.availability is ModelAvailability.AVAILABLE)
            ):
                trusted = model.trusted_capabilities()
                binding_factory = self._provider_binding_factories.get(
                    provider.adapter_type
                )
                if trusted and binding_factory is not None:
                    try:
                        binding = binding_factory(provider, self._secret_service)
                        registry.register(
                            ModelRegistration(
                                descriptor=ModelDescriptor(
                                    identity=identity,
                                    capabilities=trusted,
                                    execution_location=model.execution_location,
                                    context_window=model.context_window,
                                ),
                                binding=binding,
                            )
                        )
                    except ValueError:
                        adapter_incompatible = True
                elif trusted and binding_factory is None:
                    adapter_incompatible = True
            diagnostics[identity] = ModelDiagnostic(
                provider_enabled=provider_enabled,
                model_known=True,
                model_enabled=model.enabled,
                availability=model.availability,
                execution_location=model.execution_location,
                adapter_incompatible=adapter_incompatible,
            )

        profile_specs = {
            profile.key: ProfileSpec(
                key=profile.key,
                required_capabilities=profile.required_capabilities,
                preferred_capabilities=profile.preferred_capabilities,
                locality=profile.locality,
                enabled=profile.enabled,
                fallback_policy=profile.fallback_policy,
            )
            for profile in profiles
        }
        bindings_by_profile: dict[str, list[BindingSpec]] = {}
        for raw_binding in raw_bindings:
            bindings_by_profile.setdefault(raw_binding.profile_key, []).append(
                BindingSpec(
                    identity=raw_binding.identity,
                    priority=raw_binding.priority,
                    enabled=raw_binding.enabled,
                )
            )
        bindings = {
            key: tuple(sorted(value, key=lambda spec: spec.priority))
            for key, value in bindings_by_profile.items()
        }

        self._snapshot = RoutingSnapshot(
            profiles=profile_specs,
            bindings=bindings,
            canonical=self._canonical,
            router=CapabilityRouter(registry),
            diagnostics=diagnostics,
        )

    async def _emit(
        self,
        *,
        event_type: str,
        actor: str,
        subject: str,
        action: str,
        resource: str,
        outcome: str,
        origin: str,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self._audit is None:
            return
        await self._audit.record(
            event_type=event_type,
            actor=actor,
            subject=subject,
            action=action,
            resource=resource,
            outcome=outcome,
            origin=origin,
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata=metadata or {},
        )


def _validate_binding_or_raise(
    profile: InferenceProfile,
    candidate: ProfileBindingInput,
    models_by_identity: Mapping[ModelIdentity, ModelCatalogEntry],
) -> None:
    identity = ModelIdentity(candidate.provider_id, candidate.model_id)
    model = models_by_identity.get(identity)
    if model is None:
        raise AIConfigurationError(
            f"Binding references an unknown model: {identity.provider_id}/{identity.model_id}"
        )
    if not profile.required_capabilities <= model.trusted_capabilities():
        raise AIConfigurationError(
            "Binding does not satisfy the profile's required capabilities: "
            f"{identity.provider_id}/{identity.model_id}"
        )
    if (
        profile.locality is DataLocality.LOCAL_ONLY
        and model.execution_location is not ExecutionLocation.LOCAL
    ):
        raise AIConfigurationError(
            f"Binding is not LOCAL_ONLY compatible: {identity.provider_id}/{identity.model_id}"
        )


def _with_last_seen(
    entry: ModelCatalogEntry,
    *,
    availability: ModelAvailability,
    last_seen_at: datetime | None,
    updated_at: datetime,
) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        provider_id=entry.provider_id,
        model_id=entry.model_id,
        display_name=entry.display_name,
        context_window=entry.context_window,
        execution_location=entry.execution_location,
        availability=availability,
        enabled=entry.enabled,
        discovery_source=entry.discovery_source,
        capabilities=entry.capabilities,
        metadata=entry.metadata,
        last_seen_at=last_seen_at,
        created_at=entry.created_at,
        updated_at=updated_at,
    )


def _default_profiles(now: datetime) -> tuple[InferenceProfile, ...]:
    return tuple(
        InferenceProfile(
            key=key,
            display_name=key,
            description=f"Baseline {key} workload profile",
            required_capabilities=required,
            preferred_capabilities=frozenset(),
            locality=locality,
            enabled=True,
            fallback_policy=FallbackPolicy.ORDERED_THEN_CANONICAL,
            created_at=now,
            updated_at=now,
        )
        for key, (required, locality) in _DEFAULT_PROFILE_REQUIREMENTS.items()
    )


def _fresh_uuid() -> UUID:
    from uuid import uuid4

    return uuid4()
