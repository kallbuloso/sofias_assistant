"""Authenticated projections of Core reminders and durable attention."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from sofias_assistant.client_boundary.sessions import (
    ClientSession,
    ClientSessionRegistry,
)
from sofias_assistant.persistence.models import NotificationRecord, ScheduleRecord
from sofias_assistant.proactivity.models import Recurrence
from sofias_assistant.proactivity.runtime import ProactivityRuntime


class ReminderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reminder: str = Field(min_length=1, max_length=1024)
    due_at: datetime
    timezone: str = Field(min_length=1, max_length=128)
    recurrence: str = "ONCE"
    interval_seconds: int | None = Field(default=None, strict=True)


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reminder: str
    timezone: str
    status: str
    due_at: datetime
    next_run_at: datetime | None
    last_run_at: datetime | None
    recurrence: str
    correlation_id: UUID


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    event_id: UUID
    type: str
    severity: str
    title: str
    summary: str
    source: str
    created_at: datetime
    correlation_id: UUID
    action_reference: UUID | None
    state: str


def register_proactivity_routes(
    app: FastAPI,
    require_session: Callable[..., Any],
    sessions: ClientSessionRegistry,
    runtime: ProactivityRuntime,
) -> None:
    @app.post("/api/v1/reminders", status_code=201, response_model=ReminderResponse)
    async def create_reminder(
        body: ReminderRequest,
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> ReminderResponse:
        try:
            row = await runtime.scheduler.create_reminder(
                subject=f"client:{session.id}",
                reminder=body.reminder,
                due_at=body.due_at,
                zone=body.timezone,
                recurrence=Recurrence(body.recurrence, body.interval_seconds),
            )
        except ValueError:
            raise HTTPException(422, "Invalid reminder timing") from None
        return ReminderResponse.model_validate(row)

    async def reminder_row(schedule_id: UUID) -> ScheduleRecord:
        row = await runtime.scheduler.get(schedule_id)
        if row is None or row.kind != "REMINDER":
            raise HTTPException(404, "Reminder not found")
        return row

    @app.get("/api/v1/reminders/{schedule_id}", response_model=ReminderResponse)
    async def get_reminder(
        schedule_id: UUID, _: Annotated[ClientSession, Depends(require_session)]
    ) -> ReminderResponse:
        return ReminderResponse.model_validate(await reminder_row(schedule_id))

    @app.delete("/api/v1/reminders/{schedule_id}")
    async def cancel_reminder(
        schedule_id: UUID, _: Annotated[ClientSession, Depends(require_session)]
    ) -> dict[str, bool]:
        await reminder_row(schedule_id)
        return {"cancelled": await runtime.scheduler.cancel(schedule_id)}

    @app.get("/api/v1/notifications", response_model=list[NotificationResponse])
    async def pending(
        _: Annotated[ClientSession, Depends(require_session)],
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    ) -> list[NotificationResponse]:
        return [
            NotificationResponse.model_validate(row)
            for row in await runtime.notifications.pending(limit=limit, offset=offset)
        ]

    @app.post("/api/v1/notifications/{notification_id}/acknowledge")
    async def acknowledge(
        notification_id: UUID, _: Annotated[ClientSession, Depends(require_session)]
    ) -> dict[str, bool]:
        if await runtime.notifications.get(notification_id) is None:
            raise HTTPException(404, "Notification not found")
        return {
            "acknowledged": await runtime.notifications.acknowledge(notification_id)
        }

    @app.get("/api/v1/notification-stream")
    async def stream(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> StreamingResponse:
        return StreamingResponse(
            notification_stream(runtime, sessions, session),
            media_type="application/x-ndjson",
        )


async def notification_stream(
    runtime: ProactivityRuntime, sessions: ClientSessionRegistry, session: ClientSession
) -> AsyncGenerator[str]:
    def encode(row: NotificationRecord) -> str:
        return NotificationResponse.model_validate(row).model_dump_json() + "\n"

    # Subscribe before initial sync: reconnect/creation race can replay IDs but cannot lose them.
    async with runtime.notifications.listen() as queue:
        for row in await runtime.notifications.pending():
            if sessions.get(session.id) is None:
                return
            yield encode(row)
        while sessions.get(session.id) is not None:
            try:
                notification_id = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                yield '{"type":"heartbeat"}\n'
                continue
            if notification_id is None or sessions.get(session.id) is None:
                return
            notification = await runtime.notifications.get(notification_id)
            if notification is not None:
                yield encode(notification)
