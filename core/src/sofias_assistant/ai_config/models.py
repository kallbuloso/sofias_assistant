"""Domain entities for persistent AI provider/model/profile configuration.

These are Core-owned application/domain objects, separate from both the
provider-neutral inference contracts in `sofias_assistant.ai.contracts` and
the SQLAlchemy ORM records in `sofias_assistant.persistence.models`. Nothing
here ever holds a secret value: `credential_ref` is a `SecretRef` identity
only (Amendment 0003 SS10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sofias_assistant.ai.contracts import (
    Capability,
    CapabilityProvenance,
    DataLocality,
    ExecutionLocation,
    ModelIdentity,
)
from sofias_assistant.ai.registry import ModelAvailability
from sofias_assistant.ai.routing_policy import FallbackPolicy
from sofias_assistant.secrets.models import SecretRef


class DiscoverySource(StrEnum):
    """Origin of one catalog entry; never a capability claim by itself."""

    BOOTSTRAP = "bootstrap"
    MANUAL = "manual"
    DISCOVERED = "discovered"


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    """Non-secret provider configuration (Contract v1 SS16)."""

    id: str
    display_name: str
    adapter_type: str
    base_url: str
    enabled: bool
    execution_location: ExecutionLocation
    credential_ref: SecretRef | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.id, "id")
        _require_non_blank(self.display_name, "display_name")
        _require_non_blank(self.adapter_type, "adapter_type")
        _require_non_blank(self.base_url, "base_url")
        if not isinstance(self.execution_location, ExecutionLocation):
            raise ValueError("execution_location must be an ExecutionLocation")
        if self.credential_ref is not None and not isinstance(
            self.credential_ref, SecretRef
        ):
            raise ValueError("credential_ref must be a SecretRef when provided")


@dataclass(frozen=True, slots=True)
class CapabilityClaim:
    """One capability claim with explicit provenance (Contract v1 SS19)."""

    capability: Capability
    provenance: CapabilityProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.capability, Capability):
            raise ValueError("capability must be a Capability")
        if not isinstance(self.provenance, CapabilityProvenance):
            raise ValueError("provenance must be a CapabilityProvenance")


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """Non-secret catalog entry keyed by stable (provider_id, model_id) identity."""

    provider_id: str
    model_id: str
    display_name: str
    context_window: int | None
    execution_location: ExecutionLocation
    availability: ModelAvailability
    enabled: bool
    discovery_source: DiscoverySource
    capabilities: frozenset[CapabilityClaim]
    metadata: dict[str, Any] = field(default_factory=dict)
    last_seen_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.provider_id, "provider_id")
        _require_non_blank(self.model_id, "model_id")
        _require_non_blank(self.display_name, "display_name")
        if self.context_window is not None and (
            isinstance(self.context_window, bool)
            or not isinstance(self.context_window, int)
            or self.context_window <= 0
        ):
            raise ValueError("context_window must be greater than zero when provided")
        if not isinstance(self.availability, ModelAvailability):
            raise ValueError("availability must be a ModelAvailability")
        if not isinstance(self.discovery_source, DiscoverySource):
            raise ValueError("discovery_source must be a DiscoverySource")
        if not isinstance(self.capabilities, frozenset) or not all(
            isinstance(claim, CapabilityClaim) for claim in self.capabilities
        ):
            raise ValueError("capabilities must be a frozenset of CapabilityClaim")
        claimed = [claim.capability for claim in self.capabilities]
        if len(claimed) != len(set(claimed)):
            raise ValueError("capabilities must not claim the same Capability twice")

    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity(self.provider_id, self.model_id)

    def trusted_capabilities(self) -> frozenset[Capability]:
        """Capabilities usable for hard compatibility (never bare DISCOVERED)."""

        return frozenset(
            claim.capability
            for claim in self.capabilities
            if claim.provenance is not CapabilityProvenance.DISCOVERED
        )

    def capability_provenance(self) -> dict[Capability, CapabilityProvenance]:
        return {claim.capability: claim.provenance for claim in self.capabilities}


@dataclass(frozen=True, slots=True)
class InferenceProfile:
    """Persistent workload profile (Contract v1 SS21)."""

    key: str
    display_name: str
    description: str
    required_capabilities: frozenset[Capability]
    preferred_capabilities: frozenset[Capability]
    locality: DataLocality
    enabled: bool
    fallback_policy: FallbackPolicy
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.key, "key")
        if not isinstance(self.locality, DataLocality):
            raise ValueError("locality must be a DataLocality")
        if not isinstance(self.fallback_policy, FallbackPolicy):
            raise ValueError("fallback_policy must be a FallbackPolicy")
        if self.required_capabilities & self.preferred_capabilities:
            raise ValueError("required and preferred capabilities must not overlap")


@dataclass(frozen=True, slots=True)
class ProfileModelBinding:
    """Ordered preference binding a profile to one candidate model."""

    profile_key: str
    provider_id: str
    model_id: str
    priority: int
    enabled: bool
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.profile_key, "profile_key")
        _require_non_blank(self.provider_id, "provider_id")
        _require_non_blank(self.model_id, "model_id")
        _require_non_blank(self.source, "source")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("priority must be an int")

    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity(self.provider_id, self.model_id)
