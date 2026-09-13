"""Clock/calendar and event contract correctness without wall-clock waiting."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sofias_assistant.proactivity.models import (
    Durability,
    Event,
    FakeClock,
    Recurrence,
    resolve_local,
    timezone,
)


def test_event_identity_correlation_and_detached_payload() -> None:
    payload = {"reference": "one"}
    event = Event(
        "changed",
        "fixture",
        datetime(2030, 1, 1, tzinfo=UTC),
        causation_id=uuid4(),
        payload=payload,
    )
    payload["reference"] = "two"
    assert event.payload == {"reference": "one"}
    assert event.id != event.correlation_id != event.causation_id
    assert event.durability is Durability.EPHEMERAL


@pytest.mark.parametrize(
    "kind, interval",
    [
        ("cron", None),
        ("INTERVAL", 0),
        ("INTERVAL", True),
        ("INTERVAL", 1.5),
        ("DAILY", 60),
        ("ONCE", 5),
    ],
)
def test_malformed_recurrence(kind, interval) -> None:
    with pytest.raises(ValueError):
        Recurrence(kind, interval)


@pytest.mark.parametrize("zone", ["Invalid/Zone", "../UTC", "-03:00"])
def test_invalid_timezone(zone: str) -> None:
    with pytest.raises(ValueError):
        timezone(zone)


def test_sao_paulo_and_dst_folds_and_gap() -> None:
    assert resolve_local(datetime(2030, 1, 1, 9), "America/Sao_Paulo") == datetime(
        2030, 1, 1, 12, tzinfo=UTC
    )
    first = resolve_local(datetime(2026, 11, 1, 1, 30), "America/New_York")
    second = resolve_local(datetime(2026, 11, 1, 1, 30, fold=1), "America/New_York")
    assert second - first == timedelta(hours=1)
    with pytest.raises(ValueError, match="Nonexistent"):
        resolve_local(datetime(2026, 3, 8, 2, 30), "America/New_York")


def test_daily_tracks_wall_clock_and_skips_nonexistent_occurrence() -> None:
    recurrence = Recurrence("DAILY")
    anchor = resolve_local(datetime(2026, 3, 7, 9), "America/New_York")
    next_run = recurrence.next_after(anchor, anchor, "America/New_York")
    assert next_run == datetime(2026, 3, 8, 13, tzinfo=UTC)
    assert next_run - anchor == timedelta(hours=23)
    gap_anchor = resolve_local(datetime(2026, 3, 7, 2, 30), "America/New_York")
    assert recurrence.next_after(
        gap_anchor, gap_anchor, "America/New_York"
    ) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def test_interval_coalesces_missed_runs_and_clock_can_jump() -> None:
    anchor = datetime(2030, 1, 1, tzinfo=UTC)
    clock = FakeClock(anchor)
    clock.advance(timedelta(days=500))
    assert Recurrence("INTERVAL", 30).next_after(
        anchor, clock.now(), "UTC"
    ) == clock.now() + timedelta(seconds=30)
    assert Recurrence().next_after(anchor, clock.now(), "UTC") is None
    clock.advance(timedelta(days=-501))
    assert clock.now() < anchor


@pytest.mark.parametrize("payload", [{"raw": "x" * 9000}, {"nested": {"a": "b"}}])
def test_event_bounds(payload) -> None:
    with pytest.raises(ValueError):
        Event("signal", "fake", datetime(2030, 1, 1, tzinfo=UTC), payload=payload)
