"""Immutable, transport-neutral runtime health models."""

from dataclasses import dataclass
from enum import StrEnum


class HealthStatus(StrEnum):
    """Observed condition of a runtime component."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """Safe diagnostic condition supplied by a component health producer."""

    name: str
    status: HealthStatus
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Component health name must not be blank")


@dataclass(frozen=True, slots=True)
class RuntimeHealthSnapshot:
    """Ordered component health observations with a derived aggregate status."""

    components: tuple[ComponentHealth, ...]

    def __post_init__(self) -> None:
        component_names = tuple(component.name for component in self.components)
        if len(component_names) != len(set(component_names)):
            raise ValueError("Component health names must be unique within a snapshot")

    @property
    def status(self) -> HealthStatus:
        """Return the conservative aggregate status of the observed components."""

        statuses = {component.status for component in self.components}
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.UNKNOWN in statuses:
            return HealthStatus.UNKNOWN
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        if HealthStatus.HEALTHY in statuses:
            return HealthStatus.HEALTHY
        return HealthStatus.UNKNOWN
