"""Durable local Task runtime built on the I4 authorized Tool facade."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select, text

from sofias_assistant.persistence.models import (
    EventRecord,
    ScheduleRecord,
    TaskRecord,
    ToolCallRecord,
)
from sofias_assistant.proactivity.models import Event

if TYPE_CHECKING:
    from sofias_assistant.proactivity.scheduler import Scheduler

from sofias_assistant.execution.models import (
    AuthorityContext,
    Task,
    TaskAttempt,
    TaskExecutionStrategy,
    TaskStatus,
    ToolCall,
    ToolError,
)
from sofias_assistant.execution.runtime import ExecutionRuntime


class TaskRuntime:
    """Single-Core queue/claim owner; no distributed worker is implied."""

    def __init__(
        self, execution: ExecutionRuntime, *, scheduler: Scheduler | None = None
    ) -> None:
        self.execution = execution
        self.store = execution.store
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._pending_confirmations: dict[UUID, UUID] = {}
        self._lock = asyncio.Lock()
        self._owner = f"core-{uuid4()}"
        self._stopping = False
        self.scheduler = scheduler

    async def create_task(
        self,
        *,
        objective: str,
        subject: str,
        tool_call: ToolCall,
        authority: AuthorityContext | None = None,
        conversation_id: UUID | None = None,
        delegation_id: UUID | None = None,
        execution_strategy: TaskExecutionStrategy = TaskExecutionStrategy.DIRECT_TOOL,
        grant_id: UUID | None = None,
        wait_until: datetime | None = None,
        timezone: str = "UTC",
    ) -> Task:
        if self._stopping:
            raise RuntimeError("Task runtime is stopping")
        if wait_until is not None:
            from sofias_assistant.proactivity.models import timezone as validate_zone
            from sofias_assistant.proactivity.models import utc

            if self.scheduler is None:
                raise ValueError("Scheduler is not configured")
            if subject != tool_call.subject or (
                authority is not None and authority.subject != subject
            ):
                raise ValueError("Scheduled Task and continuation authority must match")
            utc(wait_until)
            validate_zone(timezone)
        task = Task(
            objective=objective,
            subject=subject,
            origin="TASK",
            authority=authority or AuthorityContext(subject, tool_call.session_id),
            conversation_id=conversation_id,
            delegation_id=delegation_id,
            execution_strategy=execution_strategy,
            correlation_id=tool_call.correlation_id,
            causation_id=tool_call.causation_id,
        )
        await self.store.save_task(task)
        await self.execution.audit.record(
            event_type="TASK_CREATED",
            actor=subject,
            subject=subject,
            action="task.create",
            resource=str(task.id),
            outcome=task.status.value,
            origin=task.origin.upper() if task.origin else "TASK",
            correlation_id=task.correlation_id,
            task_id=task.id,
            metadata={"objective_summary": objective[:160]},
        )
        self._cancel_events[task.id] = asyncio.Event()
        self._tasks[task.id] = asyncio.create_task(
            self._run(
                task.id,
                tool_call,
                grant_id=grant_id,
                wait_until=wait_until,
                timezone=timezone,
            )
        )
        return task

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self.store.get_task(task_id)

    async def list_tasks(self, subject: str, *, limit: int = 50) -> tuple[Task, ...]:
        return await self.store.list_tasks(subject, limit=limit)

    async def create_agent_task(
        self,
        *,
        objective: str,
        subject: str,
        authority: AuthorityContext,
        conversation_id: UUID | None = None,
        delegation_id: UUID | None = None,
    ) -> Task:
        """Create durable work for Sofia/root to delegate to an AgentRun."""

        if self._stopping:
            raise RuntimeError("Task runtime is stopping")
        task = Task(
            objective=objective,
            subject=subject,
            origin="TASK",
            authority=authority,
            conversation_id=conversation_id,
            delegation_id=delegation_id,
            execution_strategy=TaskExecutionStrategy.AGENT,
        )
        await self.store.save_task(task)
        await self.execution.audit.record(
            event_type="TASK_CREATED",
            actor=subject,
            subject=subject,
            action="task.create",
            resource=str(task.id),
            outcome=task.status.value,
            origin="TASK",
            correlation_id=task.correlation_id,
            task_id=task.id,
            metadata={"objective_summary": objective[:160], "strategy": "AGENT"},
        )
        self._cancel_events[task.id] = asyncio.Event()
        return task

    async def complete_agent_task(
        self, task_id: UUID, *, result: object, succeeded: bool, agent_run_id: UUID
    ) -> Task:
        """Project an Agent result back onto its parent Task; never replace it."""

        task = await self.store.get_task(task_id)
        if task is None:
            raise KeyError("Task not found")
        status = TaskStatus.SUCCEEDED if succeeded else TaskStatus.FAILED
        updated = replace(
            task,
            status=status,
            result=result,
            error=None if succeeded else ToolError("AGENT_FAILED", "AgentRun failed"),
            updated_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        await self.store.update_task(updated)
        await self.execution.audit.record(
            event_type="TASK_STATE_CHANGED",
            actor=task.subject,
            subject=task.subject,
            action="task.transition",
            resource=str(task.id),
            outcome=status.value,
            origin="TASK",
            correlation_id=task.correlation_id,
            causation_id=agent_run_id,
            task_id=task.id,
            agent_run_id=agent_run_id,
            metadata={"strategy": "AGENT"},
        )
        return updated

    def pending_confirmation(self, task_id: UUID) -> UUID | None:
        return self._pending_confirmations.get(task_id)

    async def cancel_task(self, task_id: UUID) -> Task:
        async with self._lock:
            task = await self.store.get_task(task_id)
            if task is None:
                raise KeyError("Task not found")
            if task.status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return task
            updated = replace(
                task,
                status=TaskStatus.CANCELLING,
                cancellation_requested=True,
                updated_at=datetime.now(UTC),
            )
            await self.store.update_task(updated)
            await self.execution.audit.record(
                event_type="TASK_CANCELLATION_REQUESTED",
                actor=task.subject,
                subject=task.subject,
                action="task.cancel",
                resource=str(task.id),
                outcome=updated.status.value,
                origin="TASK",
                correlation_id=task.correlation_id,
                task_id=task.id,
            )
            event = self._cancel_events.setdefault(task_id, asyncio.Event())
            event.set()
            runner = self._tasks.get(task_id)
            if runner is not None and not runner.done():
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
            elif runner is not None:
                await self._finish_cancelled(task_id)
            await self._finish_cancelled(task_id)
            return await self.store.get_task(task_id) or updated

    async def approve_confirmation(self, task_id: UUID, confirmation_id: UUID) -> Task:
        task = await self.store.get_task(task_id)
        if task is None:
            raise KeyError("Task not found")
        if task.status is not TaskStatus.WAITING_CONFIRMATION:
            raise ValueError("Task is not waiting for confirmation")
        result = await self.execution.approve_confirmation(confirmation_id)
        if result.status == "SUCCEEDED":
            updated = replace(
                task,
                status=TaskStatus.SUCCEEDED,
                result=result.value,
                updated_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        else:
            updated = replace(
                task,
                status=TaskStatus.FAILED,
                error=result.error,
                updated_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        await self.store.update_task(updated)
        self._pending_confirmations.pop(task_id, None)
        attempts = await self.store.list_task_attempts(task_id)
        if attempts:
            latest = attempts[-1]
            await self.store.update_task_attempt(
                replace(
                    latest,
                    status=updated.status,
                    result=result.value,
                    error=result.error,
                    finished_at=datetime.now(UTC),
                )
            )
        return updated

    async def retry_task(self, task_id: UUID, tool_call: ToolCall) -> Task:
        """Start a new append-only attempt only for an idempotent Tool."""

        task = await self.store.get_task(task_id)
        if task is None:
            raise KeyError("Task not found")
        if task.status is not TaskStatus.FAILED:
            raise ValueError("Only failed Tasks may be retried")
        spec = self.execution.registry.resolve(tool_call.name)
        if not spec.idempotent:
            raise ValueError("Non-idempotent Tool cannot be blindly retried")
        retry = replace(
            task,
            status=TaskStatus.QUEUED,
            result=None,
            error=None,
            cancellation_requested=False,
            claimed_by=None,
            updated_at=datetime.now(UTC),
            finished_at=None,
        )
        await self.store.update_task(retry)
        self._cancel_events[task_id] = asyncio.Event()
        self._tasks[task_id] = asyncio.create_task(self._run(task_id, tool_call))
        return retry

    async def stop(self) -> None:
        self._stopping = True
        for event in self._cancel_events.values():
            event.set()
        tasks = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._cancel_events.clear()
        self._pending_confirmations.clear()

    async def _run(
        self,
        task_id: UUID,
        tool_call: ToolCall,
        *,
        grant_id: UUID | None = None,
        wait_until: datetime | None = None,
        timezone: str = "UTC",
    ) -> None:
        claimed = await self.store.claim_task(task_id, self._owner)
        if claimed is None:
            return
        attempts = await self.store.list_task_attempts(task_id)
        try:
            execution_mode = self.execution.registry.resolve(
                tool_call.name
            ).execution_mode
        except KeyError:
            execution_mode = None
        attempt = TaskAttempt(
            task_id=task_id,
            attempt_number=len(attempts) + 1,
            tool_call_id=tool_call.id,
            execution_mode=execution_mode,
            status=TaskStatus.RUNNING,
            started_at=datetime.now(UTC),
            correlation_id=claimed.correlation_id,
            causation_id=claimed.id,
        )
        await self.store.save_task_attempt(attempt)
        await self.execution.audit.record(
            event_type="TASK_ATTEMPT_STARTED",
            actor=claimed.subject,
            subject=claimed.subject,
            action="task.attempt",
            resource=str(task_id),
            outcome=attempt.status.value,
            origin="TASK",
            correlation_id=claimed.correlation_id,
            causation_id=claimed.id,
            task_id=task_id,
            attempt_id=attempt.id,
            tool_call_id=attempt.tool_call_id,
            execution_context={
                "mode": execution_mode.value if execution_mode else None
            },
        )
        cancel_event = self._cancel_events[task_id]
        try:
            if cancel_event.is_set():
                await self._finish_cancelled(task_id)
                return
            if wait_until is not None:
                assert self.scheduler is not None
                await self.scheduler.wait_task(
                    task_id, tool_call, wait_until, timezone, grant_id
                )
                await self.store.update_task_attempt(
                    replace(
                        attempt,
                        status=TaskStatus.WAITING_SCHEDULE,
                        finished_at=datetime.now(UTC),
                    )
                )
                return
            result = await self.execution.invoke(
                tool_call, grant_id=grant_id, origin="TASK", task_id=task_id
            )
            current = await self.store.get_task(task_id)
            if current is None:
                return
            if result.status == "CONFIRMATION_REQUIRED":
                waiting = replace(
                    current,
                    status=TaskStatus.WAITING_CONFIRMATION,
                    updated_at=datetime.now(UTC),
                )
                if result.confirmation_id is not None:
                    self._pending_confirmations[task_id] = result.confirmation_id
                await self.store.update_task(waiting)
                await self.execution.audit.record(
                    event_type="TASK_STATE_CHANGED",
                    actor=waiting.subject,
                    subject=waiting.subject,
                    action="task.transition",
                    resource=str(task_id),
                    outcome=waiting.status.value,
                    origin="TASK",
                    correlation_id=waiting.correlation_id,
                    causation_id=attempt.id,
                    task_id=task_id,
                )
                return
            if cancel_event.is_set() or current.cancellation_requested:
                await self._finish_cancelled(task_id)
                return
            final = replace(
                current,
                status=TaskStatus.SUCCEEDED
                if result.status == "SUCCEEDED"
                else TaskStatus.FAILED,
                result=result.value,
                error=result.error,
                updated_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
            await self.store.update_task(final)
            await self.store.update_task_attempt(
                replace(
                    attempt,
                    status=final.status,
                    result=result.value,
                    error=result.error,
                    finished_at=datetime.now(UTC),
                )
            )
            await self.execution.audit.record(
                event_type="TASK_STATE_CHANGED",
                actor=final.subject,
                subject=final.subject,
                action="task.transition",
                resource=str(task_id),
                outcome=final.status.value,
                origin="TASK",
                correlation_id=final.correlation_id,
                causation_id=attempt.id,
                task_id=task_id,
                attempt_id=attempt.id,
            )
        except asyncio.CancelledError:
            if not self._stopping:
                await self._finish_cancelled(task_id)
        except Exception:
            current = await self.store.get_task(task_id)
            if current is not None and current.status not in {
                TaskStatus.CANCELLED,
                TaskStatus.SUCCEEDED,
            }:
                await self.store.update_task(
                    replace(
                        current,
                        status=TaskStatus.FAILED,
                        error=ToolError("TASK_FAILED", "Task execution failed"),
                        updated_at=datetime.now(UTC),
                        finished_at=datetime.now(UTC),
                    )
                )
        finally:
            self._tasks.pop(task_id, None)

    async def resume_schedule(self, event: Event) -> None:
        """Wake only the persisted occurrence/continuation selected by root."""
        from sofias_assistant.proactivity.events import to_event

        if self.scheduler is None or self._stopping:
            raise RuntimeError("Scheduled Task runtime unavailable")
        async with self.scheduler.sessions() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            schedule = await session.get(ScheduleRecord, event.causation_id)
            stored = await session.get(EventRecord, event.id)
            if (
                schedule is None
                or stored is None
                or schedule.kind != "TASK_WAKEUP"
                or schedule.last_event_id != event.id
                or event.source != "scheduler"
                or event.kind != "DOMAIN"
                or stored.source != "scheduler"
                or to_event(stored) != event
                or event.type != "TaskScheduleDue"
            ):
                raise ValueError("Event is not the persisted Task schedule occurrence")
            task = await session.get(TaskRecord, schedule.task_id)
            if (
                task is not None
                and not task.cancellation_requested
                and task.status == "WAITING_SCHEDULE"
            ):
                task.status, task.claimed_by = "QUEUED", None
                task.updated_at = self.scheduler.clock.now()
            await session.commit()
        await self.recover_scheduled_tasks()

    async def recover_scheduled_tasks(self, *, startup: bool = False) -> None:
        """Recover queued continuations; uncertain running effects pause explicitly."""
        if self.scheduler is None or self._stopping:
            return
        async with self._lock:
            async with self.scheduler.sessions() as session:
                await session.execute(text("BEGIN IMMEDIATE"))
                pairs = (
                    await session.execute(
                        select(ScheduleRecord, TaskRecord)
                        .join(TaskRecord, ScheduleRecord.task_id == TaskRecord.id)
                        .where(
                            ScheduleRecord.kind == "TASK_WAKEUP",
                            ScheduleRecord.status == "COMPLETED",
                            TaskRecord.status.in_(("QUEUED", "RUNNING")),
                            TaskRecord.cancellation_requested.is_(False),
                        )
                        .limit(100)
                    )
                ).all()
                eligible = []
                for schedule, task in pairs:
                    if task.id in self._tasks:
                        continue
                    if task.status == "RUNNING":
                        if not startup:
                            continue
                        call = await session.get(ToolCallRecord, schedule.tool_call_id)
                        if call is None or call.status == "RUNNING":
                            task.status, task.error_code = (
                                "PAUSED",
                                "SCHEDULE_RECONCILIATION_REQUIRED",
                            )
                            task.error_message = (
                                "Interrupted execution requires reconciliation"
                            )
                            continue
                        task.status, task.claimed_by = "QUEUED", None
                    eligible.append((task.id, schedule.tool_call_id, schedule.grant_id))
                await session.commit()
            for task_id, call_id, grant_id in eligible:
                stored_call = await self.store.get_tool_call(call_id)
                if stored_call is None:
                    continue
                self._cancel_events[task_id] = asyncio.Event()
                self._tasks[task_id] = asyncio.create_task(
                    self._run(task_id, stored_call[0], grant_id=grant_id)
                )

    async def _finish_cancelled(self, task_id: UUID) -> None:
        task = await self.store.get_task(task_id)
        if task is None or task.status is TaskStatus.CANCELLED:
            return
        await self.store.update_task(
            replace(
                task,
                status=TaskStatus.CANCELLED,
                cancellation_requested=True,
                updated_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
            )
        )
        current = await self.store.get_task(task_id)
        if current is not None:
            await self.execution.audit.record(
                event_type="TASK_CANCELLED",
                actor=current.subject,
                subject=current.subject,
                action="task.transition",
                resource=str(task_id),
                outcome=current.status.value,
                origin="TASK",
                correlation_id=current.correlation_id,
                task_id=task_id,
            )
