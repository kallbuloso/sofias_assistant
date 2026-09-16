"""Gate I15 — Intelligent AI Routing (SA-B037).

Proves the full Amendment 0003 / Runtime Configuration Contract v1 vertical:
persistent ProviderConfiguration/ModelCatalog/InferenceProfile/
ProfileModelBinding, capability provenance, provider-neutral discovery,
deterministic profile-aware routing with reason codes and fallback, atomic
RoutingSnapshot publication, real Conversation/Agent/Vision consumer
integration, the authenticated AI Configuration API surface, safe Audit and
no secret leakage — using deterministic fakes only (no live provider).
"""

from __future__ import annotations

from asyncio import to_thread
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    Capability,
    CapabilityProvenance,
    DataLocality,
    ExecutionLocation,
)
from sofias_assistant.ai.discovery import DiscoveredModel
from sofias_assistant.ai.fake import FakeVisionProvider
from sofias_assistant.ai.registry import ModelAvailability, ProviderBinding
from sofias_assistant.ai.routing_policy import RoutingReasonCode
from sofias_assistant.ai_config.models import (
    CapabilityClaim,
    DiscoverySource,
    ModelCatalogEntry,
    ProviderConfiguration,
)
from sofias_assistant.ai_config.service import (
    AIConfigurationError,
    AIConfigurationService,
    CanonicalBootstrap,
    ProfileBindingInput,
    ProfilePatch,
    SnapshotPublicationError,
)
from sofias_assistant.capabilities.vision import VisionCapability
from sofias_assistant.client_boundary.ai_http import (
    RoutingPreviewRequestBody,
)
from sofias_assistant.execution import AgentRuntime, AuthorityContext, ExecutionRuntime
from sofias_assistant.execution.audit import AuditService
from sofias_assistant.execution.development_analysis import (
    register_development_analysis,
)
from sofias_assistant.execution.research import register_research
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore
from tests.support.ai import FakeTextSuccess, ScriptedFakeProvider

_FIXED_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _FIXED_NOW


class _FakeSecretStore(SecretStore):
    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


def _binding_factory(binding: ProviderBinding):
    def factory(_: ProviderConfiguration, __: SecretService) -> ProviderBinding:
        return binding

    return factory


class _FakeDiscoveryAdapter:
    def __init__(self, models: list[DiscoveredModel]) -> None:
        self._models = models

    async def discover_models(self) -> list[DiscoveredModel]:
        return self._models


async def _service(
    tmp_path: Path,
    *,
    provider_binding_factories: dict,
    discovery_adapter_factories: dict | None = None,
) -> tuple[AIConfigurationService, AuditService]:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    audit = AuditService(session_factory)
    secret_service = SecretService(_FakeSecretStore())
    secret_service.set(SecretRef("providers/provider-a/api-key"), SecretValue("sk-a"))
    secret_service.set(SecretRef("providers/provider-b/api-key"), SecretValue("sk-b"))
    service = AIConfigurationService(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        secret_service=secret_service,
        provider_binding_factories=provider_binding_factories,
        discovery_adapter_factories=discovery_adapter_factories or {},
        audit=audit,
        clock=_clock,
    )
    return service, audit


def _canonical(**overrides: Any) -> CanonicalBootstrap:
    defaults: dict[str, Any] = dict(
        provider_id="provider-a",
        display_name="Provider A",
        adapter_type="provider-a",
        base_url="https://provider-a.invalid/v1",
        execution_location=ExecutionLocation.CLOUD,
        credential_ref=SecretRef("providers/provider-a/api-key"),
        model_id="model-old",
        model_display_name="model-old",
        capabilities=frozenset(
            {
                CapabilityClaim(
                    Capability.TEXT_GENERATION, CapabilityProvenance.BUILTIN_METADATA
                ),
                CapabilityClaim(
                    Capability.TEXT_STREAMING, CapabilityProvenance.BUILTIN_METADATA
                ),
            }
        ),
    )
    defaults.update(overrides)
    return CanonicalBootstrap(**defaults)


async def _add_provider_b_with_coding_capable_model(
    service: AIConfigurationService,
) -> None:
    # Two separate transactions: SQLAlchemy's unit-of-work only orders
    # cross-table inserts within one flush when an ORM `relationship()`
    # connects the mappers, which these deliberately do not have (Amendment
    # 0003: no persistence-aware coupling). Committing the provider row
    # first keeps this fixture correct regardless of flush ordering.
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.provider_configurations.add(
            ProviderConfiguration(
                id="provider-b",
                display_name="Provider B",
                adapter_type="provider-b",
                base_url="https://provider-b.invalid/v1",
                enabled=True,
                execution_location=ExecutionLocation.CLOUD,
                credential_ref=SecretRef("providers/provider-b/api-key"),
                created_at=_FIXED_NOW,
                updated_at=_FIXED_NOW,
            )
        )
        await uow.commit()
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.model_catalog_entries.add(
            ModelCatalogEntry(
                provider_id="provider-b",
                model_id="model-new",
                display_name="model-new",
                context_window=None,
                execution_location=ExecutionLocation.CLOUD,
                availability=ModelAvailability.AVAILABLE,
                enabled=True,
                discovery_source=DiscoverySource.MANUAL,
                capabilities=frozenset(
                    {
                        CapabilityClaim(
                            Capability.TEXT_GENERATION,
                            CapabilityProvenance.USER_OVERRIDE,
                        ),
                        CapabilityClaim(
                            Capability.TOOL_CALLING, CapabilityProvenance.USER_OVERRIDE
                        ),
                    }
                ),
                metadata={},
                last_seen_at=_FIXED_NOW,
                created_at=_FIXED_NOW,
                updated_at=_FIXED_NOW,
            )
        )
        await uow.commit()
    await service._rebuild_and_publish()  # noqa: SLF001


def _requirements(
    required: frozenset[Capability] = frozenset(),
    locality: DataLocality = DataLocality.CLOUD_ALLOWED,
) -> AIRequestRequirements:
    return AIRequestRequirements(
        required_capabilities=required,
        preferred_capabilities=frozenset(),
        locality=locality,
    )


# ---------------------------------------------------------------------------
# First boot / persistence / discovery / capability provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_boot_seeds_canonical_provider_model_and_chat_general_route(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("hi")])
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    providers = await service.list_providers()
    models = await service.list_models()
    assert [p.id for p in providers] == ["provider-a"]
    assert [m.model_id for m in models] == ["model-old"]

    decision = service.preview_routing(
        "chat.general", _requirements(frozenset({Capability.TEXT_GENERATION}))
    )
    assert decision.route is not None
    assert decision.route.descriptor.identity.provider_id == "provider-a"
    assert decision.reason_code is RoutingReasonCode.PROFILE_BINDING_SELECTED


@pytest.mark.asyncio
async def test_persisted_provider_configuration_survives_reinitialize(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    factories = {
        "provider-a": _binding_factory(
            ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
        )
    }
    service, _ = await _service(tmp_path, provider_binding_factories=factories)
    await service.bootstrap(_canonical())

    reloaded, _ = await _service(tmp_path, provider_binding_factories=factories)
    await reloaded.initialize()  # simulates a second process boot; no re-seed

    providers = await reloaded.list_providers()
    assert [p.id for p in providers] == ["provider-a"]
    decision = reloaded.preview_routing(
        "chat.general", _requirements(frozenset({Capability.TEXT_GENERATION}))
    )
    assert decision.route is not None


@pytest.mark.asyncio
async def test_discovered_model_reconciliation_never_deletes_missing_models(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
        discovery_adapter_factories={
            "provider-a": lambda p, s: _FakeDiscoveryAdapter(
                [DiscoveredModel(model_id="discovered-1", display_name="discovered-1")]
            )
        },
    )
    await service.bootstrap(_canonical())

    refreshed = await service.refresh_models("provider-a")
    assert {m.model_id for m in refreshed} == {"model-old", "discovered-1"}
    discovered = next(m for m in refreshed if m.model_id == "discovered-1")
    assert discovered.enabled is False  # discovery alone never authorizes usage

    service._discovery_adapter_factories["provider-a"] = lambda p, s: (  # noqa: SLF001
        _FakeDiscoveryAdapter([])
    )
    refreshed_again = await service.refresh_models("provider-a")
    still_present = next(m for m in refreshed_again if m.model_id == "discovered-1")
    assert still_present.availability is ModelAvailability.UNAVAILABLE
    assert {m.model_id for m in refreshed_again} == {"model-old", "discovered-1"}


@pytest.mark.asyncio
async def test_discovered_only_capability_never_satisfies_hard_requirement(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.model_catalog_entries.add(
            ModelCatalogEntry(
                provider_id="provider-a",
                model_id="claims-vision",
                display_name="claims-vision",
                context_window=None,
                execution_location=ExecutionLocation.CLOUD,
                availability=ModelAvailability.AVAILABLE,
                enabled=True,
                discovery_source=DiscoverySource.DISCOVERED,
                capabilities=frozenset(
                    {
                        CapabilityClaim(
                            Capability.IMAGE_INPUT, CapabilityProvenance.DISCOVERED
                        )
                    }
                ),
                metadata={},
                last_seen_at=_FIXED_NOW,
                created_at=_FIXED_NOW,
                updated_at=_FIXED_NOW,
            )
        )
        await uow.commit()
    await service._rebuild_and_publish()  # noqa: SLF001

    with pytest.raises(AIConfigurationError, match="required capabilities"):
        await service.update_profile(
            "vision",
            ProfilePatch(
                bindings=(
                    ProfileBindingInput(
                        provider_id="provider-a", model_id="claims-vision", priority=1
                    ),
                )
            ),
        )


# ---------------------------------------------------------------------------
# Profiles, bindings, fallback, locality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_defaults_match_contract_v1_baseline(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    profiles = {p.key: p for p in await service.list_profiles()}
    assert set(profiles) == {"chat.general", "coding", "research", "vision", "realtime"}
    assert profiles["chat.general"].required_capabilities == frozenset(
        {Capability.TEXT_GENERATION}
    )
    assert profiles["coding"].required_capabilities == frozenset(
        {Capability.TEXT_GENERATION, Capability.TOOL_CALLING}
    )
    assert profiles["vision"].required_capabilities == frozenset(
        {Capability.IMAGE_INPUT}
    )
    assert profiles["realtime"].required_capabilities == frozenset(
        {Capability.REALTIME, Capability.AUDIO_INPUT, Capability.AUDIO_OUTPUT}
    )


@pytest.mark.asyncio
async def test_incompatible_binding_rejected_and_not_persisted(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    with pytest.raises(AIConfigurationError):
        await service.update_profile(
            "coding",
            ProfilePatch(
                bindings=(
                    ProfileBindingInput(
                        provider_id="provider-a", model_id="model-old", priority=1
                    ),
                )
            ),
        )

    bindings = await service.list_bindings("coding")
    assert bindings == ()


@pytest.mark.asyncio
async def test_unavailable_primary_binding_falls_back_and_preserves_original_binding(
    tmp_path: Path,
) -> None:
    """Contract v1 SS30 vertical: coding primary=model-old, secondary=model-new."""

    provider_a = ScriptedFakeProvider()
    provider_b = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("ok")])
    service, audit = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)
    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )

    decision = await service.route_with_audit(
        "coding",
        _requirements(),
        correlation_id=uuid4(),
        actor="Sofia/root",
        subject="agent-run",
        origin="AGENT_RUN",
    )
    assert decision.route is not None
    assert decision.route.descriptor.identity.provider_id == "provider-b"
    assert decision.reason_code is RoutingReasonCode.PROFILE_BINDING_SELECTED
    assert decision.fallback is False  # only configured binding, not a fallback tier

    # Now simulate model-new becoming unavailable while an OLDER, incompatible
    # canonical binding remains configured: routing must fail rather than
    # silently downgrade capabilities, and the original preference persists.
    async with service._uow_factory() as uow:  # noqa: SLF001
        entry = await uow.model_catalog_entries.get_by_identity(
            "provider-b", "model-new"
        )
        assert entry is not None
        from dataclasses import replace

        await uow.model_catalog_entries.save(
            replace(entry, availability=ModelAvailability.UNAVAILABLE)
        )
        await uow.commit()
    await service._rebuild_and_publish()  # noqa: SLF001

    failed_decision = service.preview_routing("coding", _requirements())
    assert failed_decision.route is None
    assert failed_decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL

    bindings = await service.list_bindings("coding")
    assert [b.provider_id for b in bindings] == ["provider-b"]
    assert bindings[0].model_id == "model-new"  # preference persisted, not deleted

    entries = await audit.query()
    assert any(entry.event_type == "AI_ROUTING_SELECTED" for entry in entries)


@pytest.mark.asyncio
async def test_local_only_request_never_falls_back_to_cloud(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())  # canonical model is CLOUD execution_location

    decision = service.preview_routing(
        "chat.general",
        _requirements(
            frozenset({Capability.TEXT_GENERATION}), locality=DataLocality.LOCAL_ONLY
        ),
    )
    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


@pytest.mark.asyncio
async def test_profile_disabled_fails_clearly(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    await service.update_profile("vision", ProfilePatch(enabled=False))

    decision = service.preview_routing(
        "vision", _requirements(frozenset({Capability.IMAGE_INPUT}))
    )
    assert decision.reason_code is RoutingReasonCode.INVALID_PROFILE


@pytest.mark.asyncio
async def test_invalid_profile_key_fails_clearly(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    decision = service.preview_routing("does-not-exist", _requirements())
    assert decision.reason_code is RoutingReasonCode.INVALID_PROFILE


@pytest.mark.asyncio
async def test_explicit_incompatible_override_does_not_silently_fall_through(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    provider_b = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)
    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )
    from sofias_assistant.ai.contracts import ModelIdentity

    incompatible_override = ModelIdentity(
        "provider-a", "model-old"
    )  # lacks TOOL_CALLING
    decision = service.preview_routing(
        "coding", _requirements(), model_override=incompatible_override
    )

    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.MISSING_REQUIRED_CAPABILITY


@pytest.mark.asyncio
async def test_canonical_fallback_only_when_compatible(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("ok")])
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    # chat.general has no bindings configured beyond the bootstrap one, and
    # its fallback policy is ORDERED_THEN_CANONICAL by default: removing the
    # binding must still let the canonical model itself serve as fallback.
    await service.update_profile("chat.general", ProfilePatch(bindings=()))
    decision = service.preview_routing(
        "chat.general", _requirements(frozenset({Capability.TEXT_GENERATION}))
    )
    assert decision.route is not None
    assert decision.reason_code is RoutingReasonCode.CANONICAL_FALLBACK_SELECTED

    # coding's canonical is the same text-only model: it is not tool-capable,
    # so the fallback must be rejected rather than silently accepted.
    decision = service.preview_routing("coding", _requirements())
    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


# ---------------------------------------------------------------------------
# Consumer integration: Conversation / Agents / Vision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coding_agent_uses_coding_profile_and_selected_provider(
    tmp_path: Path,
) -> None:
    from sofias_assistant.ai.fake import FakeAgentProvider

    provider_a = ScriptedFakeProvider()
    provider_b = FakeAgentProvider(lambda request, turn: ('{"summary": "done"}', ()))
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)
    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )

    execution = ExecutionRuntime(
        (await _session_factory(tmp_path)), artifact_root=tmp_path / "artifacts"
    )
    agent_runtime = AgentRuntime(execution)
    from sofias_assistant.execution import TaskRuntime

    task_runtime = TaskRuntime(execution)
    subject = "Sofia/root"
    from sofias_assistant.execution.development_analysis import (
        development_analysis_definition,
    )

    definition = await register_development_analysis(
        agent_runtime,
        service.routing_policy_for("coding"),
        definition=development_analysis_definition(
            provider_requirements={"locality": "cloud_allowed"}
        ),
    )
    task = await task_runtime.create_agent_task(
        objective="inspect", subject=subject, authority=AuthorityContext(subject)
    )
    run = await agent_runtime.create_agent_run(
        root_authority=agent_runtime.root_authority,
        task=task,
        definition=definition,
        delegated_context={"objective": "inspect", "workspace": str(tmp_path)},
        authority=AuthorityContext(subject),
        allowed_tools=frozenset(),
        workspace=str(tmp_path),
    )
    completed = await agent_runtime.run(run, AuthorityContext(subject), grants={})

    assert completed.status.value == "SUCCEEDED"
    assert len(provider_b.requests) == 1
    assert (
        len(provider_a.invocations()) == 0
    )  # coding never used the text-only canonical

    # AGENT_RUN routing audit is recorded through the Agent's own
    # ExecutionRuntime.audit, not through AIConfigurationService's audit.
    entries = await execution.audit.query()
    routing_entries = [e for e in entries if e.event_type == "AI_ROUTING_SELECTED"]
    assert any(e.metadata.get("profile") == "coding" for e in routing_entries)


@pytest.mark.asyncio
async def test_research_agent_uses_research_profile_and_selected_provider(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    provider_b = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("")])
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)
    await service.update_profile(
        "research",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )

    execution = ExecutionRuntime(
        (await _session_factory(tmp_path)), artifact_root=tmp_path / "artifacts"
    )
    agent_runtime = AgentRuntime(execution)
    from sofias_assistant.execution import TaskRuntime

    task_runtime = TaskRuntime(execution)
    subject = "Sofia/root"
    from sofias_assistant.execution.research import research_definition

    definition = await register_research(
        agent_runtime,
        service.routing_policy_for("research"),
        definition=research_definition(
            provider_requirements={"locality": "cloud_allowed"}
        ),
    )
    task = await task_runtime.create_agent_task(
        objective="research", subject=subject, authority=AuthorityContext(subject)
    )
    run = await agent_runtime.create_agent_run(
        root_authority=agent_runtime.root_authority,
        task=task,
        definition=definition,
        delegated_context={"objective": "research"},
        authority=AuthorityContext(subject),
        allowed_tools=frozenset(),
    )
    # Zero tool calls -> insufficient sources -> the Agent fails its own
    # business rule, but routing itself must still have selected provider-b.
    await agent_runtime.run(run, AuthorityContext(subject), grants={})

    assert len(provider_b.invocations()) == 1
    assert provider_b.invocations()[0].model.provider_id == "provider-b"
    assert len(provider_a.invocations()) == 0

    entries = await execution.audit.query()
    routing_entries = [e for e in entries if e.event_type == "AI_ROUTING_SELECTED"]
    assert any(e.metadata.get("profile") == "research" for e in routing_entries)


@pytest.mark.asyncio
async def test_vision_capability_requires_image_input_with_no_text_fallback(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    vision_provider = FakeVisionProvider()
    service, audit = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())
    execution = ExecutionRuntime(
        (await _session_factory(tmp_path)), artifact_root=tmp_path / "artifacts"
    )
    artifact = await execution.artifacts.create(
        b"\x89PNG", kind="screenshot", media_type="image/png"
    )
    vision = VisionCapability(
        execution.artifacts, service.routing_policy_for("vision"), audit=audit
    )

    with pytest.raises(Exception):  # NoCompatibleModelError: no IMAGE_INPUT model
        await vision.observe(
            artifact_id=artifact.id,
            prompt="describe",
            locality=DataLocality.CLOUD_ALLOWED,
        )

    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.provider_configurations.add(
            ProviderConfiguration(
                id="vision-provider",
                display_name="Vision Provider",
                adapter_type="vision-provider",
                base_url="https://vision.invalid/v1",
                enabled=True,
                execution_location=ExecutionLocation.CLOUD,
                credential_ref=None,
                created_at=_FIXED_NOW,
                updated_at=_FIXED_NOW,
            )
        )
        await uow.commit()
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.model_catalog_entries.add(
            ModelCatalogEntry(
                provider_id="vision-provider",
                model_id="vision-model",
                display_name="vision-model",
                context_window=None,
                execution_location=ExecutionLocation.CLOUD,
                availability=ModelAvailability.AVAILABLE,
                enabled=True,
                discovery_source=DiscoverySource.MANUAL,
                capabilities=frozenset(
                    {
                        CapabilityClaim(
                            Capability.IMAGE_INPUT,
                            CapabilityProvenance.BUILTIN_METADATA,
                        )
                    }
                ),
                metadata={},
                last_seen_at=_FIXED_NOW,
                created_at=_FIXED_NOW,
                updated_at=_FIXED_NOW,
            )
        )
        await uow.commit()
    service._provider_binding_factories["vision-provider"] = _binding_factory(  # noqa: SLF001
        ProviderBinding(vision=vision_provider)
    )
    await service._rebuild_and_publish()  # noqa: SLF001
    await service.update_profile(
        "vision",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="vision-provider", model_id="vision-model", priority=1
                ),
            )
        ),
    )

    response = await vision.observe(
        artifact_id=artifact.id, prompt="describe", locality=DataLocality.CLOUD_ALLOWED
    )
    assert "describe" in response.text
    assert len(vision_provider.requests) == 1

    entries = await audit.query()
    assert any(
        e.event_type == "AI_ROUTING_SELECTED" and e.metadata.get("profile") == "vision"
        for e in entries
    )


@pytest.mark.asyncio
async def test_realtime_profile_requires_full_audio_capability_set(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    # No realtime-capable model is configured: the profile's hard
    # requirements (REALTIME + AUDIO_INPUT + AUDIO_OUTPUT) must fail
    # closed rather than degrade to a text-only canonical model.
    decision = service.preview_routing(
        "realtime",
        _requirements(
            frozenset(
                {Capability.REALTIME, Capability.AUDIO_INPUT, Capability.AUDIO_OUTPUT}
            )
        ),
    )
    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


# ---------------------------------------------------------------------------
# Runtime reconfiguration / snapshot consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_update_takes_effect_without_restart(tmp_path: Path) -> None:
    provider_a = ScriptedFakeProvider()
    provider_b = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)
    policy = service.routing_policy_for("coding")

    before = policy.resolve(_requirements())
    assert before.route is None  # no binding configured yet

    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )

    after = policy.resolve(_requirements())  # same RoutingPolicy instance, no restart
    assert after.route is not None
    assert after.route.descriptor.identity.provider_id == "provider-b"


@pytest.mark.asyncio
async def test_routing_snapshot_is_immutable_and_in_flight_requests_keep_their_version(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    provider_b = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)

    captured_snapshot = service.current_snapshot()
    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )

    assert service.current_snapshot() is not captured_snapshot
    assert captured_snapshot.bindings.get("coding", ()) == ()  # old snapshot unaffected
    assert service.current_snapshot().bindings["coding"][0].identity.model_id == (
        "model-new"
    )


@pytest.mark.asyncio
async def test_failed_snapshot_rebuild_keeps_previous_snapshot_active(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())
    good_snapshot = service.current_snapshot()

    async def _boom() -> None:
        raise RuntimeError("simulated persistence outage during rebuild")

    service._rebuild_and_publish = _boom  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(SnapshotPublicationError):
        await service.update_profile("chat.general", ProfilePatch(enabled=True))

    assert service.current_snapshot() is good_snapshot


# ---------------------------------------------------------------------------
# Routing preview API / Audit / security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routing_preview_response_shape_has_no_secret_or_reasoning_fields(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    body = RoutingPreviewRequestBody(
        profile="chat.general",
        required_capabilities=["text_generation"],
        preferred_capabilities=[],
        locality="cloud_allowed",
        override=None,
    )
    from sofias_assistant.ai.contracts import AIRequestRequirements as _Req

    requirements = _Req(
        required_capabilities=frozenset(
            Capability(v) for v in body.required_capabilities
        ),
        preferred_capabilities=frozenset(),
        locality=DataLocality(body.locality),
    )
    decision = service.preview_routing("chat.general", requirements)
    payload = {
        "profile": decision.profile_key,
        "selected": {
            "provider_id": decision.route.descriptor.identity.provider_id,
            "model_id": decision.route.descriptor.identity.model_id,
        }
        if decision.route
        else None,
        "fallback": decision.fallback,
        "reason_code": decision.reason_code.value,
        "reason": decision.reason,
    }
    assert set(payload) == {"profile", "selected", "fallback", "reason_code", "reason"}
    assert "sk-a" not in str(payload)
    assert "api_key" not in str(payload).lower()


@pytest.mark.asyncio
async def test_audit_covers_provider_catalog_profile_and_routing_events(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, audit = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
        discovery_adapter_factories={
            "provider-a": lambda p, s: _FakeDiscoveryAdapter([])
        },
    )
    await service.bootstrap(_canonical())
    await service.refresh_models("provider-a")
    await service.update_profile("chat.general", ProfilePatch(enabled=True))
    await service.route_with_audit(
        "chat.general",
        _requirements(frozenset({Capability.TEXT_GENERATION})),
        correlation_id=uuid4(),
        actor="Sofia/root",
        subject="conversation",
        origin="CONVERSATION",
    )

    entries = await audit.query()
    event_types = {entry.event_type for entry in entries}
    assert {
        "AI_PROVIDER_CONFIG_CHANGED",
        "AI_MODEL_CATALOG_REFRESHED",
        "AI_PROFILE_CHANGED",
        "AI_ROUTING_SELECTED",
    } <= event_types
    for entry in entries:
        blob = f"{entry.metadata}{entry.authority_context}{entry.execution_context}"
        assert "sk-a" not in blob
        assert "api_key" not in blob.lower() or "api-key" in blob.lower()


@pytest.mark.asyncio
async def test_no_secret_leakage_in_provider_repr_or_credential_diagnostics(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider()
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            )
        },
    )
    await service.bootstrap(_canonical())

    providers = await service.list_providers()
    provider = providers[0]
    assert "sk-a" not in repr(provider)
    assert "sk-a" not in str(provider)
    assert service.is_credential_configured(provider.credential_ref) is True
    assert service.is_credential_configured(None) is False


@pytest.mark.asyncio
async def test_multi_provider_vertical_same_core_same_authority_model(
    tmp_path: Path,
) -> None:
    """Two provider identities, one Core: chat.general -> A, coding -> B."""

    provider_a = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("A")])
    provider_b = ScriptedFakeProvider(text_scripts=[FakeTextSuccess("B")])
    service, _ = await _service(
        tmp_path,
        provider_binding_factories={
            "provider-a": _binding_factory(
                ProviderBinding(text_generation=provider_a, text_streaming=provider_a)
            ),
            "provider-b": _binding_factory(ProviderBinding(text_generation=provider_b)),
        },
    )
    await service.bootstrap(_canonical())
    await _add_provider_b_with_coding_capable_model(service)
    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="provider-b", model_id="model-new", priority=1
                ),
            )
        ),
    )

    chat_decision = service.preview_routing(
        "chat.general", _requirements(frozenset({Capability.TEXT_GENERATION}))
    )
    coding_decision = service.preview_routing("coding", _requirements())

    assert chat_decision.route is not None
    assert coding_decision.route is not None
    assert chat_decision.route.descriptor.identity.provider_id == "provider-a"
    assert coding_decision.route.descriptor.identity.provider_id == "provider-b"


async def _session_factory(tmp_path: Path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational-agents.sqlite').as_posix()}"
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    return create_session_factory(engine)


# ---------------------------------------------------------------------------
# Human-facing diagnostic smoke: the real sofia-core host, real HTTP loopback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_facing_diagnostic_smoke_exposes_ai_configuration_over_http(
    tmp_path: Path,
) -> None:
    """Start the real production host and exercise the AI Configuration API.

    Reuses the exact `sofias_assistant.host.runner.run` lifecycle Gate I14
    proved (same composition `sofia-core` uses), with a fake OpenAI SDK
    transport standing in only for network I/O.
    """

    import socket
    from types import SimpleNamespace

    from sofias_assistant.client_app.api import CoreApiClient
    from sofias_assistant.host import runner
    from tests.integration.core.test_core import FakeSecretStore, fake_ownership_factory

    def free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    class FakeResponses:
        async def create(self, *, stream: bool = False, **kwargs: Any) -> Any:
            return SimpleNamespace(
                status="completed",
                output_text="ok",
                usage=None,
                output=(),
                _request_id=None,
            )

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

        async def close(self) -> None:
            return None

    import asyncio

    environment = {
        "SOFIA_DATA_DIR": str(tmp_path / "core-data"),
        "SOFIA_CORE_PORT": str(free_loopback_port()),
        "LLM_MODEL": "gate-i15-smoke-model",
        "LLM_API_KEY": "sk-smoke",
    }
    shutdown_event = asyncio.Event()
    ready: asyncio.Future[tuple[Any, Any]] = asyncio.get_running_loop().create_future()

    def on_ready(access: Any, core: Any) -> None:
        if not ready.done():
            ready.set_result((access, core))

    task = asyncio.create_task(
        runner.run(
            environment=environment,
            env_file=None,
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=fake_ownership_factory,
            client_factory=lambda api_key: FakeOpenAIClient(),
            shutdown_event=shutdown_event,
            on_ready=on_ready,
            install_signal_handlers=False,
        )
    )
    waitable: set[asyncio.Future[Any]] = {task, ready}
    done, _pending = await asyncio.wait(waitable, return_when=asyncio.FIRST_COMPLETED)
    if task in done and not ready.done():
        raise AssertionError(f"host failed to reach READY (exit code {task.result()})")
    access, core = await ready
    try:
        client = CoreApiClient(
            f"http://127.0.0.1:{access.port}", access.credential.reveal()
        )

        def _call_api() -> tuple[Any, Any, Any, Any]:
            client.connect()
            providers = client._get("/api/v1/ai/providers")
            models = client._get("/api/v1/ai/models")
            profiles = client._get("/api/v1/ai/profiles")
            preview = client._post(
                "/api/v1/ai/routing/preview",
                {
                    "profile": "chat.general",
                    "required_capabilities": ["text_generation"],
                    "preferred_capabilities": [],
                    "locality": "cloud_allowed",
                },
            )
            return providers, models, profiles, preview

        try:
            # CoreApiClient is a blocking httpx client; run it off the event
            # loop the in-process ASGI server needs to answer these requests.
            providers_raw, models_raw, profiles_raw, preview = await asyncio.to_thread(
                _call_api
            )
        finally:
            client.close()
    finally:
        shutdown_event.set()
        await task

    assert isinstance(providers_raw, list)
    assert isinstance(models_raw, list)
    assert isinstance(profiles_raw, list)
    providers: list[dict[str, Any]] = providers_raw
    models: list[dict[str, Any]] = models_raw
    profiles: list[dict[str, Any]] = profiles_raw

    assert providers and providers[0]["id"] == "openai"
    assert providers[0]["credential"]["configured"] is True
    assert "sk-smoke" not in str(providers)
    assert any(model["model_id"] == "gate-i15-smoke-model" for model in models)
    assert {profile["key"] for profile in profiles} == {
        "chat.general",
        "coding",
        "research",
        "vision",
        "realtime",
    }
    assert preview["selected"] == {
        "provider_id": "openai",
        "model_id": "gate-i15-smoke-model",
    }
    assert preview["reason_code"] == "profile_binding_selected"
