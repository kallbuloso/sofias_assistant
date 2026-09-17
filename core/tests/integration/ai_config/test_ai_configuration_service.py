"""AIConfigurationService integration coverage against a real SQLite DB (Gate I15)."""

from __future__ import annotations

from asyncio import to_thread
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    Capability,
    CapabilityProvenance,
    DataLocality,
    ExecutionLocation,
)
from sofias_assistant.ai.discovery import DiscoveredModel
from sofias_assistant.ai.registry import ModelAvailability, ProviderBinding
from sofias_assistant.ai.routing_policy import FallbackPolicy, RoutingReasonCode
from sofias_assistant.ai_config.models import CapabilityClaim, ProviderConfiguration
from sofias_assistant.ai_config.service import (
    AIConfigurationError,
    AIConfigurationService,
    CanonicalBootstrap,
    ProfileBindingInput,
    ProfileNotFoundError,
    ProfilePatch,
    ProviderNotFoundError,
    ProviderPatch,
)
from sofias_assistant.execution.audit import AuditService
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore


class _FakeSecretStore(SecretStore):
    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


class _FakeProvider:
    """Structural stand-in never actually invoked by these tests."""


def _fake_binding_factory(
    _: ProviderConfiguration, __: SecretService
) -> ProviderBinding:
    provider = _FakeProvider()
    return ProviderBinding(
        text_generation=provider,  # type: ignore[arg-type]
        text_streaming=provider,  # type: ignore[arg-type]
    )


class _FakeDiscoveryAdapter:
    def __init__(self, models: list[DiscoveredModel]) -> None:
        self._models = models

    async def discover_models(self) -> list[DiscoveredModel]:
        return self._models


def _fixed_clock() -> datetime:
    return datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


async def _build_service(
    tmp_path: Path,
    *,
    discovery_models: list[DiscoveredModel] | None = None,
    audit: AuditService | None = None,
) -> AIConfigurationService:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    secret_service = SecretService(_FakeSecretStore())
    secret_service.set(SecretRef("providers/fake/api-key"), SecretValue("sk-fake"))
    discovery_factories = (
        {"fake": lambda provider, secrets: _FakeDiscoveryAdapter(discovery_models)}
        if discovery_models is not None
        else {}
    )
    return AIConfigurationService(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        secret_service=secret_service,
        provider_binding_factories={"fake": _fake_binding_factory},
        discovery_adapter_factories=discovery_factories,
        audit=audit,
        clock=_fixed_clock,
    )


def _canonical(
    provider_id: str = "fake", model_id: str = "gate-i15-canonical"
) -> CanonicalBootstrap:
    return CanonicalBootstrap(
        provider_id=provider_id,
        display_name="Fake",
        adapter_type="fake",
        base_url="https://fake.invalid/v1",
        execution_location=ExecutionLocation.CLOUD,
        credential_ref=SecretRef(f"providers/{provider_id}/api-key"),
        model_id=model_id,
        model_display_name=model_id,
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


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_and_seeds_usable_chat_general_snapshot(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    canonical = _canonical()

    await service.bootstrap(canonical)
    await service.bootstrap(canonical)  # idempotent: must not duplicate rows

    providers = await service.list_providers()
    models = await service.list_models()
    profiles = await service.list_profiles()
    assert [p.id for p in providers] == ["fake"]
    assert len(models) == 1
    assert {p.key for p in profiles} == {
        "chat.general",
        "coding",
        "research",
        "vision",
        "realtime",
    }

    decision = service.preview_routing(
        "chat.general",
        AIRequestRequirements(
            required_capabilities=frozenset({Capability.TEXT_GENERATION}),
            preferred_capabilities=frozenset(),
            locality=DataLocality.CLOUD_ALLOWED,
        ),
    )
    assert decision.route is not None
    assert decision.route.descriptor.identity.provider_id == "fake"


@pytest.mark.asyncio
async def test_bootstrap_never_overwrites_explicit_user_configuration(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    canonical = _canonical()
    await service.bootstrap(canonical)

    await service.update_profile(
        "chat.general", ProfilePatch(fallback_policy=FallbackPolicy.ORDERED_ONLY)
    )
    await service.bootstrap(canonical)  # simulate a second process boot

    profile = await service.get_profile("chat.general")
    assert profile is not None
    assert profile.fallback_policy is FallbackPolicy.ORDERED_ONLY


@pytest.mark.asyncio
async def test_coding_profile_has_no_eligible_candidate_from_canonical_alone(
    tmp_path: Path,
) -> None:
    """Canonical only proves TEXT_GENERATION/TEXT_STREAMING; coding needs TOOL_CALLING."""

    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    decision = service.preview_routing(
        "coding",
        AIRequestRequirements(
            required_capabilities=frozenset(),
            preferred_capabilities=frozenset(),
            locality=DataLocality.CLOUD_ALLOWED,
        ),
    )
    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


@pytest.mark.asyncio
async def test_update_profile_rejects_incompatible_binding(tmp_path: Path) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(AIConfigurationError, match="unknown model"):
        await service.update_profile(
            "coding",
            ProfilePatch(
                bindings=(
                    ProfileBindingInput(
                        provider_id="fake", model_id="does-not-exist", priority=1
                    ),
                )
            ),
        )

    with pytest.raises(AIConfigurationError, match="required capabilities"):
        await service.update_profile(
            "coding",
            ProfilePatch(
                bindings=(
                    ProfileBindingInput(
                        provider_id="fake",
                        model_id="gate-i15-canonical",
                        priority=1,
                    ),
                )
            ),
        )


@pytest.mark.asyncio
async def test_update_profile_unknown_key_fails_clearly(tmp_path: Path) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(ProfileNotFoundError):
        await service.update_profile("does-not-exist", ProfilePatch(enabled=False))


@pytest.mark.asyncio
async def test_update_profile_accepts_compatible_binding_and_takes_effect(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())
    async with service._uow_factory() as uow:  # noqa: SLF001
        from sofias_assistant.ai_config.models import DiscoverySource, ModelCatalogEntry

        uow.model_catalog_entries.add(
            ModelCatalogEntry(
                provider_id="fake",
                model_id="coding-capable",
                display_name="coding-capable",
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
                last_seen_at=_fixed_clock(),
                created_at=_fixed_clock(),
                updated_at=_fixed_clock(),
            )
        )
        await uow.commit()
    # The newly added model is not yet visible to routing until reconciled.
    await service._rebuild_and_publish()  # noqa: SLF001

    await service.update_profile(
        "coding",
        ProfilePatch(
            bindings=(
                ProfileBindingInput(
                    provider_id="fake", model_id="coding-capable", priority=1
                ),
            )
        ),
    )

    decision = service.preview_routing(
        "coding",
        AIRequestRequirements(
            required_capabilities=frozenset(),
            preferred_capabilities=frozenset(),
            locality=DataLocality.CLOUD_ALLOWED,
        ),
    )
    assert decision.route is not None
    assert decision.route.descriptor.identity.model_id == "coding-capable"
    assert decision.reason_code.value == "profile_binding_selected"


@pytest.mark.asyncio
async def test_refresh_models_reconciles_without_deleting_missing_models(
    tmp_path: Path,
) -> None:
    service = await _build_service(
        tmp_path,
        discovery_models=[
            DiscoveredModel(model_id="new-model", display_name="new-model")
        ],
    )
    await service.bootstrap(_canonical())

    refreshed = await service.refresh_models("fake")
    model_ids = {entry.model_id for entry in refreshed}
    assert "new-model" in model_ids
    assert "gate-i15-canonical" in model_ids  # bootstrap model untouched

    new_entry = next(entry for entry in refreshed if entry.model_id == "new-model")
    assert new_entry.discovery_source.value == "discovered"
    assert new_entry.availability is ModelAvailability.AVAILABLE
    assert new_entry.enabled is False  # discovery never auto-authorizes usage

    # Second refresh with an empty discovery result must not delete "new-model";
    # it must be marked unavailable instead (Contract v1 SS17/SS38).
    service._discovery_adapter_factories["fake"] = lambda provider, secrets: (  # noqa: SLF001
        _FakeDiscoveryAdapter([])
    )
    refreshed_again = await service.refresh_models("fake")
    still_present = next(
        entry for entry in refreshed_again if entry.model_id == "new-model"
    )
    assert still_present.availability is ModelAvailability.UNAVAILABLE


@pytest.mark.asyncio
async def test_refresh_models_unknown_provider_fails_clearly(tmp_path: Path) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(AIConfigurationError):
        await service.refresh_models("does-not-exist")


@pytest.mark.asyncio
async def test_route_with_audit_emits_selected_and_failed_events(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    audit = AuditService(session_factory)
    service = await _build_service(tmp_path, audit=audit)
    await service.bootstrap(_canonical())

    from uuid import uuid4

    ok_requirements = AIRequestRequirements(
        required_capabilities=frozenset({Capability.TEXT_GENERATION}),
        preferred_capabilities=frozenset(),
        locality=DataLocality.CLOUD_ALLOWED,
    )
    decision = await service.route_with_audit(
        "chat.general",
        ok_requirements,
        correlation_id=uuid4(),
        actor="Sofia/root",
        subject="conversation",
        origin="CONVERSATION",
    )
    assert decision.route is not None

    failing_requirements = AIRequestRequirements(
        required_capabilities=frozenset({Capability.IMAGE_INPUT}),
        preferred_capabilities=frozenset(),
        locality=DataLocality.CLOUD_ALLOWED,
    )
    await service.route_with_audit(
        "vision",
        failing_requirements,
        correlation_id=uuid4(),
        actor="Sofia/root",
        subject="vision",
        origin="VISION",
    )

    entries = await audit.query()
    event_types = {entry.event_type for entry in entries}
    assert "AI_ROUTING_SELECTED" in event_types
    assert "AI_ROUTING_FAILED" in event_types
    for entry in entries:
        assert "api" not in str(entry.metadata).lower() or "api_key" not in str(
            entry.metadata
        )
        assert "sk-fake" not in str(entry.metadata)
        assert "sk-fake" not in str(entry.authority_context)


@pytest.mark.asyncio
async def test_no_secret_leakage_in_provider_repr_or_listing(tmp_path: Path) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    providers = await service.list_providers()
    assert len(providers) == 1
    provider = providers[0]
    assert "sk-fake" not in repr(provider)
    assert provider.credential_ref is not None
    assert provider.credential_ref.identifier == "providers/fake/api-key"
    assert service.is_credential_configured(provider.credential_ref) is True


@pytest.mark.asyncio
async def test_update_provider_applies_enabled_and_base_url_and_republishes(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    updated = await service.update_provider(
        "fake",
        ProviderPatch(base_url="https://fake.invalid/v2", enabled=False),
    )

    assert updated.base_url == "https://fake.invalid/v2"
    assert updated.enabled is False
    providers = await service.list_providers()
    assert providers[0].base_url == "https://fake.invalid/v2"
    assert providers[0].enabled is False
    # A disabled provider makes its model ineligible: routing must reflect it.
    decision = service.preview_routing(
        "chat.general",
        AIRequestRequirements(
            required_capabilities=frozenset({Capability.TEXT_GENERATION}),
            preferred_capabilities=frozenset(),
            locality=DataLocality.CLOUD_ALLOWED,
        ),
    )
    assert decision.route is None


@pytest.mark.asyncio
async def test_update_provider_rejects_unknown_provider_id(tmp_path: Path) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(ProviderNotFoundError):
        await service.update_provider("does-not-exist", ProviderPatch(enabled=False))


@pytest.mark.asyncio
async def test_update_provider_rejects_an_unsafe_base_url(tmp_path: Path) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(AIConfigurationError):
        await service.update_provider(
            "fake", ProviderPatch(base_url="https://user:pass@fake.invalid")
        )


@pytest.mark.asyncio
async def test_set_provider_credential_derives_ref_and_writes_through_secret_service(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    status = await service.set_provider_credential("fake", SecretValue("sk-new"))

    assert status.provider_id == "fake"
    assert status.credential_ref == "providers/fake/api-key"
    assert status.configured is True
    assert status.effective_source == "platform_store"
    assert status.writable_source == "platform_store"
    assert status.shadowed is False


@pytest.mark.asyncio
async def test_set_provider_credential_rejects_unknown_provider_id(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(ProviderNotFoundError):
        await service.set_provider_credential("does-not-exist", SecretValue("sk-x"))


@pytest.mark.asyncio
async def test_delete_provider_credential_removes_the_platform_store_value(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())
    await service.set_provider_credential("fake", SecretValue("sk-new"))

    status = await service.delete_provider_credential("fake")

    assert status.configured is False
    assert status.effective_source == "missing"


@pytest.mark.asyncio
async def test_delete_provider_credential_rejects_unknown_provider_id(
    tmp_path: Path,
) -> None:
    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())

    with pytest.raises(ProviderNotFoundError):
        await service.delete_provider_credential("does-not-exist")


@pytest.mark.asyncio
async def test_provider_credential_write_never_reaches_snapshot_rebuild_lock(
    tmp_path: Path,
) -> None:
    """Credential writes never invalidate the routing snapshot: adapters
    resolve the secret through SecretService at call time, not at
    snapshot-build time, so the previously published snapshot stays valid.
    """

    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())
    snapshot_before = service.current_snapshot()

    await service.set_provider_credential("fake", SecretValue("sk-new"))

    assert service.current_snapshot() is snapshot_before


@pytest.mark.asyncio
async def test_attach_audit_enables_previously_silent_audit_emission(
    tmp_path: Path,
) -> None:
    """`build_conversation_dependencies_factory` constructs this service

    before the Core-composed `AuditService` exists; `attach_audit` is how
    `SofiaCore._compose_conversation_runtime` binds it afterwards. Before
    that call, Audit emission is a safe no-op rather than an error.
    """

    service = await _build_service(tmp_path)
    await service.bootstrap(_canonical())  # audit is None: must not raise

    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    audit = AuditService(session_factory)
    service.attach_audit(audit)

    await service.update_provider("fake", ProviderPatch(enabled=False))

    entries = await audit.query()
    assert any(entry.event_type == "AI_PROVIDER_CONFIG_CHANGED" for entry in entries)


@pytest.mark.asyncio
async def test_provider_credential_audit_never_contains_secret_value(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    session_factory = create_session_factory(engine)
    audit = AuditService(session_factory)
    service = await _build_service(tmp_path, audit=audit)
    await service.bootstrap(_canonical())

    await service.set_provider_credential("fake", SecretValue("sk-super-secret-value"))
    await service.delete_provider_credential("fake")

    entries = await audit.query()
    event_types = {entry.event_type for entry in entries}
    assert "PROVIDER_CREDENTIAL_UPDATED" in event_types
    assert "PROVIDER_CREDENTIAL_DELETED" in event_types
    for entry in entries:
        assert "sk-super-secret-value" not in str(entry.metadata)
        assert "sk-super-secret-value" not in str(entry.authority_context)
