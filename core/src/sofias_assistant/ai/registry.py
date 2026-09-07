"""In-memory registrations for declared models and their provider bindings."""

from dataclasses import dataclass, field, replace
from enum import StrEnum

from sofias_assistant.ai.contracts import Capability, ModelDescriptor, ModelIdentity
from sofias_assistant.ai.providers import (
    StructuredOutputProvider,
    TextGenerationProvider,
    TextStreamingProvider,
)


class ModelAvailability(StrEnum):
    """Minimum runtime usability state for a registered model."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class RegistryError(RuntimeError):
    """Base error for explicit in-memory model registration operations."""


class ModelAlreadyRegisteredError(RegistryError):
    """Raised when a ModelIdentity is registered more than once."""


class ModelNotRegisteredError(RegistryError):
    """Raised when an operation references an unknown ModelIdentity."""


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    """Specialized provider contracts bound to one registered model."""

    text_generation: TextGenerationProvider | None = field(default=None, repr=False)
    text_streaming: TextStreamingProvider | None = field(default=None, repr=False)
    structured_output: StructuredOutputProvider | None = field(default=None, repr=False)


def _identity_label(identity: ModelIdentity) -> str:
    return f"{identity.provider_id}/{identity.model_id}"


def _validate_binding(descriptor: ModelDescriptor, binding: ProviderBinding) -> None:
    capabilities = descriptor.capabilities
    if Capability.TEXT_GENERATION in capabilities and binding.text_generation is None:
        raise ValueError("TEXT_GENERATION requires a text_generation binding")
    if Capability.TEXT_STREAMING in capabilities and binding.text_streaming is None:
        raise ValueError("TEXT_STREAMING requires a text_streaming binding")
    if (
        Capability.STRUCTURED_OUTPUT in capabilities
        and binding.structured_output is None
    ):
        raise ValueError("STRUCTURED_OUTPUT requires a structured_output binding")
    if Capability.TOOL_CALLING in capabilities and (
        binding.text_generation is None and binding.text_streaming is None
    ):
        raise ValueError("TOOL_CALLING requires a text generation or streaming binding")


@dataclass(frozen=True, slots=True)
class ModelRegistration:
    """Mutable-at-registry, immutable-at-value registration state for a model."""

    descriptor: ModelDescriptor
    binding: ProviderBinding = field(repr=False)
    enabled: bool = True
    availability: ModelAvailability = ModelAvailability.AVAILABLE

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ModelDescriptor):
            raise ValueError("descriptor must be a ModelDescriptor")
        if not isinstance(self.binding, ProviderBinding):
            raise ValueError("binding must be a ProviderBinding")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if not isinstance(self.availability, ModelAvailability):
            raise ValueError("availability must be a ModelAvailability")
        _validate_binding(self.descriptor, self.binding)


class ModelRegistry:
    """Explicit process-local registry with no global singleton or persistence."""

    def __init__(self) -> None:
        self._registrations: dict[ModelIdentity, ModelRegistration] = {}

    def register(self, registration: ModelRegistration) -> None:
        """Register one model identity exactly once."""

        identity = registration.descriptor.identity
        if identity in self._registrations:
            raise ModelAlreadyRegisteredError(
                f"Model is already registered: {_identity_label(identity)}"
            )
        self._registrations[identity] = registration

    def get(self, identity: ModelIdentity) -> ModelRegistration:
        """Return a registration or fail clearly when the identity is unknown."""

        try:
            return self._registrations[identity]
        except KeyError as error:
            raise ModelNotRegisteredError(
                f"Model is not registered: {_identity_label(identity)}"
            ) from error

    def registrations(self) -> tuple[ModelRegistration, ...]:
        """Return immutable registrations in deterministic identity order."""

        return tuple(
            self._registrations[identity]
            for identity in sorted(
                self._registrations,
                key=lambda candidate: (candidate.provider_id, candidate.model_id),
            )
        )

    def set_enabled(self, identity: ModelIdentity, enabled: bool) -> None:
        """Set explicit runtime enablement without changing static descriptors."""

        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a bool")
        self._replace(identity, enabled=enabled)

    def set_availability(
        self, identity: ModelIdentity, availability: ModelAvailability
    ) -> None:
        """Set minimum runtime availability without performing a health probe."""

        if not isinstance(availability, ModelAvailability):
            raise ValueError("availability must be a ModelAvailability")
        self._replace(identity, availability=availability)

    def _replace(
        self,
        identity: ModelIdentity,
        *,
        enabled: bool | None = None,
        availability: ModelAvailability | None = None,
    ) -> None:
        registration = self.get(identity)
        replacement = replace(
            registration,
            enabled=registration.enabled if enabled is None else enabled,
            availability=(
                registration.availability if availability is None else availability
            ),
        )
        self._registrations[identity] = replacement
