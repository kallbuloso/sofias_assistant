"""Unit tests for transport-neutral runtime health models."""

from dataclasses import FrozenInstanceError

import pytest

from sofias_assistant.health import (
    ComponentHealth,
    HealthStatus,
    RuntimeHealthSnapshot,
)


def test_component_health_accepts_a_valid_name_and_optional_detail() -> None:
    without_detail = ComponentHealth("database", HealthStatus.HEALTHY)
    with_detail = ComponentHealth(
        "provider", HealthStatus.DEGRADED, "Reduced capability"
    )

    assert without_detail.detail is None
    assert with_detail.detail == "Reduced capability"


@pytest.mark.parametrize("name", ["", "   "])
def test_component_health_rejects_blank_names(name: str) -> None:
    with pytest.raises(ValueError, match="name must not be blank"):
        ComponentHealth(name, HealthStatus.HEALTHY)


def test_health_value_objects_are_immutable() -> None:
    component = ComponentHealth("database", HealthStatus.HEALTHY)
    snapshot = RuntimeHealthSnapshot((component,))

    with pytest.raises(FrozenInstanceError):
        setattr(component, "status", HealthStatus.UNHEALTHY)
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, "components", ())


def test_empty_snapshot_is_unknown() -> None:
    assert RuntimeHealthSnapshot(()).status is HealthStatus.UNKNOWN


def test_all_healthy_components_aggregate_to_healthy() -> None:
    snapshot = RuntimeHealthSnapshot(
        (
            ComponentHealth("database", HealthStatus.HEALTHY),
            ComponentHealth("secrets", HealthStatus.HEALTHY),
        )
    )

    assert snapshot.status is HealthStatus.HEALTHY


def test_degraded_component_aggregates_to_degraded() -> None:
    snapshot = RuntimeHealthSnapshot(
        (
            ComponentHealth("database", HealthStatus.HEALTHY),
            ComponentHealth("provider", HealthStatus.DEGRADED),
        )
    )

    assert snapshot.status is HealthStatus.DEGRADED


def test_unknown_component_dominates_degraded_and_healthy() -> None:
    snapshot = RuntimeHealthSnapshot(
        (
            ComponentHealth("database", HealthStatus.HEALTHY),
            ComponentHealth("provider", HealthStatus.DEGRADED),
            ComponentHealth("scheduler", HealthStatus.UNKNOWN),
        )
    )

    assert snapshot.status is HealthStatus.UNKNOWN


def test_unhealthy_component_dominates_all_other_statuses() -> None:
    snapshot = RuntimeHealthSnapshot(
        (
            ComponentHealth("database", HealthStatus.UNHEALTHY),
            ComponentHealth("provider", HealthStatus.DEGRADED),
            ComponentHealth("scheduler", HealthStatus.UNKNOWN),
        )
    )

    assert snapshot.status is HealthStatus.UNHEALTHY


def test_aggregation_is_independent_of_component_order() -> None:
    components = (
        ComponentHealth("database", HealthStatus.HEALTHY),
        ComponentHealth("provider", HealthStatus.DEGRADED),
        ComponentHealth("scheduler", HealthStatus.UNKNOWN),
    )

    assert (
        RuntimeHealthSnapshot(components).status
        is RuntimeHealthSnapshot(tuple(reversed(components))).status
    )


def test_snapshot_preserves_component_order() -> None:
    components = (
        ComponentHealth("provider", HealthStatus.DEGRADED),
        ComponentHealth("database", HealthStatus.HEALTHY),
    )

    snapshot = RuntimeHealthSnapshot(components)

    assert snapshot.components == components


def test_duplicate_component_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="names must be unique"):
        RuntimeHealthSnapshot(
            (
                ComponentHealth("database", HealthStatus.HEALTHY),
                ComponentHealth("database", HealthStatus.UNHEALTHY),
            )
        )


def test_component_names_remain_case_sensitive() -> None:
    snapshot = RuntimeHealthSnapshot(
        (
            ComponentHealth("database", HealthStatus.HEALTHY),
            ComponentHealth("Database", HealthStatus.DEGRADED),
        )
    )

    assert snapshot.components[0].name == "database"
    assert snapshot.components[1].name == "Database"
