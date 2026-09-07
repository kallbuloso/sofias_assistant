"""Unit tests for deterministic in-memory model registration and routing."""

from dataclasses import FrozenInstanceError, fields
from typing import Never

import pytest

from sofias_assistant.ai import (
    AIRequestRequirements,
    Capability,
    CapabilityRouter,
    DataLocality,
    ExecutionLocation,
    IncompatibleModelOverrideError,
    ModelAlreadyRegisteredError,
    ModelAvailability,
    ModelDescriptor,
    ModelIdentity,
    ModelNotRegisteredError,
    ModelRegistration,
    ModelRegistry,
    NoCompatibleModelError,
    ProviderBinding,
)
from sofias_assistant.ai.contracts import (
    AIRequest,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextResponse,
)


class FailingProvider:
    """Structural stub that makes accidental provider invocation visible."""

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        self._fail()

    def stream_text(self, *, model: ModelIdentity, request: AIRequest) -> Never:
        self._fail()

    async def generate_structured_output(
        self,
        *,
        model: ModelIdentity,
        request: AIRequest,
        spec: StructuredOutputSpec,
    ) -> StructuredOutputResult:
        self._fail()

    @staticmethod
    def _fail() -> Never:
        raise AssertionError("Router must not invoke a provider binding")


class SentinelProvider(FailingProvider):
    def __repr__(self) -> str:
        return "provider-adapter-super-secret-sentinel"


def _identity(provider_id: str, model_id: str) -> ModelIdentity:
    return ModelIdentity(provider_id=provider_id, model_id=model_id)


def _registration(
    provider_id: str,
    model_id: str,
    *,
    capabilities: frozenset[Capability] = frozenset({Capability.TEXT_GENERATION}),
    location: ExecutionLocation = ExecutionLocation.CLOUD,
    binding: ProviderBinding | None = None,
    enabled: bool = True,
    availability: ModelAvailability = ModelAvailability.AVAILABLE,
) -> ModelRegistration:
    provider = FailingProvider()
    return ModelRegistration(
        descriptor=ModelDescriptor(
            identity=_identity(provider_id, model_id),
            capabilities=capabilities,
            execution_location=location,
        ),
        binding=(
            ProviderBinding(text_generation=provider) if binding is None else binding
        ),
        enabled=enabled,
        availability=availability,
    )


def _requirements(
    *,
    required: frozenset[Capability] = frozenset({Capability.TEXT_GENERATION}),
    preferred: frozenset[Capability] = frozenset(),
    locality: DataLocality = DataLocality.CLOUD_ALLOWED,
) -> AIRequestRequirements:
    return AIRequestRequirements(required, preferred, locality)


def test_registry_registration_errors_and_immutable_read_model() -> None:
    registry = ModelRegistry()
    registration = _registration("provider", "model")
    identity = registration.descriptor.identity

    registry.register(registration)

    assert registry.get(identity) is registration
    assert registry.registrations() == (registration,)
    with pytest.raises(ModelAlreadyRegisteredError, match="already registered"):
        registry.register(registration)
    with pytest.raises(ModelNotRegisteredError, match="not registered"):
        registry.get(_identity("unknown", "model"))
    with pytest.raises(ModelNotRegisteredError, match="not registered"):
        registry.set_enabled(_identity("unknown", "model"), False)
    with pytest.raises(FrozenInstanceError):
        setattr(registration, "enabled", False)

    registry.set_enabled(identity, False)

    assert registration.enabled is True
    assert registry.get(identity).enabled is False


def test_static_model_descriptor_does_not_include_runtime_registration_state() -> None:
    descriptor_field_names = {field.name for field in fields(ModelDescriptor)}

    assert descriptor_field_names == {
        "identity",
        "capabilities",
        "execution_location",
        "context_window",
    }


@pytest.mark.parametrize(
    ("capability", "binding", "message"),
    [
        (Capability.TEXT_GENERATION, ProviderBinding(), "text_generation"),
        (Capability.TEXT_STREAMING, ProviderBinding(), "text_streaming"),
        (Capability.STRUCTURED_OUTPUT, ProviderBinding(), "structured_output"),
        (Capability.TOOL_CALLING, ProviderBinding(), "text generation or streaming"),
    ],
)
def test_registration_requires_binding_for_declared_capabilities(
    capability: Capability, binding: ProviderBinding, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _registration(
            "provider", "model", capabilities=frozenset({capability}), binding=binding
        )


def test_registration_accepts_coherent_tool_calling_text_binding() -> None:
    registration = _registration(
        "provider",
        "model",
        capabilities=frozenset({Capability.TOOL_CALLING}),
    )

    assert registration.binding.text_generation is not None


def test_disabled_and_unavailable_models_are_excluded_then_reenabled() -> None:
    registry = ModelRegistry()
    registration = _registration("provider", "model")
    registry.register(registration)
    router = CapabilityRouter(registry)

    registry.set_enabled(registration.descriptor.identity, False)
    with pytest.raises(NoCompatibleModelError):
        router.route(_requirements())

    registry.set_enabled(registration.descriptor.identity, True)
    registry.set_availability(
        registration.descriptor.identity, ModelAvailability.UNAVAILABLE
    )
    with pytest.raises(NoCompatibleModelError):
        router.route(_requirements())

    registry.set_availability(
        registration.descriptor.identity, ModelAvailability.AVAILABLE
    )

    assert (
        router.route(_requirements()).descriptor.identity
        == registration.descriptor.identity
    )


def test_required_capabilities_are_hard_eligibility() -> None:
    registry = ModelRegistry()
    text = _registration("provider", "text")
    structured = _registration(
        "provider",
        "structured",
        capabilities=frozenset(
            {Capability.TEXT_GENERATION, Capability.STRUCTURED_OUTPUT}
        ),
        binding=ProviderBinding(
            text_generation=FailingProvider(), structured_output=FailingProvider()
        ),
    )
    registry.register(text)
    registry.register(structured)
    router = CapabilityRouter(registry)

    route = router.route(
        _requirements(required=frozenset({Capability.STRUCTURED_OUTPUT}))
    )

    assert route.descriptor.identity == structured.descriptor.identity

    registry = ModelRegistry()
    registry.register(text)
    with pytest.raises(NoCompatibleModelError):
        CapabilityRouter(registry).route(
            _requirements(required=frozenset({Capability.STRUCTURED_OUTPUT}))
        )


def test_local_only_selects_local_and_rejects_cloud_only() -> None:
    registry = ModelRegistry()
    local = _registration("provider", "local", location=ExecutionLocation.LOCAL)
    cloud = _registration("provider", "cloud", location=ExecutionLocation.CLOUD)
    registry.register(cloud)
    registry.register(local)

    assert (
        CapabilityRouter(registry)
        .route(_requirements(locality=DataLocality.LOCAL_ONLY))
        .descriptor.identity
        == local.descriptor.identity
    )

    cloud_only = ModelRegistry()
    cloud_only.register(cloud)
    with pytest.raises(NoCompatibleModelError):
        CapabilityRouter(cloud_only).route(
            _requirements(locality=DataLocality.LOCAL_ONLY)
        )


def test_cloud_allowed_uses_identity_tie_break_without_location_preference() -> None:
    registry = ModelRegistry()
    cloud = _registration("a-provider", "cloud", location=ExecutionLocation.CLOUD)
    local = _registration("z-provider", "local", location=ExecutionLocation.LOCAL)
    registry.register(local)
    registry.register(cloud)

    route = CapabilityRouter(registry).route(
        _requirements(locality=DataLocality.CLOUD_ALLOWED)
    )

    assert route.descriptor.identity == cloud.descriptor.identity


def test_cloud_preferred_uses_cloud_or_falls_back_to_local() -> None:
    registry = ModelRegistry()
    local = _registration("a-provider", "local", location=ExecutionLocation.LOCAL)
    cloud = _registration("z-provider", "cloud", location=ExecutionLocation.CLOUD)
    registry.register(local)
    registry.register(cloud)

    assert (
        CapabilityRouter(registry)
        .route(_requirements(locality=DataLocality.CLOUD_PREFERRED))
        .descriptor.identity
        == cloud.descriptor.identity
    )

    local_only = ModelRegistry()
    local_only.register(local)
    assert (
        CapabilityRouter(local_only)
        .route(_requirements(locality=DataLocality.CLOUD_PREFERRED))
        .descriptor.identity
        == local.descriptor.identity
    )


def test_preferred_capabilities_require_all_or_are_relaxed_together() -> None:
    registry = ModelRegistry()
    partial = _registration(
        "a-provider",
        "partial",
        capabilities=frozenset({Capability.TEXT_GENERATION, Capability.TEXT_STREAMING}),
        binding=ProviderBinding(
            text_generation=FailingProvider(), text_streaming=FailingProvider()
        ),
    )
    complete = _registration(
        "z-provider",
        "complete",
        capabilities=frozenset(
            {
                Capability.TEXT_GENERATION,
                Capability.TEXT_STREAMING,
                Capability.STRUCTURED_OUTPUT,
            }
        ),
        binding=ProviderBinding(
            text_generation=FailingProvider(),
            text_streaming=FailingProvider(),
            structured_output=FailingProvider(),
        ),
    )
    registry.register(partial)
    registry.register(complete)
    requirements = _requirements(
        preferred=frozenset({Capability.TEXT_STREAMING, Capability.STRUCTURED_OUTPUT})
    )

    assert (
        CapabilityRouter(registry).route(requirements).descriptor.identity
        == complete.descriptor.identity
    )

    registry = ModelRegistry()
    registry.register(partial)
    registry.register(
        _registration(
            "z-provider", "none", capabilities=frozenset({Capability.TEXT_GENERATION})
        )
    )
    relaxed_route = CapabilityRouter(registry).route(requirements)

    assert relaxed_route.descriptor.identity == partial.descriptor.identity


def test_cloud_preference_precedes_preferred_capability_tier() -> None:
    registry = ModelRegistry()
    local = _registration(
        "a-provider",
        "local-complete",
        location=ExecutionLocation.LOCAL,
        capabilities=frozenset(
            {Capability.TEXT_GENERATION, Capability.STRUCTURED_OUTPUT}
        ),
        binding=ProviderBinding(
            text_generation=FailingProvider(), structured_output=FailingProvider()
        ),
    )
    cloud = _registration("z-provider", "cloud-basic", location=ExecutionLocation.CLOUD)
    registry.register(local)
    registry.register(cloud)

    route = CapabilityRouter(registry).route(
        _requirements(
            locality=DataLocality.CLOUD_PREFERRED,
            preferred=frozenset({Capability.STRUCTURED_OUTPUT}),
        )
    )

    assert route.descriptor.identity == cloud.descriptor.identity


def test_routing_is_independent_of_registration_order() -> None:
    first = _registration("z-provider", "model")
    second = _registration("a-provider", "model")
    first_registry = ModelRegistry()
    first_registry.register(first)
    first_registry.register(second)
    second_registry = ModelRegistry()
    second_registry.register(second)
    second_registry.register(first)

    first_route = CapabilityRouter(first_registry).route(_requirements())
    second_route = CapabilityRouter(second_registry).route(_requirements())

    assert first_route.descriptor.identity == _identity("a-provider", "model")
    assert second_route.descriptor.identity == _identity("a-provider", "model")


def test_exact_model_override_is_hard_compatible_only() -> None:
    registry = ModelRegistry()
    local = _registration("provider", "local", location=ExecutionLocation.LOCAL)
    cloud = _registration("provider", "cloud", location=ExecutionLocation.CLOUD)
    registry.register(local)
    registry.register(cloud)
    router = CapabilityRouter(registry)

    assert (
        router.route(
            _requirements(locality=DataLocality.CLOUD_PREFERRED),
            model_override=local.descriptor.identity,
        ).descriptor.identity
        == local.descriptor.identity
    )
    assert (
        router.route(
            _requirements(locality=DataLocality.CLOUD_ALLOWED),
            model_override=cloud.descriptor.identity,
        ).descriptor.identity
        == cloud.descriptor.identity
    )

    registry.set_enabled(cloud.descriptor.identity, False)
    with pytest.raises(IncompatibleModelOverrideError, match="incompatible"):
        router.route(_requirements(), model_override=cloud.descriptor.identity)
    registry.set_enabled(cloud.descriptor.identity, True)
    registry.set_availability(cloud.descriptor.identity, ModelAvailability.UNAVAILABLE)
    with pytest.raises(IncompatibleModelOverrideError, match="incompatible"):
        router.route(_requirements(), model_override=cloud.descriptor.identity)
    registry.set_availability(cloud.descriptor.identity, ModelAvailability.AVAILABLE)
    with pytest.raises(IncompatibleModelOverrideError, match="incompatible"):
        router.route(
            _requirements(locality=DataLocality.LOCAL_ONLY),
            model_override=cloud.descriptor.identity,
        )
    with pytest.raises(IncompatibleModelOverrideError, match="not registered"):
        router.route(_requirements(), model_override=_identity("missing", "model"))
    with pytest.raises(IncompatibleModelOverrideError, match="incompatible"):
        router.route(
            _requirements(required=frozenset({Capability.STRUCTURED_OUTPUT})),
            model_override=local.descriptor.identity,
        )


def test_router_does_not_invoke_provider_and_repr_redacts_binding() -> None:
    sentinel_provider = SentinelProvider()
    registration = _registration(
        "provider",
        "model",
        binding=ProviderBinding(text_generation=sentinel_provider),
    )
    registry = ModelRegistry()
    registry.register(registration)

    route = CapabilityRouter(registry).route(_requirements())

    assert route.descriptor.identity == registration.descriptor.identity
    sentinel = "provider-adapter-super-secret-sentinel"
    assert sentinel not in repr(registration.binding)
    assert sentinel not in repr(registration)
    assert sentinel not in repr(route)
