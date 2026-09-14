"""Durable local Task runtime built on the I4 authorized Tool facade."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
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
    AgentRunStatus,
    AuthorityContext,
    ConfirmationStatus,
    RecoveryClassification,
    Task,
    TaskAttempt,
    TaskExecutionStrategy,
    TaskStatus,
    ToolCall,
    ToolError,
    ToolExecutionMode,
    ToolResult,
    ToolSideEffect,
)
from sofias_assistant.execution.runtime import ExecutionRuntime

_RECONCILABLE_STATUSES = (
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_CONFIRMATION,
    TaskStatus.CANCELLING,
)
_RECOVERY_REQUIRED_ERROR_CODE = "RECOVERY_REQUIRED"


@dataclass(frozen=True, slots=True)
class RecoveryPassReport:
    """Small, auditable summary of one startup Task recovery pass."""

    classifications: tuple[tuple[UUID, RecoveryClassification], ...] = ()

    @property
    def requires_attention_count(self) -> int:
        return sum(
            1
            for _, classification in self.classifications
            if classification
            in (
                RecoveryClassification.REQUIRES_RECONCILIATION,
                RecoveryClassification.REQUIRES_USER_DECISION,
            )
        )


class TaskRuntime:
    """Single-Core queue/claim owner; no distributed worker is implied."""

    def __init__(
        self,
        execution: ExecutionRuntime,
        *,
        scheduler: Scheduler | None = None,
        owner: str | None = None,
    ) -> None:
        self.execution = execution
        self.store = execution.store
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._pending_confirmations: dict[UUID, UUID] = {}
        self._lock = asyncio.Lock()
        self._owner = owner or f"core-{uuid4()}"
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
        # Durable execution intent before any runner is scheduled (Gap A,
        # ADR-0010 §83): a crash between here and the first ToolCall
        # persistence inside invoke() must still leave enough evidence to
        # reconstruct what was intended, not just that a Task existed.
        await self.store.save_tool_call(tool_call, status="QUEUED")
        await self.store.save_task_attempt(
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                tool_call_id=tool_call.id,
                execution_mode=self._resolve_execution_mode(tool_call.name),
                grant_id=grant_id,
                status=TaskStatus.QUEUED,
                correlation_id=task.correlation_id,
                causation_id=task.id,
            )
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

    def _resolve_execution_mode(self, tool_name: str) -> ToolExecutionMode | None:
        try:
            return self.execution.registry.resolve(tool_name).execution_mode
        except KeyError:
            return None

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
        execution_mode = self._resolve_execution_mode(tool_call.name)
        pre_created = (
            attempts[-1]
            if attempts
            and attempts[-1].tool_call_id == tool_call.id
            and attempts[-1].status is TaskStatus.QUEUED
            else None
        )
        if pre_created is not None:
            # Reuse the durable intent persisted by create_task() instead of
            # appending a second attempt for the same first execution.
            attempt = replace(
                pre_created,
                execution_mode=execution_mode,
                grant_id=grant_id if grant_id is not None else pre_created.grant_id,
                status=TaskStatus.RUNNING,
                started_at=datetime.now(UTC),
                correlation_id=claimed.correlation_id,
                causation_id=claimed.id,
            )
            await self.store.update_task_attempt(attempt)
        else:
            attempt = TaskAttempt(
                task_id=task_id,
                attempt_number=len(attempts) + 1,
                tool_call_id=tool_call.id,
                execution_mode=execution_mode,
                grant_id=grant_id,
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

            async def _persist_process_id(pid: int) -> None:
                nonlocal attempt
                attempt = replace(attempt, process_id=pid)
                await self.store.update_task_attempt(attempt)

            result = await self.execution.invoke(
                tool_call,
                grant_id=grant_id,
                origin="TASK",
                task_id=task_id,
                on_process_started=_persist_process_id,
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

    async def recover_stale_work(self) -> RecoveryPassReport:
        """Reconcile stale QUEUED/RUNNING/WAITING_CONFIRMATION/CANCELLING Tasks.

        WAITING_SCHEDULE remains owned by recover_scheduled_tasks(); any Task
        tied to a TASK_WAKEUP schedule is skipped here so the two recovery
        paths never race on the same Task (Slice 08 §16.5/§24).
        """

        if self._stopping:
            return RecoveryPassReport()
        scheduled_task_ids: set[UUID] = set()
        if self.scheduler is not None:
            async with self.scheduler.sessions() as session:
                rows = await session.execute(
                    select(ScheduleRecord.task_id).where(
                        ScheduleRecord.kind == "TASK_WAKEUP",
                        ScheduleRecord.task_id.is_not(None),
                    )
                )
                scheduled_task_ids = {row[0] for row in rows}
        tasks = await self.store.list_tasks_by_status(_RECONCILABLE_STATUSES)
        classifications: list[tuple[UUID, RecoveryClassification]] = []
        for task in tasks:
            if task.id in scheduled_task_ids or task.id in self._tasks:
                continue
            classification = await self._reconcile_task(task)
            classifications.append((task.id, classification))
        return RecoveryPassReport(tuple(classifications))

    async def _reconcile_task(self, task: Task) -> RecoveryClassification:
        if task.status is TaskStatus.QUEUED:
            return await self._reconcile_queued(task)
        if task.status is TaskStatus.RUNNING:
            return await self._reconcile_running(task)
        if task.status is TaskStatus.WAITING_CONFIRMATION:
            return await self._reconcile_waiting_confirmation(task)
        return await self._reconcile_cancelling(task)

    async def _reconcile_queued(self, task: Task) -> RecoveryClassification:
        if task.execution_strategy is not TaskExecutionStrategy.DIRECT_TOOL:
            # AGENT/WORKFLOW Tasks have no in-process runner to restart here;
            # they remain QUEUED for their normal external driver.
            await self._audit_recovery(
                task,
                event_type="RECOVERY_TASK_CLASSIFIED",
                outcome=RecoveryClassification.SAFE_TO_RESUME.value,
                metadata={"reason": "no in-process runner required"},
            )
            return RecoveryClassification.SAFE_TO_RESUME
        attempt = await self._latest_attempt(task.id)
        if attempt is None or attempt.tool_call_id is None:
            return await self._pause_for_reconciliation(
                task, reason="no durable execution intent found for a QUEUED Task"
            )
        stored_call = await self.store.get_tool_call(attempt.tool_call_id)
        if stored_call is None:
            return await self._pause_for_reconciliation(
                task, reason="durable ToolCall intent is missing"
            )
        call, _, call_status = stored_call
        if call_status != "QUEUED":
            return await self._pause_for_reconciliation(
                task,
                reason=f"unexpected ToolCall status {call_status!r} for a QUEUED Task",
            )
        await self._requeue(
            task,
            call,
            grant_id=attempt.grant_id,
            classification=RecoveryClassification.SAFE_TO_RESUME,
            reason="durable intent reconstructed; safe to claim normally",
        )
        return RecoveryClassification.SAFE_TO_RESUME

    async def _reconcile_running(self, task: Task) -> RecoveryClassification:
        if task.execution_strategy is TaskExecutionStrategy.AGENT:
            return await self._reconcile_running_agent(task)
        attempt = await self._latest_attempt(task.id)
        if attempt is None or attempt.tool_call_id is None:
            return await self._pause_for_reconciliation(
                task,
                reason="no durable Attempt/ToolCall evidence for a RUNNING Task",
            )
        stored_call = await self.store.get_tool_call(attempt.tool_call_id)
        if stored_call is None:
            return await self._pause_for_reconciliation(
                task, reason="durable ToolCall evidence is missing"
            )
        call, result, call_status = stored_call
        if call_status in ("SUCCEEDED", "FAILED", "DENIED"):
            # The ToolCall actually finished before the runtime was lost;
            # use the durable result instead of guessing (ADR-0010 §24).
            await self._finalize_from_evidence(task, attempt, call_status, result)
            return RecoveryClassification.SAFE_TO_RESUME
        if call_status == "WAITING_CONFIRMATION":
            await self._transition_to_waiting_confirmation(task, call)
            return RecoveryClassification.SAFE_TO_RESUME
        if call_status != "RUNNING":
            return await self._pause_for_reconciliation(
                task,
                reason=(
                    f"incoherent ToolCall status {call_status!r} for a RUNNING Task"
                ),
            )
        try:
            spec = self.execution.registry.resolve(call.name)
        except KeyError:
            return await self._pause_for_reconciliation(
                task,
                reason="Tool is no longer registered; outcome cannot be classified",
                tool_call=call,
            )
        retry_safe = spec.idempotent and spec.side_effect is ToolSideEffect.NONE
        await self.execution.audit.record(
            event_type="RECOVERY_TOOLCALL_UNCERTAIN",
            actor="sofias-assistant",
            subject=task.subject,
            action=call.name,
            resource=str(call.id),
            outcome="UNCERTAIN",
            origin="RECOVERY",
            correlation_id=task.correlation_id,
            causation_id=task.id,
            task_id=task.id,
            attempt_id=attempt.id,
            tool_call_id=call.id,
            metadata={"retry_safe": retry_safe},
        )
        if retry_safe:
            await self.store.update_task_attempt(
                replace(
                    attempt,
                    status=TaskStatus.FAILED,
                    error=ToolError(
                        "INTERRUPTED", "Runtime session was lost before completion"
                    ),
                    finished_at=datetime.now(UTC),
                )
            )
            await self.store.save_tool_call(call, status="QUEUED")
            await self._requeue(
                task,
                call,
                grant_id=attempt.grant_id,
                classification=RecoveryClassification.SAFE_TO_RETRY,
                reason="read-only/idempotent outcome unknown; safe to retry",
            )
            return RecoveryClassification.SAFE_TO_RETRY
        return await self._pause_for_reconciliation(
            task,
            reason="mutating/non-idempotent ToolCall outcome is unknown",
            tool_call=call,
        )

    async def _reconcile_running_agent(self, task: Task) -> RecoveryClassification:
        runs = await self.store.list_agent_runs_by_task(task.id)
        latest_run = runs[-1] if runs else None
        if latest_run is not None and latest_run.status is AgentRunStatus.RUNNING:
            interrupted = replace(
                latest_run,
                status=AgentRunStatus.FAILED,
                result={"error": "runtime_interruption", "recovery_required": True},
                finished_at=datetime.now(UTC),
            )
            await self.store.update_agent_run(interrupted)
            await self.execution.audit.record(
                event_type="RECOVERY_AGENT_INTERRUPTED",
                actor="sofias-assistant",
                subject=task.subject,
                action="agent.run.recover",
                resource=str(latest_run.id),
                outcome="INTERRUPTED",
                origin="RECOVERY",
                correlation_id=task.correlation_id,
                causation_id=task.id,
                task_id=task.id,
                agent_run_id=latest_run.id,
            )
        return await self._pause_for_reconciliation(
            task,
            reason="stale AgentRun requires an explicit replan/resume decision",
            classification=RecoveryClassification.REQUIRES_USER_DECISION,
        )

    async def _reconcile_waiting_confirmation(
        self, task: Task
    ) -> RecoveryClassification:
        attempt = await self._latest_attempt(task.id)
        confirmation_id = (
            await self.store.get_tool_call_confirmation(attempt.tool_call_id)
            if attempt is not None and attempt.tool_call_id is not None
            else None
        )
        if confirmation_id is None:
            return await self._pause_for_reconciliation(
                task,
                reason="no confirmation reference found for a WAITING_CONFIRMATION Task",
            )
        confirmation = await self.execution.store.get_confirmation(confirmation_id)
        if confirmation is None:
            return await self._pause_for_reconciliation(
                task, reason="confirmation request is missing"
            )
        if confirmation.status is ConfirmationStatus.PENDING:
            self._pending_confirmations[task.id] = confirmation_id
            await self._audit_recovery(
                task,
                event_type="RECOVERY_TASK_CLASSIFIED",
                outcome=RecoveryClassification.SAFE_TO_RESUME.value,
                metadata={"reason": "confirmation still pending"},
            )
            return RecoveryClassification.SAFE_TO_RESUME
        return await self._pause_for_reconciliation(
            task,
            reason="confirmation was resolved but the Task never observed it",
        )

    async def _reconcile_cancelling(self, task: Task) -> RecoveryClassification:
        attempt = await self._latest_attempt(task.id)
        if attempt is not None and attempt.tool_call_id is not None:
            stored_call = await self.store.get_tool_call(attempt.tool_call_id)
            if stored_call is not None and stored_call[2] == "RUNNING":
                call = stored_call[0]
                try:
                    spec = self.execution.registry.resolve(call.name)
                    retry_safe = (
                        spec.idempotent and spec.side_effect is ToolSideEffect.NONE
                    )
                except KeyError:
                    retry_safe = False
                if not retry_safe:
                    return await self._pause_for_reconciliation(
                        task,
                        reason=(
                            "cancellation requested but ToolCall outcome is uncertain"
                        ),
                        tool_call=call,
                    )
        await self._finish_cancelled(task.id)
        await self._audit_recovery(
            task,
            event_type="RECOVERY_TASK_CLASSIFIED",
            outcome=RecoveryClassification.SAFE_TO_RESUME.value,
            metadata={"reason": "cancellation completed safely"},
        )
        return RecoveryClassification.SAFE_TO_RESUME

    async def _latest_attempt(self, task_id: UUID) -> TaskAttempt | None:
        attempts = await self.store.list_task_attempts(task_id)
        return attempts[-1] if attempts else None

    async def _requeue(
        self,
        task: Task,
        call: ToolCall,
        *,
        grant_id: UUID | None,
        classification: RecoveryClassification,
        reason: str,
    ) -> None:
        updated = replace(
            task,
            status=TaskStatus.QUEUED,
            claimed_by=None,
            updated_at=datetime.now(UTC),
        )
        await self.store.update_task(updated)
        await self._audit_recovery(
            task,
            event_type="RECOVERY_TASK_REQUEUED",
            outcome=classification.value,
            metadata={"reason": reason},
        )
        self._cancel_events[task.id] = asyncio.Event()
        self._tasks[task.id] = asyncio.create_task(
            self._run(task.id, call, grant_id=grant_id)
        )

    async def _pause_for_reconciliation(
        self,
        task: Task,
        *,
        reason: str,
        classification: RecoveryClassification = (
            RecoveryClassification.REQUIRES_RECONCILIATION
        ),
        tool_call: ToolCall | None = None,
    ) -> RecoveryClassification:
        updated = replace(
            task,
            status=TaskStatus.PAUSED,
            claimed_by=None,
            error=ToolError(_RECOVERY_REQUIRED_ERROR_CODE, reason[:500]),
            updated_at=datetime.now(UTC),
        )
        await self.store.update_task(updated)
        if tool_call is not None:
            await self.store.save_tool_call(tool_call, status="RECOVERY_REQUIRED")
        await self._audit_recovery(
            task,
            event_type="RECOVERY_TASK_PAUSED",
            outcome=classification.value,
            metadata={"reason": reason},
        )
        return classification

    async def _finalize_from_evidence(
        self,
        task: Task,
        attempt: TaskAttempt,
        call_status: str,
        result: ToolResult | None,
    ) -> None:
        final_status = (
            TaskStatus.SUCCEEDED if call_status == "SUCCEEDED" else TaskStatus.FAILED
        )
        now = datetime.now(UTC)
        await self.store.update_task(
            replace(
                task,
                status=final_status,
                claimed_by=None,
                result=result.value if result is not None else None,
                error=result.error if result is not None else None,
                updated_at=now,
                finished_at=now,
            )
        )
        await self.store.update_task_attempt(
            replace(
                attempt,
                status=final_status,
                result=result.value if result is not None else None,
                error=result.error if result is not None else None,
                finished_at=now,
            )
        )
        await self._audit_recovery(
            task,
            event_type="RECOVERY_TASK_CLASSIFIED",
            outcome=RecoveryClassification.SAFE_TO_RESUME.value,
            metadata={
                "reason": "durable ToolCall result reconciled Task outcome",
                "final_status": final_status.value,
            },
        )

    async def _transition_to_waiting_confirmation(
        self, task: Task, call: ToolCall
    ) -> None:
        await self.store.update_task(
            replace(
                task,
                status=TaskStatus.WAITING_CONFIRMATION,
                claimed_by=None,
                updated_at=datetime.now(UTC),
            )
        )
        confirmation_id = await self.store.get_tool_call_confirmation(call.id)
        if confirmation_id is not None:
            self._pending_confirmations[task.id] = confirmation_id
        await self._audit_recovery(
            task,
            event_type="RECOVERY_TASK_CLASSIFIED",
            outcome=RecoveryClassification.SAFE_TO_RESUME.value,
            metadata={
                "reason": "ToolCall was already WAITING_CONFIRMATION at crash time"
            },
        )

    async def _audit_recovery(
        self,
        task: Task,
        *,
        event_type: str,
        outcome: str,
        metadata: dict[str, object],
    ) -> None:
        await self.execution.audit.record(
            event_type=event_type,
            actor="sofias-assistant",
            subject=task.subject,
            action="task.recover",
            resource=str(task.id),
            outcome=outcome,
            origin="RECOVERY",
            correlation_id=task.correlation_id,
            causation_id=task.id,
            task_id=task.id,
            metadata=metadata,
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
