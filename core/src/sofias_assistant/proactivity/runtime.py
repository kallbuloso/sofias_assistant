"""Lifecycle composition and wakeup loop for Core proactivity."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.execution.audit import AuditService
from sofias_assistant.execution.task_runtime import TaskRuntime
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.proactivity.events import EventBus
from sofias_assistant.proactivity.models import Clock, SystemClock
from sofias_assistant.proactivity.notifications import NotificationService
from sofias_assistant.proactivity.scheduler import Scheduler


class ProactivityRuntime:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        audit: AuditService,
        clock: Clock | None = None,
    ) -> None:
        self.bus = EventBus(sessions, clock or SystemClock(), audit)
        self.scheduler = Scheduler(self.bus)
        self.notifications = NotificationService(self.bus)
        self.tasks: TaskRuntime | None = None
        self._worker: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._tick_lock = asyncio.Lock()
        self.health = tuple(
            ComponentHealth(name, HealthStatus.UNKNOWN)
            for name in ("event-runtime", "scheduler", "notifications")
        )

    def bind_tasks(self, tasks: TaskRuntime) -> None:
        self.tasks = tasks
        tasks.scheduler = self.scheduler
        self.bus.subscribe(
            "TaskScheduleDue", "task-wakeup", tasks.resume_schedule, retry_safe=True
        )

    async def start(self) -> None:
        if self._worker is not None or self._stop.is_set():
            raise RuntimeError("Proactivity runtime can only start once")
        if self.tasks is not None:
            await self.tasks.recover_scheduled_tasks(startup=True)
        await self.tick()
        self._worker = asyncio.create_task(self._run())

    async def tick(self) -> None:
        async with self._tick_lock:
            operations = (
                ("scheduler", self.scheduler.tick),
                ("notifications", self.notifications.collect_operational_events),
                ("event-runtime", self.bus.dispatch_pending),
            )
            health = []
            for name, operation in operations:
                try:
                    await operation()
                    component = ComponentHealth(name, HealthStatus.HEALTHY)
                except Exception:
                    component = ComponentHealth(
                        name, HealthStatus.DEGRADED, "Service operation failed"
                    )
                health.append(component)
                try:
                    await self.notifications.observe_health(component)
                except Exception:
                    # Persistence failure is already visible through service health.
                    health[-1] = ComponentHealth(
                        name, HealthStatus.DEGRADED, "Operational state unavailable"
                    )
            by_name = {component.name: component for component in health}
            self.health = tuple(
                by_name[name]
                for name in ("event-runtime", "scheduler", "notifications")
            )
            if self.tasks is not None:
                await self.tasks.recover_scheduled_tasks()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5)
            except TimeoutError:
                try:
                    await self.tick()
                except Exception:
                    self.health = tuple(
                        ComponentHealth(
                            item.name, HealthStatus.DEGRADED, "Proactivity cycle failed"
                        )
                        for item in self.health
                    )

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        await self.bus.stop()
        await self.notifications.stop()
