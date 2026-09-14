"""Transport-neutral Client view models; Core remains the domain owner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID


class ConnectionState(StrEnum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


class VoiceState(StrEnum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    LISTENING = "LISTENING"
    RESPONDING = "RESPONDING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class HealthItem:
    name: str
    status: str
    detail: str | None


@dataclass(frozen=True, slots=True)
class NotificationItem:
    id: UUID
    event_id: UUID
    type: str
    title: str
    summary: str
    severity: str
    state: str
    action_reference: UUID | None

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> NotificationItem:
        return cls(
            id=UUID(str(value["id"])),
            event_id=UUID(str(value["event_id"])),
            type=str(value["type"]),
            title=str(value["title"]),
            summary=str(value["summary"]),
            severity=str(value["severity"]),
            state=str(value["state"]),
            action_reference=(
                UUID(str(value["action_reference"]))
                if value.get("action_reference")
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class TaskItem:
    id: UUID
    objective: str
    status: str
    result: Any
    error_code: str | None
    error_message: str | None
    cancellation_requested: bool
    confirmation_id: UUID | None

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> TaskItem:
        return cls(
            id=UUID(str(value["id"])),
            objective=str(value["objective"]),
            status=str(value["status"]),
            result=value.get("result"),
            error_code=value.get("error_code"),
            error_message=value.get("error_message"),
            cancellation_requested=bool(value.get("cancellation_requested", False)),
            confirmation_id=(
                UUID(str(value["confirmation_id"]))
                if value.get("confirmation_id")
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class ConversationItem:
    id: UUID
    turn_count: int = 0


@dataclass(frozen=True, slots=True)
class ClientSnapshot:
    connection: ConnectionState
    core_state: str
    health: tuple[HealthItem, ...]
    notifications: tuple[NotificationItem, ...]
    tasks: tuple[TaskItem, ...]
    conversation: ConversationItem | None


_HEALTH_COMPONENTS = (
    ("core", "Core"),
    ("ai-provider", "AI provider"),
    ("realtime", "Realtime"),
    ("scheduler", "Scheduler"),
    ("notifications", "Notifications"),
    ("memory", "Memory"),
)


def health_items(core_payload: dict[str, Any]) -> tuple[HealthItem, ...]:
    """Map transport health to a stable product view without inventing Memory."""

    core_state = str(core_payload.get("state", "unknown"))
    snapshot = core_payload.get("health") or {}
    observed = {
        str(item.get("name")): item
        for item in snapshot.get("components", [])
        if isinstance(item, dict)
    }
    result: list[HealthItem] = []
    for key, label in _HEALTH_COMPONENTS:
        if key == "core":
            result.append(
                HealthItem(
                    label,
                    "healthy" if core_state == "running" else "degraded",
                    None if core_state == "running" else f"Core state: {core_state}",
                )
            )
            continue
        item = observed.get(key)
        if item is None:
            detail = (
                "Not configured" if key in {"ai-provider", "memory"} else "No probe"
            )
            result.append(HealthItem(label, "unavailable", detail))
        else:
            result.append(
                HealthItem(
                    label, str(item.get("status", "unknown")), item.get("detail")
                )
            )
    return tuple(result)


def snapshot_from_wire(
    core_payload: dict[str, Any],
    notifications: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    conversation: dict[str, Any] | None,
) -> ClientSnapshot:
    core_state = str(core_payload.get("state", "unknown"))
    aggregate = str((core_payload.get("health") or {}).get("status", "unknown"))
    connection = (
        ConnectionState.CONNECTED
        if core_state == "running" and aggregate == "healthy"
        else ConnectionState.DEGRADED
        if core_state == "running"
        else ConnectionState.DISCONNECTED
    )
    conversation_item = None
    if conversation is not None:
        conversation_item = ConversationItem(
            UUID(str(conversation["conversation"]["id"])),
            len(conversation.get("turns", [])),
        )
    return ClientSnapshot(
        connection=connection,
        core_state=core_state,
        health=health_items(core_payload),
        notifications=tuple(
            NotificationItem.from_wire(value) for value in notifications
        ),
        tasks=tuple(TaskItem.from_wire(value) for value in tasks),
        conversation=conversation_item,
    )
