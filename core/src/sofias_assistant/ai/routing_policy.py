"""Profile-aware routing policy above the deterministic CapabilityRouter.

Amendment 0003 SS3 fundamental rule:

    Domain requests capabilities + workload/profile.
        -> Routing policy resolves configured preferences.
        -> CapabilityRouter validates hard compatibility.
        -> Provider adapter performs inference.

`RoutingPolicy` is the "routing policy" layer. It never becomes
persistence-aware itself: it only reads an already-built, immutable
`RoutingSnapshot` supplied by a snapshot provider callable (owned by the AI
Configuration Service) and drives `CapabilityRouter.route(...)` with explicit
`model_override` candidates, one at a time, in the exact deterministic order
required by the Runtime Configuration Contract v1 SS25:

    1. explicit per-call override, if supplied
    2. ordered enabled bindings for the selected profile
    3. canonical/default model only if the profile's fallback policy permits
    4. routing failure

`CapabilityRouter` remains the sole authority for hard compatibility: this
module never re-implements eligibility checks to decide whether a candidate
is used, it only inspects snapshot data to produce a diagnostic reason code
after the router has already accepted or rejected that exact candidate.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    Capability,
    DataLocality,
    ExecutionLocation,
    ModelIdentity,
)
from sofias_assistant.ai.registry import ModelAvailability
from sofias_assistant.ai.routing import (
    AIRoute,
    CapabilityRouter,
    IncompatibleModelOverrideError,
    NoCompatibleModelError,
    RoutingError,
)


class FallbackPolicy(StrEnum):
    """Runtime Configuration Contract v1 SS24 baseline fallback vocabulary."""

    ORDERED_ONLY = "ordered_only"
    ORDERED_THEN_CANONICAL = "ordered_then_canonical"


class RoutingReasonCode(StrEnum):
    """Contract v1 SS35 baseline machine-readable routing reason vocabulary."""

    EXPLICIT_OVERRIDE_SELECTED = "explicit_override_selected"
    PROFILE_BINDING_SELECTED = "profile_binding_selected"
    CANONICAL_FALLBACK_SELECTED = "canonical_fallback_selected"
    NO_COMPATIBLE_MODEL = "no_compatible_model"
    PROVIDER_DISABLED = "provider_disabled"
    MODEL_DISABLED = "model_disabled"
    MODEL_UNAVAILABLE = "model_unavailable"
    MISSING_REQUIRED_CAPABILITY = "missing_required_capability"
    LOCALITY_INCOMPATIBLE = "locality_incompatible"
    ADAPTER_INCOMPATIBLE = "adapter_incompatible"
    INVALID_PROFILE = "invalid_profile"


class InvalidProfileError(RoutingError):
    """Raised when a profile key is unknown or disabled."""


@runtime_checkable
class Router(Protocol):
    """Structural contract shared by `CapabilityRouter` and `RoutingPolicy`.

    Consumers (Conversation, Vision, Agents) depend on this Protocol instead
    of the concrete `CapabilityRouter` class so a profile-aware
    `RoutingPolicy` is a drop-in replacement with no call-site changes.
    """

    def route(
        self,
        requirements: AIRequestRequirements,
        *,
        model_override: ModelIdentity | None = None,
    ) -> AIRoute: ...


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """Immutable routing-relevant projection of one persisted InferenceProfile."""

    key: str
    required_capabilities: frozenset[Capability]
    preferred_capabilities: frozenset[Capability]
    locality: DataLocality
    enabled: bool
    fallback_policy: FallbackPolicy


@dataclass(frozen=True, slots=True)
class BindingSpec:
    """Immutable routing-relevant projection of one ProfileModelBinding."""

    identity: ModelIdentity
    priority: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class ModelDiagnostic:
    """Safe, snapshot-derived explanation for why a candidate was rejected."""

    provider_enabled: bool
    model_known: bool
    model_enabled: bool
    availability: ModelAvailability | None
    execution_location: ExecutionLocation | None
    adapter_incompatible: bool = False


@dataclass(frozen=True, slots=True)
class RoutingSnapshot:
    """One immutable, atomically-published routing configuration version.

    Built entirely by the AI Configuration Service. `router` already embeds
    a fully-populated `ModelRegistry` (only trusted, non-DISCOVERED-only
    capabilities registered); `RoutingPolicy` never queries persistence.
    """

    profiles: Mapping[str, ProfileSpec]
    bindings: Mapping[str, tuple[BindingSpec, ...]]
    canonical: ModelIdentity | None
    router: CapabilityRouter
    diagnostics: Mapping[ModelIdentity, ModelDiagnostic] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Deterministic, auditable outcome of one profile-aware routing resolution."""

    profile_key: str
    route: AIRoute | None
    reason_code: RoutingReasonCode
    reason: str
    fallback: bool


def _narrow_locality(request: DataLocality, profile: DataLocality) -> DataLocality:
    """A profile may only narrow a request toward LOCAL_ONLY, never widen it."""

    if request is DataLocality.LOCAL_ONLY or profile is DataLocality.LOCAL_ONLY:
        return DataLocality.LOCAL_ONLY
    return request


def _diagnose(
    snapshot: RoutingSnapshot,
    identity: ModelIdentity,
    requirements: AIRequestRequirements,
) -> RoutingReasonCode:
    """Best-effort, snapshot-derived explanation; never the eligibility authority."""

    diagnostic = snapshot.diagnostics.get(identity)
    if diagnostic is None or not diagnostic.model_known:
        return RoutingReasonCode.MODEL_UNAVAILABLE
    if not diagnostic.provider_enabled:
        return RoutingReasonCode.PROVIDER_DISABLED
    if not diagnostic.model_enabled:
        return RoutingReasonCode.MODEL_DISABLED
    if diagnostic.availability is not ModelAvailability.AVAILABLE:
        return RoutingReasonCode.MODEL_UNAVAILABLE
    if diagnostic.adapter_incompatible:
        return RoutingReasonCode.ADAPTER_INCOMPATIBLE
    if (
        requirements.locality is DataLocality.LOCAL_ONLY
        and diagnostic.execution_location is not ExecutionLocation.LOCAL
    ):
        return RoutingReasonCode.LOCALITY_INCOMPATIBLE
    return RoutingReasonCode.MISSING_REQUIRED_CAPABILITY


class RoutingPolicy:
    """Profile-bound routing policy resolving over a live `RoutingSnapshot`.

    Instances are cheap and stateless beyond the bound `profile_key`; the
    `snapshot_provider` callable always returns the currently published
    snapshot, so concurrent configuration writes never affect a resolution
    already in progress (Contract v1 SS27/SS43).
    """

    def __init__(
        self,
        snapshot_provider: Callable[[], RoutingSnapshot],
        *,
        profile_key: str,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._profile_key = profile_key

    @property
    def profile_key(self) -> str:
        return self._profile_key

    def resolve(
        self,
        requirements: AIRequestRequirements,
        *,
        model_override: ModelIdentity | None = None,
    ) -> RoutingDecision:
        """Return a deterministic, explainable routing decision. Never invokes a provider."""

        snapshot = self._snapshot_provider()
        profile = snapshot.profiles.get(self._profile_key)
        if profile is None or not profile.enabled:
            return RoutingDecision(
                profile_key=self._profile_key,
                route=None,
                reason_code=RoutingReasonCode.INVALID_PROFILE,
                reason=f"Profile '{self._profile_key}' is unknown or disabled",
                fallback=False,
            )

        effective_requirements = AIRequestRequirements(
            required_capabilities=requirements.required_capabilities
            | profile.required_capabilities,
            preferred_capabilities=(
                requirements.preferred_capabilities | profile.preferred_capabilities
            )
            - (requirements.required_capabilities | profile.required_capabilities),
            locality=_narrow_locality(requirements.locality, profile.locality),
        )

        if model_override is not None:
            return self._resolve_override(
                snapshot, effective_requirements, model_override
            )

        bindings = tuple(
            binding
            for binding in snapshot.bindings.get(self._profile_key, ())
            if binding.enabled
        )
        for index, binding in enumerate(
            sorted(bindings, key=lambda candidate: candidate.priority)
        ):
            try:
                route = snapshot.router.route(
                    effective_requirements, model_override=binding.identity
                )
            except IncompatibleModelOverrideError:
                continue
            return RoutingDecision(
                profile_key=self._profile_key,
                route=route,
                reason_code=RoutingReasonCode.PROFILE_BINDING_SELECTED,
                reason="Highest-priority eligible profile binding selected.",
                fallback=index > 0,
            )

        if (
            profile.fallback_policy is FallbackPolicy.ORDERED_THEN_CANONICAL
            and snapshot.canonical is not None
        ):
            try:
                route = snapshot.router.route(
                    effective_requirements, model_override=snapshot.canonical
                )
            except IncompatibleModelOverrideError:
                pass
            else:
                return RoutingDecision(
                    profile_key=self._profile_key,
                    route=route,
                    reason_code=RoutingReasonCode.CANONICAL_FALLBACK_SELECTED,
                    reason="No profile binding was eligible; canonical model is compatible.",
                    fallback=True,
                )

        return RoutingDecision(
            profile_key=self._profile_key,
            route=None,
            reason_code=RoutingReasonCode.NO_COMPATIBLE_MODEL,
            reason="No configured candidate satisfies the required capabilities/locality.",
            fallback=False,
        )

    def _resolve_override(
        self,
        snapshot: RoutingSnapshot,
        requirements: AIRequestRequirements,
        model_override: ModelIdentity,
    ) -> RoutingDecision:
        try:
            route = snapshot.router.route(requirements, model_override=model_override)
        except IncompatibleModelOverrideError:
            reason_code = _diagnose(snapshot, model_override, requirements)
            return RoutingDecision(
                profile_key=self._profile_key,
                route=None,
                reason_code=reason_code,
                reason="Explicit model override is incompatible; no fallback is attempted.",
                fallback=False,
            )
        return RoutingDecision(
            profile_key=self._profile_key,
            route=route,
            reason_code=RoutingReasonCode.EXPLICIT_OVERRIDE_SELECTED,
            reason="Explicit per-call model override is compatible.",
            fallback=False,
        )

    def route(
        self,
        requirements: AIRequestRequirements,
        *,
        model_override: ModelIdentity | None = None,
    ) -> AIRoute:
        """Drop-in replacement for `CapabilityRouter.route` at existing call sites."""

        decision = self.resolve(requirements, model_override=model_override)
        if decision.route is not None:
            return decision.route
        if decision.reason_code is RoutingReasonCode.INVALID_PROFILE:
            raise InvalidProfileError(decision.reason)
        if model_override is not None:
            raise IncompatibleModelOverrideError(decision.reason)
        raise NoCompatibleModelError(decision.reason)
