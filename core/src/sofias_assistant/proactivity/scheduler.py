"""Persistent timing: atomic due advancement and event outbox insertion."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, text

from sofias_assistant.execution.models import ToolCall
from sofias_assistant.persistence.models import (
    EventRecord,
    ScheduleRecord,
    TaskRecord,
    ToolCallRecord,
)
from sofias_assistant.proactivity.events import EventBus, event_record
from sofias_assistant.proactivity.models import (
    Durability,
    Event,
    Recurrence,
    timezone,
    utc,
)


class Scheduler:
    def __init__(self, bus: EventBus) -> None:
        self.bus, self.sessions, self.clock = bus, bus.sessions, bus.clock

    async def create_reminder(
        self,
        *,
        subject: str,
        reminder: str,
        due_at: datetime,
        zone: str,
        recurrence: Recurrence = Recurrence(),
        correlation_id: UUID | None = None,
    ) -> ScheduleRecord:
        row = self._new(subject, reminder, due_at, zone, recurrence, correlation_id)
        async with self.sessions() as session:
            session.add(row)
            await session.commit()
        await self._audit(row, "SCHEDULE_CREATED")
        return row

    def _new(
        self,
        subject: str,
        reminder: str,
        due_at: datetime,
        zone: str,
        recurrence: Recurrence,
        correlation_id: UUID | None,
    ) -> ScheduleRecord:
        timezone(zone)
        if (
            not subject.strip()
            or len(subject) > 255
            or not reminder.strip()
            or len(reminder) > 1024
        ):
            raise ValueError("Schedule intent must be bounded and explicit")
        if not isinstance(recurrence, Recurrence):
            raise ValueError("Invalid recurrence")
        return ScheduleRecord(
            id=uuid4(),
            kind="REMINDER",
            subject=subject,
            reminder=reminder,
            timezone=zone,
            due_at=utc(due_at),
            next_run_at=utc(due_at),
            recurrence=recurrence.kind,
            interval_seconds=recurrence.interval_seconds,
            status="ACTIVE",
            created_at=self.clock.now(),
            correlation_id=correlation_id or uuid4(),
        )

    async def wait_task(
        self,
        task_id: UUID,
        call: ToolCall,
        due_at: datetime,
        zone: str,
        grant_id: UUID | None,
    ) -> ScheduleRecord:
        row = self._new(
            call.subject,
            "Resume scheduled Task",
            due_at,
            zone,
            Recurrence(),
            call.correlation_id,
        )
        row.kind, row.task_id, row.tool_call_id, row.grant_id = (
            "TASK_WAKEUP",
            task_id,
            call.id,
            grant_id,
        )
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            task = await session.get(TaskRecord, task_id)
            if task is None or task.status != "RUNNING" or task.cancellation_requested:
                raise ValueError("Only a running Task can wait for a schedule")
            if (
                task.subject != call.subject
                or task.correlation_id != call.correlation_id
            ):
                raise ValueError(
                    "Continuation must preserve Task subject and correlation"
                )
            existing_call = await session.get(ToolCallRecord, call.id)
            if existing_call is not None:
                if existing_call.status != "QUEUED":
                    raise ValueError(
                        "Continuation ToolCall must not have been executed"
                    )
                # Durable pre-execution intent (Gap A) already persisted this
                # ToolCall when the Task was created; mark it scheduled in
                # place instead of rejecting an id that was never executed.
                existing_call.status = "SCHEDULED"
            else:
                session.add(
                    ToolCallRecord(
                        id=call.id,
                        name=call.name,
                        subject=call.subject,
                        session_id=call.session_id,
                        arguments_json=json.dumps(dict(call.arguments)),
                        status="SCHEDULED",
                        correlation_id=call.correlation_id,
                        causation_id=call.causation_id,
                        created_at=self.clock.now(),
                    )
                )
            await session.flush()
            task.status, task.claimed_by = "WAITING_SCHEDULE", None
            task.updated_at = self.clock.now()
            session.add(row)
            await session.commit()
        await self._audit(row, "TASK_WAITING_SCHEDULE")
        return row

    async def tick(self) -> int:
        now = self.clock.now()
        async with self.sessions() as session:
            # SQLite write reservation serializes competing due/cancel transactions.
            # No committed CLAIMED intermediate state exists to lose on crash.
            await session.execute(text("BEGIN IMMEDIATE"))
            rows = list(
                await session.scalars(
                    select(ScheduleRecord)
                    .where(
                        ScheduleRecord.status == "ACTIVE",
                        ScheduleRecord.next_run_at <= now,
                    )
                    .order_by(ScheduleRecord.next_run_at, ScheduleRecord.id)
                    .limit(100)
                )
            )
            for row in rows:
                due = row.next_run_at
                assert due is not None
                if row.task_id is not None:
                    task = await session.get(TaskRecord, row.task_id)
                    if (
                        task is None
                        or task.cancellation_requested
                        or task.status != "WAITING_SCHEDULE"
                    ):
                        row.status, row.next_run_at = "CANCELLED", None
                        continue
                event = Event(
                    id=uuid5(row.id, due.isoformat()),
                    type="ReminderDue" if row.kind == "REMINDER" else "TaskScheduleDue",
                    source="scheduler",
                    occurred_at=now,
                    correlation_id=row.correlation_id,
                    causation_id=row.id,
                    durability=Durability.DURABLE,
                    payload={
                        "schedule_id": str(row.id),
                        "due_at": due.isoformat(),
                        "late": str(now > due).lower(),
                    },
                )
                session.add(event_record(event))
                await session.flush()
                row.last_event_id, row.last_run_at = event.id, now
                row.next_run_at = Recurrence(
                    row.recurrence, row.interval_seconds
                ).next_after(row.due_at, now, row.timezone)
                if row.next_run_at is None:
                    row.status = "COMPLETED"
            await session.commit()
        for row in rows:
            await self._audit(row, "SCHEDULE_OBSERVED")
        return len(rows)

    async def get(self, schedule_id: UUID) -> ScheduleRecord | None:
        async with self.sessions() as session:
            return await session.get(ScheduleRecord, schedule_id)

    async def cancel(self, schedule_id: UUID) -> bool:
        async with self.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.get(ScheduleRecord, schedule_id)
            if row is None or row.status == "CANCELLED":
                return False
            if row.kind == "TASK_WAKEUP":
                raise ValueError("Cancel scheduled Tasks through TaskRuntime")
            row.status, row.next_run_at = "CANCELLED", None
            events = await session.scalars(
                select(EventRecord).where(
                    EventRecord.causation_id == row.id,
                    EventRecord.status == "PENDING",
                )
            )
            for event in events:
                event.status = "CANCELLED"
            await session.commit()
        await self._audit(row, "SCHEDULE_CANCELLED")
        return True

    async def _audit(self, row: ScheduleRecord, event_type: str) -> None:
        await self.bus.audit.record(
            event_type=event_type,
            actor="Sofia/Core",
            subject=row.subject,
            action="schedule",
            resource=str(row.id),
            outcome=row.status,
            origin="SCHEDULE",
            correlation_id=row.correlation_id,
            causation_id=row.last_event_id,
            task_id=row.task_id,
            tool_call_id=row.tool_call_id,
            metadata={
                "schedule_id": str(row.id),
                "event_id": str(row.last_event_id) if row.last_event_id else None,
            },
        )
