"""Bounded operational contracts; events and timing convey no authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return value.astimezone(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FakeClock:
    instant: datetime

    def now(self) -> datetime:
        return utc(self.instant)

    def advance(self, delta: timedelta) -> None:
        self.instant = self.now() + delta


class Durability(StrEnum):
    EPHEMERAL = "EPHEMERAL"
    DURABLE = "DURABLE"


@dataclass(frozen=True)
class Event:
    type: str
    source: str
    occurred_at: datetime
    correlation_id: UUID = field(default_factory=uuid4)
    causation_id: UUID | None = None
    payload: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    durability: Durability = Durability.EPHEMERAL
    kind: str = "DOMAIN"
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.type.strip() or not self.source.strip():
            raise ValueError("Event type and source must be explicit")
        if len(self.type) > 128 or len(self.source) > 128:
            raise ValueError("Event labels exceed their bound")
        if (
            not isinstance(self.id, UUID)
            or not isinstance(self.correlation_id, UUID)
            or (
                self.causation_id is not None
                and not isinstance(self.causation_id, UUID)
            )
        ):
            raise ValueError("Event references must be UUIDs")
        if self.kind not in {"DOMAIN", "EXTERNAL"}:
            raise ValueError("Invalid event kind")
        if not isinstance(self.durability, Durability):
            raise ValueError("Explicit durability required")
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        for value in (self.payload, self.metadata):
            if (
                not isinstance(value, dict)
                or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in value.items()
                )
                or len(json.dumps(value).encode()) > 8192
            ):
                raise ValueError("Event data must be a bounded string mapping")
        # Detach caller-owned containers before persistence/delivery.
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))


def timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise ValueError("Invalid IANA timezone") from error


def resolve_local(value: datetime, zone: str) -> datetime:
    """Reject nonexistent wall times; ambiguous wall times use explicit fold."""
    if value.tzinfo is not None:
        raise ValueError("Local time must be naive, with a separate IANA timezone")
    candidate = value.replace(tzinfo=timezone(zone))
    resolved = candidate.astimezone(UTC)
    if resolved.astimezone(candidate.tzinfo).replace(tzinfo=None) != value:
        raise ValueError("Nonexistent local time during timezone transition")
    return resolved


@dataclass(frozen=True)
class Recurrence:
    kind: str = "ONCE"
    interval_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"ONCE", "INTERVAL", "DAILY"}:
            raise ValueError("Unsupported recurrence")
        if self.kind == "INTERVAL":
            if type(self.interval_seconds) is not int or not (
                1 <= self.interval_seconds <= 366 * 86400
            ):
                raise ValueError("Invalid recurrence interval")
        elif self.interval_seconds is not None:
            raise ValueError("Only interval recurrence accepts interval_seconds")

    def next_after(self, anchor: datetime, now: datetime, zone: str) -> datetime | None:
        anchor, now = utc(anchor), utc(now)
        tz = timezone(zone)
        if self.kind == "ONCE":
            return None
        if self.kind == "INTERVAL":
            assert self.interval_seconds is not None
            interval = timedelta(seconds=self.interval_seconds)
            return anchor + interval * max(1, (now - anchor) // interval + 1)
        local = anchor.astimezone(tz)
        day = max(local.date(), now.astimezone(tz).date())
        # Daily wall-clock recurrence: skip nonexistent days, first fold only.
        for _ in range(370):
            wall = datetime.combine(day, local.time()).replace(fold=0)
            try:
                candidate = resolve_local(wall, zone)
            except ValueError:
                candidate = None
            if candidate is not None and candidate > max(anchor, now):
                return candidate
            day += timedelta(days=1)
        raise ValueError("No valid daily occurrence")
