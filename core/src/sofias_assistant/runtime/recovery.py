"""Startup Recovery Coordinator: SA-B033 / Gate I12.

Coordinates the existing domain recovery methods (TaskRuntime, Memory
Orchestrator) after a lost runtime session and before Scheduler/Event
processing may resume normal work. It owns no recovery logic of its own —
that stays with the runtimes that already own the durable state — only the
ordering and the audit/health bookends for one recovery pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sofias_assistant.execution.audit import AuditService
from sofias_assistant.execution.task_runtime import RecoveryPassReport, TaskRuntime
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.memory.orchestrator import (
    MemoryOrchestrator,
    MemoryRecoveryReport,
)

_SOURCE_SYSTEM = "sofias-assistant"


@dataclass(frozen=True, slots=True)
class StartupRecoveryReport:
    """Result of one full startup recovery pass, used to project health."""

    tasks: RecoveryPassReport
    memory: MemoryRecoveryReport | None

    @property
    def health(self) -> ComponentHealth:
        if self.tasks.requires_attention_count > 0:
            return ComponentHealth(
                "recovery",
                HealthStatus.DEGRADED,
                f"{self.tasks.requires_attention_count} Task(s) paused pending "
                "reconciliation",
            )
        return ComponentHealth("recovery", HealthStatus.HEALTHY)


class StartupRecoveryCoordinator:
    """Small orchestration seam; never a domain owner of recovery state."""

    def __init__(
        self,
        *,
        task_runtime: TaskRuntime,
        memory_orchestrator: MemoryOrchestrator | None,
        audit: AuditService,
        runtime_session_id: UUID | None,
    ) -> None:
        self._task_runtime = task_runtime
        self._memory_orchestrator = memory_orchestrator
        self._audit = audit
        self._runtime_session_id = runtime_session_id

    async def run(self) -> StartupRecoveryReport:
        pass_id = uuid4()
        await self._audit.record(
            event_type="RECOVERY_PASS_STARTED",
            actor=_SOURCE_SYSTEM,
            subject=_SOURCE_SYSTEM,
            action="recovery.pass",
            resource=str(self._runtime_session_id or pass_id),
            outcome="STARTED",
            origin="RECOVERY",
            correlation_id=pass_id,
        )
        tasks_report = await self._task_runtime.recover_stale_work()
        memory_report = (
            await self._memory_orchestrator.recover_pending_operations()
            if self._memory_orchestrator is not None
            else None
        )
        await self._audit.record(
            event_type="RECOVERY_PASS_COMPLETED",
            actor=_SOURCE_SYSTEM,
            subject=_SOURCE_SYSTEM,
            action="recovery.pass",
            resource=str(self._runtime_session_id or pass_id),
            outcome="COMPLETED",
            origin="RECOVERY",
            correlation_id=pass_id,
            metadata={
                "tasks_reconciled": len(tasks_report.classifications),
                "tasks_requiring_attention": tasks_report.requires_attention_count,
                "memory_auto_replayed": (
                    memory_report.auto_replayed if memory_report is not None else None
                ),
                "memory_evidence_only": (
                    memory_report.evidence_only if memory_report is not None else None
                ),
            },
        )
        return StartupRecoveryReport(tasks=tasks_report, memory=memory_report)
