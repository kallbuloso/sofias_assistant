"""Local event delivery with selective durable outbox and bounded retries."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.execution.audit import AuditService
from sofias_assistant.persistence.models import EventRecord
from sofias_assistant.proactivity.models import Clock, Durability, Event

Handler = Callable[[Event], Awaitable[None]]


def event_record(event: Event, *, available_at: datetime | None = None) -> EventRecord:
    return EventRecord(
        id=event.id,
        type=event.type,
        source=event.source,
        kind=event.kind,
        occurred_at=event.occurred_at,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        payload_json=json.dumps(event.payload, sort_keys=True),
        metadata_json=json.dumps(event.metadata, sort_keys=True),
        status="PENDING",
        available_at=available_at or event.occurred_at,
        attempts=0,
        completed_handlers_json="[]",
    )


def to_event(row: EventRecord) -> Event:
    return Event(
        id=row.id,
        type=row.type,
        source=row.source,
        kind=row.kind,
        occurred_at=row.occurred_at,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        payload=json.loads(row.payload_json),
        metadata=json.loads(row.metadata_json),
        durability=Durability.DURABLE,
    )


class EventBus:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        audit: AuditService,
        *,
        handler_timeout: float = 5.0,
    ) -> None:
        if not 0 < handler_timeout <= 5:
            raise ValueError("Handler timeout must be bounded to five seconds")
        self.sessions, self.clock, self.audit = sessions, clock, audit
        self.handler_timeout = handler_timeout
        self._handlers: dict[str, dict[str, tuple[Handler, bool]]] = {}
        self._lock = asyncio.Lock()
        self._stopped = False
        self.owner = uuid4()
        self._ephemeral_tasks: set[asyncio.Task[None]] = set()

    def subscribe(
        self, event_type: str, name: str, handler: Handler, *, retry_safe: bool = False
    ) -> None:
        handlers = self._handlers.setdefault(event_type, {})
        if name in handlers or len(handlers) >= 16 or not name.strip():
            raise ValueError(
                "Invalid/duplicate subscription or subscriber bound exceeded"
            )
        handlers[name] = (handler, retry_safe)

    async def publish(self, event: Event) -> None:
        event = copy.deepcopy(event)
        if self._stopped:
            raise RuntimeError("Event runtime is stopped")
        if event.durability is Durability.EPHEMERAL:
            task = asyncio.create_task(self._dispatch_ephemeral(event))
            self._ephemeral_tasks.add(task)
            try:
                await task
            finally:
                self._ephemeral_tasks.discard(task)
            return
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            prior = await session.get(EventRecord, event.id)
            if prior is not None:
                if to_event(prior) != event:
                    raise ValueError(
                        "Event identity cannot be reused for different data"
                    )
            else:
                row = event_record(event)
                row.available_at = self.clock.now()
                session.add(row)
            await session.commit()

    async def _dispatch_ephemeral(self, event: Event) -> None:
        for name, (handler, _) in tuple(self._handlers.get(event.type, {}).items()):
            await self._deliver(event, name, handler)

    async def dispatch_pending(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 100:
            raise ValueError("Dispatch batch must be bounded")
        async with self._lock:
            count = 0
            while not self._stopped and count < limit:
                row = await self._claim()
                if row is None:
                    break
                event = to_event(row)
                completed = set(json.loads(row.completed_handlers_json))
                retryable = True
                failed = False
                try:
                    for name, (handler, retry_safe) in tuple(
                        self._handlers[event.type].items()
                    ):
                        if name in completed:
                            continue
                        marker = "started:" + name
                        if marker in completed:
                            # A crash left a non-retry-safe effect uncertain.
                            failed, retryable = True, False
                            continue
                        if not retry_safe:
                            completed.add(marker)
                            await self._save(
                                row.id,
                                completed_handlers_json=json.dumps(sorted(completed)),
                            )
                        if await self._deliver(event, name, handler):
                            completed.discard(marker)
                            completed.add(name)
                            await self._save(
                                row.id,
                                completed_handlers_json=json.dumps(sorted(completed)),
                            )
                        else:
                            failed = True
                            retryable = retryable and retry_safe
                    status = (
                        "DELIVERED"
                        if not failed
                        else ("PENDING" if retryable and row.attempts < 3 else "FAILED")
                    )
                    await self._save(
                        row.id,
                        status=status,
                        owner=None,
                        lease_until=None,
                        available_at=self.clock.now()
                        + timedelta(seconds=2**row.attempts),
                    )
                    await self.audit.record(
                        event_type="EVENT_DELIVERY_COMPLETED",
                        actor="Sofia/Core",
                        subject="Sofia/Core",
                        action=event.type,
                        resource=str(event.id),
                        outcome=status,
                        origin="EVENT",
                        correlation_id=event.correlation_id,
                        causation_id=event.id,
                        metadata={"event_id": str(event.id), "attempts": row.attempts},
                    )
                except asyncio.CancelledError:
                    await self._save(
                        row.id, status="PENDING", owner=None, lease_until=None
                    )
                    raise
                count += 1
            return count

    async def _claim(self) -> EventRecord | None:
        if not self._handlers:
            return None
        now = self.clock.now()
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.scalar(
                select(EventRecord)
                .where(
                    EventRecord.type.in_(tuple(self._handlers)),
                    or_(
                        (EventRecord.status == "PENDING")
                        & (EventRecord.available_at <= now),
                        (EventRecord.status == "DISPATCHING")
                        & (EventRecord.lease_until <= now),
                    ),
                )
                .order_by(EventRecord.available_at, EventRecord.id)
                .limit(1)
            )
            if row is not None:
                row.status, row.owner = "DISPATCHING", self.owner
                row.lease_until = now + timedelta(seconds=300)
                row.attempts += 1
            await session.commit()
            return row

    async def _save(self, event_id: UUID, **values: object) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(EventRecord)
                .where(EventRecord.id == event_id, EventRecord.owner == self.owner)
                .values(**values)
            )
            await session.commit()

    async def _deliver(self, event: Event, name: str, handler: Handler) -> bool:
        try:
            async with asyncio.timeout(self.handler_timeout):
                await handler(copy.deepcopy(event))
            outcome = "DELIVERED"
        except Exception:
            outcome = "FAILED"
        await self.audit.record(
            event_type="EVENT_HANDLER_COMPLETED",
            actor="Sofia/Core",
            subject="Sofia/Core",
            action=event.type,
            resource=str(event.id),
            outcome=outcome,
            origin="EVENT",
            correlation_id=event.correlation_id,
            causation_id=event.id,
            metadata={"event_id": str(event.id), "handler": name},
        )
        return outcome == "DELIVERED"

    async def stop(self) -> None:
        self._stopped = True
        pending = tuple(self._ephemeral_tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        async with self._lock:
            pass


class EventSource(Protocol):
    def events(self) -> AsyncIterator[Event]: ...


class FakeEventSource:
    def __init__(self, events: tuple[Event, ...]) -> None:
        self._events = events

    async def events(self) -> AsyncIterator[Event]:
        for event in self._events:
            if event.kind != "EXTERNAL":
                raise ValueError("EventSource must normalize external events")
            yield event


async def consume_source(source: EventSource, bus: EventBus) -> None:
    """Explicitly invoked source lifecycle; registration never starts observation."""
    async for event in source.events():
        await bus.publish(event)
