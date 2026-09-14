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
        None,
    )
    assert snapshot.connection is ConnectionState.DEGRADED
    assert VoiceState.IDLE.value == "IDLE"


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
        None,
    )
    assert snapshot.notifications[0].id == notification_id
    assert snapshot.tasks[0].id == task_id
