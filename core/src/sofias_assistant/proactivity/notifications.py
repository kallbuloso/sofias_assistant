"""Durable attention projection and a bounded live delivery seam."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid5

from sqlalchemy import exists, func, select, text, update

from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.persistence.models import (
    ApplicationSetting,
    ConfirmationRequestRecord,
    EventRecord,
    NotificationRecord,
    ScheduleRecord,
    TaskRecord,
    ToolCallRecord,
)
from sofias_assistant.proactivity.events import EventBus, event_record, to_event
from sofias_assistant.proactivity.models import Durability, Event

NOTIFICATION_TYPES = {
    "TaskCompleted": "Task completed",
    "ReminderDue": "Reminder due",
    "PermissionRequested": "Permission requested",
    "SubsystemDegraded": "Subsystem degraded",
    "TaskRecoveryRequired": "Recovery attention required",
}

_RECOVERY_PAUSE_ERROR_CODES = ("RECOVERY_REQUIRED", "SCHEDULE_RECONCILIATION_REQUIRED")


class NotificationService:
    def __init__(self, bus: EventBus) -> None:
        self.bus, self.sessions, self.clock = bus, bus.sessions, bus.clock
        self._listeners: set[asyncio.Queue[UUID | None]] = set()
        for event_type in NOTIFICATION_TYPES:
            bus.subscribe(event_type, "notifications", self.on_event, retry_safe=True)

    async def on_event(self, event: Event) -> None:
        if event.durability is not Durability.DURABLE or event.kind != "DOMAIN":
            raise ValueError("Attention requires a durable domain fact")
        summary = NOTIFICATION_TYPES[event.type]
        action_reference = event.causation_id
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            stored = await session.get(EventRecord, event.id)
            if stored is None or to_event(stored) != event:
                raise ValueError("Durable event missing or identity mismatch")
            if event.type == "SubsystemDegraded":
                summary = (
                    "Subsystem degraded: " + event.payload.get("component", "unknown")
                )[:1024]
            if event.type == "TaskCompleted":
                summary = "Task finished: " + event.payload.get("status", "unknown")
            if event.type == "ReminderDue":
                schedule = await session.get(ScheduleRecord, event.causation_id)
                if schedule is None or schedule.kind != "REMINDER":
                    raise ValueError("Reminder timing reference missing")
                summary = schedule.reminder
                if event.payload.get("late") == "true":
                    summary = ("Overdue: " + summary)[:1024]
            if event.type == "TaskRecoveryRequired":
                summary = (
                    "Task paused: " + event.payload.get("reason", "recovery required")
                )[:1024]
            notification = await session.scalar(
                select(NotificationRecord).where(
                    NotificationRecord.event_id == event.id
                )
            )
            if notification is None:
                notification = NotificationRecord(
                    id=uuid5(event.id, "notification"),
                    event_id=event.id,
                    type=event.type,
                    severity="warning"
                    if event.type
                    in {
                        "PermissionRequested",
                        "SubsystemDegraded",
                        "TaskRecoveryRequired",
                    }
                    else "info",
                    title=NOTIFICATION_TYPES[event.type],
                    summary=summary,
                    source=event.source,
                    action_reference=action_reference,
                    correlation_id=event.correlation_id,
                    created_at=self.clock.now(),
                    state="PENDING",
                )
                session.add(notification)
            await session.commit()
        await self.bus.audit.record(
            event_type="NOTIFICATION_PRODUCED",
            actor="Sofia/Core",
            subject="local-user",
            action=event.type,
            resource=str(notification.id),
            outcome=notification.state,
            origin="NOTIFICATION",
            correlation_id=event.correlation_id,
            causation_id=event.id,
            task_id=action_reference
            if event.type in {"TaskCompleted", "TaskRecoveryRequired"}
            else None,
            confirmation_id=action_reference
            if event.type == "PermissionRequested"
            else None,
            metadata={
                "notification_id": str(notification.id),
                "event_id": str(event.id),
                "action_reference": str(action_reference) if action_reference else None,
            },
        )
        for queue in tuple(self._listeners):
            try:
                queue.put_nowait(notification.id)
            except asyncio.QueueFull:
                # A slow client must resync durable state, never block the producer.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self._listeners.discard(queue)

    async def pending(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[NotificationRecord]:
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("Notification query must be bounded")
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(NotificationRecord)
                    .where(NotificationRecord.state == "PENDING")
                    .order_by(NotificationRecord.created_at, NotificationRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
            )

    async def get(self, notification_id: UUID) -> NotificationRecord | None:
        async with self.sessions() as session:
            return await session.get(NotificationRecord, notification_id)

    async def acknowledge(self, notification_id: UUID) -> bool:
        async with self.sessions() as session:
            notification = await session.get(NotificationRecord, notification_id)
            if notification is None:
                return False
            result = await session.execute(
                update(NotificationRecord)
                .where(
                    NotificationRecord.id == notification_id,
                    NotificationRecord.state == "PENDING",
                )
                .values(state="ACKNOWLEDGED", acknowledged_at=self.clock.now())
            )
            await session.commit()
        changed = bool(getattr(result, "rowcount", 0))
        if changed:
            await self.bus.audit.record(
                event_type="NOTIFICATION_ACKNOWLEDGED",
                actor="local-user",
                subject="local-user",
                action="notification.acknowledge",
                resource=str(notification_id),
                outcome="ACKNOWLEDGED",
                origin="NOTIFICATION",
                correlation_id=notification.correlation_id,
                causation_id=notification.event_id,
                metadata={"notification_id": str(notification_id)},
            )
        return changed

    @asynccontextmanager
    async def listen(self) -> AsyncIterator[asyncio.Queue[UUID | None]]:
        queue: asyncio.Queue[UUID | None] = asyncio.Queue(maxsize=64)
        self._listeners.add(queue)
        try:
            yield queue
        finally:
            self._listeners.discard(queue)

    async def stop(self) -> None:
        for queue in tuple(self._listeners):
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)
        self._listeners.clear()

    async def collect_operational_events(self) -> None:
        """Reconcile durable source state after crash; never read Audit as truth."""
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            tasks = await session.scalars(
                select(TaskRecord)
                .where(
                    TaskRecord.status.in_(("SUCCEEDED", "FAILED", "CANCELLED")),
                    ~exists(
                        select(EventRecord.id).where(
                            EventRecord.causation_id == TaskRecord.id,
                            EventRecord.type == "TaskCompleted",
                            EventRecord.occurred_at
                            == func.coalesce(
                                TaskRecord.finished_at, TaskRecord.updated_at
                            ),
                        )
                    ),
                )
                .limit(100)
            )
            for task in tasks:
                session.add(
                    event_record(
                        Event(
                            id=uuid5(
                                task.id,
                                "TaskCompleted:"
                                + (task.finished_at or task.updated_at).isoformat(),
                            ),
                            type="TaskCompleted",
                            source="task-runtime",
                            occurred_at=task.finished_at or task.updated_at,
                            correlation_id=task.correlation_id,
                            causation_id=task.id,
                            durability=Durability.DURABLE,
                            payload={"task_id": str(task.id), "status": task.status},
                        ),
                        available_at=self.clock.now(),
                    )
                )
            paused_tasks = await session.scalars(
                select(TaskRecord)
                .where(
                    TaskRecord.status == "PAUSED",
                    TaskRecord.error_code.in_(_RECOVERY_PAUSE_ERROR_CODES),
                    ~exists(
                        select(EventRecord.id).where(
                            EventRecord.causation_id == TaskRecord.id,
                            EventRecord.type == "TaskRecoveryRequired",
                            EventRecord.occurred_at == TaskRecord.updated_at,
                        )
                    ),
                )
                .limit(100)
            )
            for task in paused_tasks:
                session.add(
                    event_record(
                        Event(
                            id=uuid5(
                                task.id,
                                "TaskRecoveryRequired:" + task.updated_at.isoformat(),
                            ),
                            type="TaskRecoveryRequired",
                            source="task-runtime",
                            occurred_at=task.updated_at,
                            correlation_id=task.correlation_id,
                            causation_id=task.id,
                            durability=Durability.DURABLE,
                            payload={
                                "task_id": str(task.id),
                                "reason": task.error_code or "",
                            },
                        ),
                        available_at=self.clock.now(),
                    )
                )
            confirmations = await session.scalars(
                select(ConfirmationRequestRecord)
                .where(
                    ConfirmationRequestRecord.status == "PENDING",
                    ~exists(
                        select(EventRecord.id).where(
                            EventRecord.causation_id == ConfirmationRequestRecord.id,
                            EventRecord.type == "PermissionRequested",
                        )
                    ),
                )
                .limit(100)
            )
            for confirmation in confirmations:
                call = await session.get(ToolCallRecord, confirmation.tool_call_id)
                session.add(
                    event_record(
                        Event(
                            id=uuid5(confirmation.id, "PermissionRequested"),
                            type="PermissionRequested",
                            source="execution-runtime",
                            occurred_at=confirmation.created_at,
                            correlation_id=call.correlation_id
                            if call
                            else confirmation.tool_call_id,
                            causation_id=confirmation.id,
                            durability=Durability.DURABLE,
                            payload={
                                "confirmation_id": str(confirmation.id),
                                "tool_call_id": str(confirmation.tool_call_id),
                            },
                        ),
                        available_at=self.clock.now(),
                    )
                )
            await session.commit()

    async def observe_health(self, health: ComponentHealth) -> None:
        """Persist transition deduplication plus outbox atomically."""
        key = "proactivity.health." + health.name
        if len(key) > 255:
            raise ValueError("Health component name too long")
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            previous = await session.get(ApplicationSetting, key)
            prior = json.loads(previous.value_json) if previous else {}
            if prior.get("status") == health.status.value:
                return
            revision = int(prior.get("revision", 0)) + 1
            value = json.dumps({"status": health.status.value, "revision": revision})
            if previous is None:
                session.add(
                    ApplicationSetting(
                        key=key, value_json=value, updated_at=self.clock.now()
                    )
                )
            else:
                previous.value_json, previous.updated_at = value, self.clock.now()
            if health.status in {HealthStatus.DEGRADED, HealthStatus.UNHEALTHY}:
                event = Event(
                    type="SubsystemDegraded",
                    source="health",
                    occurred_at=self.clock.now(),
                    durability=Durability.DURABLE,
                    payload={"component": health.name, "status": health.status.value},
                )
                session.add(event_record(event))
            await session.commit()
