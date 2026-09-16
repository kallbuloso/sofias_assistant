"""Deterministic profile-aware routing policy semantics (Gate I15)."""

from __future__ import annotations

from dataclasses import dataclass

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
)
from sofias_assistant.ai.registry import (
    ModelAvailability,
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import (
    CapabilityRouter,
    IncompatibleModelOverrideError,
    NoCompatibleModelError,
)
from sofias_assistant.ai.routing_policy import (
    BindingSpec,
    FallbackPolicy,
    InvalidProfileError,
    ModelDiagnostic,
    ProfileSpec,
    RoutingPolicy,
    RoutingReasonCode,
    RoutingSnapshot,
)


@dataclass(frozen=True, slots=True)
class _FakeTextProvider:
    """Structural stand-in; RoutingPolicy never invokes a provider."""


def _identity(provider_id: str, model_id: str) -> ModelIdentity:
    return ModelIdentity(provider_id, model_id)


def _register(
    registry: ModelRegistry,
    *,
    identity: ModelIdentity,
    capabilities: frozenset[Capability],
    execution_location: ExecutionLocation = ExecutionLocation.CLOUD,
    enabled: bool = True,
    availability: ModelAvailability = ModelAvailability.AVAILABLE,
) -> None:
    provider = _FakeTextProvider()
    registry.register(
        ModelRegistration(
            descriptor=ModelDescriptor(
                identity=identity,
                capabilities=capabilities,
                execution_location=execution_location,
            ),
            binding=ProviderBinding(text_generation=provider),  # type: ignore[arg-type]
            enabled=enabled,
            availability=availability,
        )
    )


def _diagnostic(
    *,
    provider_enabled: bool = True,
    model_known: bool = True,
    model_enabled: bool = True,
    availability: ModelAvailability | None = ModelAvailability.AVAILABLE,
    execution_location: ExecutionLocation | None = ExecutionLocation.CLOUD,
    adapter_incompatible: bool = False,
) -> ModelDiagnostic:
    return ModelDiagnostic(
        provider_enabled=provider_enabled,
        model_known=model_known,
        model_enabled=model_enabled,
        availability=availability,
        execution_location=execution_location,
        adapter_incompatible=adapter_incompatible,
    )


def _requirements(
    required: frozenset[Capability] = frozenset(),
    locality: DataLocality = DataLocality.CLOUD_ALLOWED,
) -> AIRequestRequirements:
    return AIRequestRequirements(
        required_capabilities=required,
        preferred_capabilities=frozenset(),
        locality=locality,
    )


def test_explicit_override_selected_bypasses_bindings() -> None:
    registry = ModelRegistry()
    good = _identity("openai", "good")
    _register(
        registry, identity=good, capabilities=frozenset({Capability.TEXT_GENERATION})
    )
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={},
        canonical=None,
        router=CapabilityRouter(registry),
        diagnostics={good: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    decision = policy.resolve(_requirements(), model_override=good)

    assert decision.reason_code is RoutingReasonCode.EXPLICIT_OVERRIDE_SELECTED
    assert decision.fallback is False
    assert decision.route is not None
    assert decision.route.descriptor.identity == good


def test_explicit_override_incompatible_fails_without_fallthrough() -> None:
    registry = ModelRegistry()
    text_only = _identity("openai", "text-only")
    fallback_capable = _identity("openai", "capable")
    _register(
        registry,
        identity=text_only,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
    )
    _register(
        registry,
        identity=fallback_capable,
        capabilities=frozenset({Capability.TEXT_GENERATION, Capability.TOOL_CALLING}),
    )
    snapshot = RoutingSnapshot(
        profiles={
            "coding": ProfileSpec(
                key="coding",
                required_capabilities=frozenset(
                    {Capability.TEXT_GENERATION, Capability.TOOL_CALLING}
                ),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={
            "coding": (
                BindingSpec(identity=fallback_capable, priority=1, enabled=True),
            )
        },
        canonical=None,
        router=CapabilityRouter(registry),
        diagnostics={
            text_only: _diagnostic(),
            fallback_capable: _diagnostic(),
        },
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="coding")

    decision = policy.resolve(_requirements(), model_override=text_only)

    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.MISSING_REQUIRED_CAPABILITY
    assert decision.fallback is False


def test_profile_bindings_are_tried_in_priority_order_with_fallback_flag() -> None:
    registry = ModelRegistry()
    disabled = _identity("openai", "disabled-model")
    healthy = _identity("openai", "healthy-model")
    _register(
        registry,
        identity=disabled,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
        enabled=False,
    )
    _register(
        registry, identity=healthy, capabilities=frozenset({Capability.TEXT_GENERATION})
    )
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={
            "chat.general": (
                BindingSpec(identity=disabled, priority=1, enabled=True),
                BindingSpec(identity=healthy, priority=2, enabled=True),
            )
        },
        canonical=None,
        router=CapabilityRouter(registry),
        diagnostics={
            disabled: _diagnostic(model_enabled=False),
            healthy: _diagnostic(),
        },
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    decision = policy.resolve(_requirements())

    assert decision.reason_code is RoutingReasonCode.PROFILE_BINDING_SELECTED
    assert decision.route is not None
    assert decision.route.descriptor.identity == healthy
    assert decision.fallback is True


def test_first_eligible_binding_is_not_reported_as_fallback() -> None:
    registry = ModelRegistry()
    primary = _identity("openai", "primary")
    _register(
        registry, identity=primary, capabilities=frozenset({Capability.TEXT_GENERATION})
    )
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={
            "chat.general": (BindingSpec(identity=primary, priority=1, enabled=True),)
        },
        canonical=None,
        router=CapabilityRouter(registry),
        diagnostics={primary: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    decision = policy.resolve(_requirements())

    assert decision.fallback is False
    assert decision.reason_code is RoutingReasonCode.PROFILE_BINDING_SELECTED


def test_ordered_only_never_falls_back_to_canonical() -> None:
    registry = ModelRegistry()
    canonical = _identity("openai", "canonical")
    _register(
        registry,
        identity=canonical,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
    )
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={},
        canonical=canonical,
        router=CapabilityRouter(registry),
        diagnostics={canonical: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    decision = policy.resolve(_requirements())

    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


def test_ordered_then_canonical_falls_back_when_compatible() -> None:
    registry = ModelRegistry()
    canonical = _identity("openai", "canonical")
    _register(
        registry,
        identity=canonical,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
    )
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_THEN_CANONICAL,
            )
        },
        bindings={},
        canonical=canonical,
        router=CapabilityRouter(registry),
        diagnostics={canonical: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    decision = policy.resolve(_requirements())

    assert decision.route is not None
    assert decision.route.descriptor.identity == canonical
    assert decision.reason_code is RoutingReasonCode.CANONICAL_FALLBACK_SELECTED
    assert decision.fallback is True


def test_canonical_fallback_rejected_when_incompatible() -> None:
    registry = ModelRegistry()
    canonical = _identity("openai", "canonical-text-only")
    _register(
        registry,
        identity=canonical,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
    )
    snapshot = RoutingSnapshot(
        profiles={
            "coding": ProfileSpec(
                key="coding",
                required_capabilities=frozenset(
                    {Capability.TEXT_GENERATION, Capability.TOOL_CALLING}
                ),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_THEN_CANONICAL,
            )
        },
        bindings={},
        canonical=canonical,
        router=CapabilityRouter(registry),
        diagnostics={canonical: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="coding")

    decision = policy.resolve(_requirements())

    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


def test_local_only_request_narrows_cloud_preferred_profile() -> None:
    registry = ModelRegistry()
    cloud_model = _identity("openai", "cloud-model")
    _register(
        registry,
        identity=cloud_model,
        capabilities=frozenset({Capability.TEXT_GENERATION}),
        execution_location=ExecutionLocation.CLOUD,
    )
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_PREFERRED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={
            "chat.general": (
                BindingSpec(identity=cloud_model, priority=1, enabled=True),
            )
        },
        canonical=None,
        router=CapabilityRouter(registry),
        diagnostics={cloud_model: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    decision = policy.resolve(_requirements(locality=DataLocality.LOCAL_ONLY))

    assert decision.route is None
    assert decision.reason_code is RoutingReasonCode.NO_COMPATIBLE_MODEL


def test_disabled_profile_reports_invalid_profile() -> None:
    snapshot = RoutingSnapshot(
        profiles={
            "vision": ProfileSpec(
                key="vision",
                required_capabilities=frozenset({Capability.IMAGE_INPUT}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=False,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={},
        canonical=None,
        router=CapabilityRouter(ModelRegistry()),
        diagnostics={},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="vision")

    decision = policy.resolve(_requirements())

    assert decision.reason_code is RoutingReasonCode.INVALID_PROFILE


def test_unknown_profile_key_reports_invalid_profile() -> None:
    snapshot = RoutingSnapshot(
        profiles={},
        bindings={},
        canonical=None,
        router=CapabilityRouter(ModelRegistry()),
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="does-not-exist")

    decision = policy.resolve(_requirements())

    assert decision.reason_code is RoutingReasonCode.INVALID_PROFILE
    assert decision.route is None


def test_effective_requirements_are_union_of_consumer_and_profile() -> None:
    registry = ModelRegistry()
    weak = _identity("openai", "weak")
    strong = _identity("openai", "strong")
    _register(
        registry, identity=weak, capabilities=frozenset({Capability.TEXT_GENERATION})
    )
    _register(
        registry,
        identity=strong,
        capabilities=frozenset({Capability.TEXT_GENERATION, Capability.TOOL_CALLING}),
    )
    snapshot = RoutingSnapshot(
        profiles={
            "coding": ProfileSpec(
                key="coding",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={
            "coding": (
                BindingSpec(identity=weak, priority=1, enabled=True),
                BindingSpec(identity=strong, priority=2, enabled=True),
            )
        },
        canonical=None,
        router=CapabilityRouter(registry),
        diagnostics={weak: _diagnostic(), strong: _diagnostic()},
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="coding")

    # The consumer (an Agent) adds its own hard requirement beyond the
    # profile's own declared required_capabilities: TOOL_CALLING. The union
    # must exclude `weak`, never silently accept the weaker profile-only set.
    decision = policy.resolve(
        _requirements(required=frozenset({Capability.TOOL_CALLING}))
    )

    assert decision.route is not None
    assert decision.route.descriptor.identity == strong
    assert decision.fallback is True


def test_route_wrapper_matches_capability_router_exception_contract() -> None:
    registry = ModelRegistry()
    snapshot = RoutingSnapshot(
        profiles={
            "chat.general": ProfileSpec(
                key="chat.general",
                required_capabilities=frozenset({Capability.TEXT_GENERATION}),
                preferred_capabilities=frozenset(),
                locality=DataLocality.CLOUD_ALLOWED,
                enabled=True,
                fallback_policy=FallbackPolicy.ORDERED_ONLY,
            )
        },
        bindings={},
        canonical=None,
        router=CapabilityRouter(registry),
    )
    policy = RoutingPolicy(lambda: snapshot, profile_key="chat.general")

    try:
        policy.route(_requirements())
        raise AssertionError("expected NoCompatibleModelError")
    except NoCompatibleModelError:
        pass

    missing = _identity("openai", "missing")
    try:
        policy.route(_requirements(), model_override=missing)
        raise AssertionError("expected IncompatibleModelOverrideError")
    except IncompatibleModelOverrideError:
        pass

    unknown_profile_policy = RoutingPolicy(lambda: snapshot, profile_key="unknown")
    try:
        unknown_profile_policy.route(_requirements())
        raise AssertionError("expected InvalidProfileError")
    except InvalidProfileError:
        pass
