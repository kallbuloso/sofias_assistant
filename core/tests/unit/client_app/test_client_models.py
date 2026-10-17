"""Tests for the Desktop Client transport view models."""

from uuid import uuid4

from sofias_assistant.client_app.models import (
    ConnectionState,
    VoiceState,
    health_items,
    snapshot_from_wire,
)


def test_health_mapping_explicitly_represents_unconfigured_subsystems() -> None:
    items = health_items({"state": "running", "health": {"components": []}})
    by_name = {item.name: item for item in items}
    assert by_name["Core"].status == "healthy"
    assert by_name["AI provider"].status == "unavailable"
    assert by_name["Memory"].detail == "Not configured"


def test_snapshot_maps_degraded_core_without_inventing_authority() -> None:
    snapshot = snapshot_from_wire(
        {"state": "running", "health": {"status": "degraded", "components": []}},
        [],
        [],
    )
    assert snapshot.connection is ConnectionState.DEGRADED
    assert VoiceState.IDLE.value == "IDLE"
    assert VoiceState.READY.value == "READY"


def test_snapshot_maps_transport_items() -> None:
    notification_id = uuid4()
    event_id = uuid4()
    task_id = uuid4()
    snapshot = snapshot_from_wire(
        {"state": "running", "health": {"status": "healthy", "components": []}},
        [
            {
                "id": str(notification_id),
                "event_id": str(event_id),
                "type": "ReminderDue",
                "title": "Reminder",
                "summary": "Due",
                "severity": "INFO",
                "state": "PENDING",
            }
        ],
        [
            {
                "id": str(task_id),
                "objective": "Inspect",
                "status": "RUNNING",
                "result": None,
                "error_code": None,
                "error_message": None,
            }
        ],
    )
    assert snapshot.notifications[0].id == notification_id
    assert snapshot.tasks[0].id == task_id


def test_health_items_maps_runtime_component_names() -> None:
    snapshot = snapshot_from_wire(
        {
            "state": "running",
            "health": {
                "status": "unknown",
                "components": [
                    {
                        "name": "llm-provider",
                        "status": "healthy",
                        "detail": "canonical provider=openai",
                    },
                    {
                        "name": "sofias-memory",
                        "status": "unknown",
                        "detail": "Memory is not configured",
                    },
                ],
            },
        },
        [],
        [],
    )

    health = {item.name: item for item in snapshot.health}
    assert health["AI provider"].status == "healthy"
    assert health["AI provider"].detail == "canonical provider=openai"
    assert health["Memory"].status == "unknown"
    assert health["Memory"].detail == "Memory is not configured"
