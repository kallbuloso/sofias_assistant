"""Deterministic capability and locality routing without provider invocation."""

from dataclasses import dataclass, field

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
)
from sofias_assistant.ai.registry import (
    ModelAvailability,
    ModelNotRegisteredError,
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)


class RoutingError(RuntimeError):
    """Base error for deterministic model selection."""


class NoCompatibleModelError(RoutingError):
    """Raised when automatic routing finds no hard-eligible model."""


class IncompatibleModelOverrideError(RoutingError):
    """Raised when an exact override cannot satisfy the request."""


@dataclass(frozen=True, slots=True)
class AIRoute:
    """Selected descriptor and binding for a later inference invocation."""

    descriptor: ModelDescriptor
    binding: ProviderBinding = field(repr=False)


def _identity_label(identity: ModelIdentity) -> str:
    return f"{identity.provider_id}/{identity.model_id}"


class CapabilityRouter:
    """Select a registered model deterministically; never invoke its provider."""

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

    def route(
        self,
        requirements: AIRequestRequirements,
        *,
        model_override: ModelIdentity | None = None,
    ) -> AIRoute:
        """Return one compatible route or a clear routing error.

        Automatic routing applies hard eligibility, then the CLOUD_PREFERRED
        location tier, then the all-preferred-capabilities tier, and finally
        `(provider_id, model_id)` ordering. An explicit override bypasses only
        preferences; it never bypasses hard eligibility.
        """

        if not isinstance(requirements, AIRequestRequirements):
            raise ValueError("requirements must be AIRequestRequirements")
        if model_override is not None:
            return self._route_override(requirements, model_override)

        candidates = tuple(
            registration
            for registration in self._registry.registrations()
            if self._is_hard_eligible(registration, requirements)
        )
        if not candidates:
            raise NoCompatibleModelError("No compatible model is registered")

        candidates = self._apply_cloud_preference(candidates, requirements)
        candidates = self._apply_capability_preferences(candidates, requirements)
        selected = min(
            candidates,
            key=lambda registration: (
                registration.descriptor.identity.provider_id,
                registration.descriptor.identity.model_id,
            ),
        )
        return AIRoute(descriptor=selected.descriptor, binding=selected.binding)

    def _route_override(
        self,
        requirements: AIRequestRequirements,
        model_override: ModelIdentity,
    ) -> AIRoute:
        try:
            registration = self._registry.get(model_override)
        except ModelNotRegisteredError as error:
            raise IncompatibleModelOverrideError(
                f"Model override is not registered: {_identity_label(model_override)}"
            ) from error
        if not self._is_hard_eligible(registration, requirements):
            raise IncompatibleModelOverrideError(
                f"Model override is incompatible: {_identity_label(model_override)}"
            )
        return AIRoute(descriptor=registration.descriptor, binding=registration.binding)

    @staticmethod
    def _is_hard_eligible(
        registration: ModelRegistration,
        requirements: AIRequestRequirements,
    ) -> bool:
        descriptor = registration.descriptor
        return (
            registration.enabled
            and registration.availability is ModelAvailability.AVAILABLE
            and requirements.required_capabilities <= descriptor.capabilities
            and CapabilityRouter._matches_locality(
                descriptor.execution_location, requirements.locality
            )
        )

    @staticmethod
    def _matches_locality(
        execution_location: ExecutionLocation,
        locality: DataLocality,
    ) -> bool:
        if locality is DataLocality.LOCAL_ONLY:
            return execution_location is ExecutionLocation.LOCAL
        return True

    @staticmethod
    def _apply_cloud_preference(
        candidates: tuple[ModelRegistration, ...],
        requirements: AIRequestRequirements,
    ) -> tuple[ModelRegistration, ...]:
        if requirements.locality is not DataLocality.CLOUD_PREFERRED:
            return candidates
        cloud_candidates = tuple(
            registration
            for registration in candidates
            if registration.descriptor.execution_location is ExecutionLocation.CLOUD
        )
        return cloud_candidates or candidates

    @staticmethod
    def _apply_capability_preferences(
        candidates: tuple[ModelRegistration, ...],
        requirements: AIRequestRequirements,
    ) -> tuple[ModelRegistration, ...]:
        if not requirements.preferred_capabilities:
            return candidates
        preferred_candidates = tuple(
            registration
            for registration in candidates
            if requirements.preferred_capabilities
            <= registration.descriptor.capabilities
        )
        return preferred_candidates or candidates
