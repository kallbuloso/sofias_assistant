"""Durable local Task runtime built on the I4 authorized Tool facade."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

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

    def __init__(self, execution: ExecutionRuntime) -> None:
        self.execution = execution
        self.store = execution.store
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._pending_confirmations: dict[UUID, UUID] = {}
        self._lock = asyncio.Lock()
        self._owner = f"core-{uuid4()}"
        self._stopping = False

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
    ) -> Task:
        if self._stopping:
            raise RuntimeError("Task runtime is stopping")
        task = Task(
            objective=objective,
            subject=subject,
            authority=authority or AuthorityContext(subject, tool_call.session_id),
            conversation_id=conversation_id,
            delegation_id=delegation_id,
            execution_strategy=execution_strategy,
        )
        await self.store.save_task(task)
        self._cancel_events[task.id] = asyncio.Event()
        self._tasks[task.id] = asyncio.create_task(
            self._run(task.id, tool_call, grant_id=grant_id)
        )
        return task

    async def get_task(self, task_id: UUID) -> Task | None:
        return await self.store.get_task(task_id)

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
        self, task_id: UUID, tool_call: ToolCall, *, grant_id: UUID | None = None
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
        )
        await self.store.save_task_attempt(attempt)
        cancel_event = self._cancel_events[task_id]
        try:
            if cancel_event.is_set():
                await self._finish_cancelled(task_id)
                return
            result = await self.execution.invoke(tool_call, grant_id=grant_id)
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
