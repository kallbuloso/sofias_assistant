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


_LOCALITY_LABELS: dict[str, str] = {
    "local_only": "Local only",
    "cloud_allowed": "Allow cloud",
    "cloud_preferred": "Prefer cloud",
}


@dataclass(frozen=True, slots=True)
class InferencePrivacyPreference:
    """Explicit human request policy (Desktop/Core Interaction Contract v1 SS31-34).

    A Desktop-local UI/application preference, never a Grant or Core
    authority: it is only ever request policy that Core independently
    validates and enforces on every relevant request.
    """

    locality: str
    cloud_context_eligible: bool = False

    def __post_init__(self) -> None:
        if self.locality not in _LOCALITY_LABELS:
            raise ValueError(f"Unknown locality: {self.locality}")

    @property
    def locality_label(self) -> str:
        return _LOCALITY_LABELS[self.locality]

    @classmethod
    def default(cls) -> InferencePrivacyPreference:
        return cls(locality="local_only", cloud_context_eligible=False)


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
class ConversationSummaryItem:
    """One bounded Conversation list row (Gate I18 Conversation History UX)."""

    conversation_id: UUID
    created_at: str
    updated_at: str
    preview: str
    last_turn_status: str | None
    last_turn_sequence: int | None

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> ConversationSummaryItem:
        return cls(
            conversation_id=UUID(str(value["conversation_id"])),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            preview=str(value["preview"]),
            last_turn_status=value.get("last_turn_status"),
            last_turn_sequence=value.get("last_turn_sequence"),
        )


@dataclass(frozen=True, slots=True)
class TurnHistoryItem:
    """One bounded, chronological Turn row (Gate I18 Conversation History UX)."""

    id: UUID
    sequence: int
    status: str
    user_text: str
    assistant_text: str | None
    error_message: str | None

    @classmethod
    def from_wire(cls, value: dict[str, Any]) -> TurnHistoryItem:
        return cls(
            id=UUID(str(value["id"])),
            sequence=int(value["sequence"]),
            status=str(value["status"]),
            user_text=str(value["user_text"]),
            assistant_text=value.get("assistant_text"),
            error_message=value.get("error_message"),
        )


@dataclass(frozen=True, slots=True)
class ClientSnapshot:
    connection: ConnectionState
    core_state: str
    health: tuple[HealthItem, ...]
    notifications: tuple[NotificationItem, ...]
    tasks: tuple[TaskItem, ...]


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
    return ClientSnapshot(
        connection=connection,
        core_state=core_state,
        health=health_items(core_payload),
        notifications=tuple(
            NotificationItem.from_wire(value) for value in notifications
        ),
        tasks=tuple(TaskItem.from_wire(value) for value in tasks),
    )
