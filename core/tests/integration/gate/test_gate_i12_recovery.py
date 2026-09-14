"""Gate I12 — Recovery Validated: deterministic crash/restart verticals.

Proves the product invariant: durable interrupted work does not silently
disappear, and does not silently duplicate critical side effects. Crashes
are simulated with direct persistence fixtures (matching the established
pattern in test_gate_i7_proactivity.py) rather than real process kills,
so every window is deterministic. No OpenAI or real Sofias Memory required.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.capabilities.shell import ShellCapability
from sofias_assistant.execution import (
    AgentDefinition,
    AgentExecutionOutcome,
    AgentRuntime,
    AuditService,
    ExecutionRuntime,
    GrantLifetime,
    RecoveryClassification,
    Task,
    TaskAttempt,
    TaskRuntime,
    ToolCall,
    ToolSpec,
)
from sofias_assistant.execution.models import (
    AgentRunStatus,
    AuthorityContext,
    TaskStatus,
    ToolSideEffect,
)
from sofias_assistant.memory.adapter import FakeMemoryProvider
from sofias_assistant.memory.models import (
    CreateMemoryRequest,
    MemoryCandidate,
    MemoryCandidateDecisionStatus,
    MemoryCandidatePersistenceStatus,
    MemoryOriginKind,
    MemoryProvenance,
    MemoryType,
)
from sofias_assistant.memory.orchestrator import MemoryOrchestrator
from sofias_assistant.memory.policy import MemoryPolicy
from sofias_assistant.memory.store import MemoryStore
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.models import (
    AgentRunRecord,
    TaskAttemptRecord,
    TaskRecord,
    ToolCallRecord,
)
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.proactivity.events import EventBus
from sofias_assistant.proactivity.models import FakeClock
from sofias_assistant.proactivity.runtime import ProactivityRuntime
from sofias_assistant.proactivity.scheduler import Scheduler
from sofias_assistant.runtime.bootstrap import operational_database_url


async def _new_execution(
    tmp_path: Path, db_url: str
) -> tuple[ExecutionRuntime, AsyncEngine]:
    engine = create_async_engine(db_url)
    execution = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    execution.register_tool(_read_spec())
    execution.register_tool(_write_spec())
    execution.register_tool(ShellCapability(output_limit_bytes=4096).spec())
    return execution, engine


def _read_spec() -> ToolSpec:
    return ToolSpec(
        name="gate.i12.read",
        version="1",
        description="Gate I12 idempotent read",
        capability="gate.i12.read",
        handler=lambda arguments: {"echo": arguments.get("value", "ok")},
        resource_resolver=lambda arguments: f"fixture:{arguments.get('value', 'ok')}",
        side_effect=ToolSideEffect.NONE,
        idempotent=True,
    )


def _write_spec() -> ToolSpec:
    return ToolSpec(
        name="gate.i12.write",
        version="1",
        description="Gate I12 mutating write",
        capability="gate.i12.write",
        handler=lambda arguments: {"wrote": arguments.get("value", "ok")},
        resource_resolver=lambda arguments: f"fixture:{arguments.get('value', 'ok')}",
        side_effect=ToolSideEffect.MUTATING,
        idempotent=False,
    )


async def _grant(execution: ExecutionRuntime, *, subject: str, capability: str) -> UUID:
    grant = await execution.create_grant(
        subject=subject,
        capability=capability,
        resource_scope="fixture:ok",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    return grant.id


async def _shell_grant(
    execution: ExecutionRuntime, *, subject: str, arguments: dict
) -> UUID:
    spec = execution.registry.resolve("shell.execute")
    assert spec.input_validator is not None
    resource = spec.resource_resolver(spec.input_validator(arguments))
    grant = await execution.create_grant(
        subject=subject,
        capability="shell.execute",
        resource_scope=resource,
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    return grant.id


@pytest.fixture
def db(tmp_path: Path) -> tuple[Path, str]:
    database = tmp_path / "operational.sqlite"
    return tmp_path, operational_database_url(database)


@pytest.mark.asyncio
async def test_window_a_durable_intent_survives_crash_before_execution(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.read")
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(name="gate.i12.read", arguments={"value": "ok"}, subject="root")
        task = await tasks.create_task(
            objective="window A",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        # Durable intent is persisted synchronously inside create_task(),
        # before the in-memory runner has had any chance to run.
        stored_call = await execution.store.get_tool_call(call.id)
        assert stored_call is not None and stored_call[2] == "QUEUED"
        attempts = await execution.store.list_task_attempts(task.id)
        assert len(attempts) == 1 and attempts[0].status is TaskStatus.QUEUED
        # Simulate a crash: the runner never gets a chance to execute.
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.SAFE_TO_RESUME
        )
        await tasks2._tasks[task.id]
        recovered = await tasks2.get_task(task.id)
        assert recovered is not None and recovered.status is TaskStatus.SUCCEEDED
        assert recovered.result == {"echo": "ok"}
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_save_task_with_intent_is_atomic_on_partial_failure(
    db: tuple[Path, str],
) -> None:
    """Gate I12 Finding 1: Task + ToolCall + Attempt commit as one unit."""

    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    try:
        call = ToolCall(name="gate.i12.read", arguments={"value": "ok"}, subject="root")
        # Pre-create a colliding ToolCallRecord so the atomic insert fails
        # partway through the same transaction as the Task/Attempt.
        async with execution.store._session_factory() as session:  # noqa: SLF001
            session.add(
                ToolCallRecord(
                    id=call.id,
                    name=call.name,
                    subject=call.subject,
                    session_id=call.session_id,
                    arguments_json="{}",
                    status="QUEUED",
                    correlation_id=call.correlation_id,
                    causation_id=call.causation_id,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

        task = Task(
            objective="atomic intent",
            subject="root",
            authority=AuthorityContext("root"),
        )
        attempt = TaskAttempt(
            task_id=task.id,
            attempt_number=1,
            tool_call_id=call.id,
            status=TaskStatus.QUEUED,
        )
        with pytest.raises(IntegrityError):
            await execution.store.save_task_with_intent(task, call, attempt)

        async with execution.store._session_factory() as session:  # noqa: SLF001
            assert await session.get(TaskRecord, task.id) is None
            attempts = (
                await session.scalars(
                    select(TaskAttemptRecord).where(
                        TaskAttemptRecord.task_id == task.id
                    )
                )
            ).all()
            assert attempts == []
    finally:
        await engine.dispose()


async def _force_running(
    execution: ExecutionRuntime, task_id: UUID, call_id: UUID, *, owner: str
) -> None:
    """Directly mutate durable state to the exact RUNNING-at-crash shape."""

    async with execution.store._session_factory() as session:  # noqa: SLF001
        task_record = await session.get(TaskRecord, task_id)
        call_record = await session.get(ToolCallRecord, call_id)
        assert task_record is not None and call_record is not None
        task_record.status, task_record.claimed_by = "RUNNING", owner
        call_record.status = "RUNNING"
        attempts = await session.scalars(
            select(TaskAttemptRecord).where(TaskAttemptRecord.task_id == task_id)
        )
        for record in attempts:
            record.status = "RUNNING"
        await session.commit()


@pytest.mark.asyncio
async def test_window_b_idempotent_uncertain_call_retries_to_single_success(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.read")
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(name="gate.i12.read", arguments={"value": "ok"}, subject="root")
        task = await tasks.create_task(
            objective="window B",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await _force_running(execution, task.id, call.id, owner="previous-core")
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.SAFE_TO_RETRY
        )
        await tasks2._tasks[task.id]
        recovered = await tasks2.get_task(task.id)
        assert recovered is not None and recovered.status is TaskStatus.SUCCEEDED
        assert recovered.result == {"echo": "ok"}
        attempts = await execution2.store.list_task_attempts(task.id)
        # Attempt identity is preserved: the interrupted attempt (1) is
        # distinguishable from the retried attempt (2), never overwritten.
        assert len(attempts) == 2
        assert attempts[0].error is not None and attempts[0].error.code == "INTERRUPTED"
        assert attempts[1].status is TaskStatus.SUCCEEDED
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_window_c_mutating_uncertain_call_never_blind_retries(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.write")
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(
            name="gate.i12.write", arguments={"value": "ok"}, subject="root"
        )
        task = await tasks.create_task(
            objective="window C",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await _force_running(execution, task.id, call.id, owner="previous-core")
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.REQUIRES_RECONCILIATION
        )
        assert task.id not in tasks2._tasks
        recovered = await tasks2.get_task(task.id)
        assert recovered is not None and recovered.status is TaskStatus.PAUSED
        assert recovered.error is not None and recovered.error.code == (
            "RECOVERY_REQUIRED"
        )
        stored_call = await execution2.store.get_tool_call(call.id)
        assert stored_call is not None and stored_call[2] == "RECOVERY_REQUIRED"
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_window_running_toolcall_already_completed_reconciles_from_evidence(
    db: tuple[Path, str],
) -> None:
    """A completed ToolCall record is trusted over a stale RUNNING Task/Attempt."""

    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.read")
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(name="gate.i12.read", arguments={"value": "ok"}, subject="root")
        task = await tasks.create_task(
            objective="reconcile from evidence",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await tasks._tasks[task.id]
        # The ToolCall genuinely completed, but the Task/Attempt update that
        # should have followed never got persisted before the crash.
        async with execution.store._session_factory() as session:  # noqa: SLF001
            task_record = await session.get(TaskRecord, task.id)
            assert task_record is not None
            task_record.status, task_record.claimed_by = "RUNNING", "previous-core"
            attempts = await session.scalars(
                select(TaskAttemptRecord).where(TaskAttemptRecord.task_id == task.id)
            )
            for record in attempts:
                record.status, record.finished_at = "RUNNING", None
            await session.commit()
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.SAFE_TO_RESUME
        )
        assert task.id not in tasks2._tasks
        recovered = await tasks2.get_task(task.id)
        assert recovered is not None and recovered.status is TaskStatus.SUCCEEDED
        assert recovered.result == {"echo": "ok"}
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_window_d_subprocess_pid_is_captured_and_never_adopted_or_killed(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    shell_arguments = {
        "executable": sys.executable,
        "argv": ["-c", "print('ok')"],
        "cwd": str(tmp_path),
    }
    grant_id = await _shell_grant(execution, subject="root", arguments=shell_arguments)
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(name="shell.execute", arguments=shell_arguments, subject="root")
        task = await tasks.create_task(
            objective="subprocess evidence",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await tasks._tasks[task.id]
        attempts = await execution.store.list_task_attempts(task.id)
        assert len(attempts) == 1 and attempts[0].process_id is not None
        pid_evidence = attempts[0].process_id

        # Now simulate a *different* run where the crash happens while the
        # ToolCall is still RUNNING: PID evidence exists but outcome is
        # uncertain (shell.execute is MUTATING/non-idempotent).
        call2 = ToolCall(
            name="shell.execute", arguments=shell_arguments, subject="root"
        )
        task2 = await tasks.create_task(
            objective="interrupted subprocess",
            subject="root",
            tool_call=call2,
            grant_id=grant_id,
        )
        await _force_running(execution, task2.id, call2.id, owner="previous-core")
        async with execution.store._session_factory() as session:  # noqa: SLF001
            record = (
                await session.scalars(
                    select(TaskAttemptRecord).where(
                        TaskAttemptRecord.task_id == task2.id
                    )
                )
            ).one()
            record.process_id = pid_evidence
            await session.commit()
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task2.id] is (
            RecoveryClassification.REQUIRES_RECONCILIATION
        )
        recovered = await tasks2.get_task(task2.id)
        assert recovered is not None and recovered.status is TaskStatus.PAUSED
        # PID evidence is preserved untouched; never used to adopt or kill.
        attempts = await execution2.store.list_task_attempts(task2.id)
        assert attempts[-1].process_id == pid_evidence
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_window_e_stale_agent_run_is_interrupted_not_resumed(
    db: tuple[Path, str],
) -> None:
    """Gate I12 Finding 3: reconcile the real AgentRuntime.run() lifecycle.

    AgentRuntime.run() marks the AgentRun RUNNING durably but never
    promotes the parent Task; the Task stays QUEUED for the entire
    execution. Recovery must reconcile from that real shape, not from a
    Task.RUNNING state AgentRuntime never actually produces.
    """

    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    tasks = TaskRuntime(execution)
    agents = AgentRuntime(execution)
    try:

        async def _runner(context) -> AgentExecutionOutcome:
            raise AssertionError("stale AgentRun must never resume hidden reasoning")

        definition = AgentDefinition(
            name="gate-i12-agent",
            version="1",
            description="Gate I12 recovery agent",
            required_capabilities=frozenset(),
            allowed_tools=frozenset({"gate.i12.read"}),
        )
        await agents.register_durable(definition, _runner)

        task = await tasks.create_agent_task(
            objective="window E",
            subject="root",
            authority=AuthorityContext("root"),
        )
        assert task.status is TaskStatus.QUEUED
        run = await agents.create_agent_run(
            root_authority=agents.root_authority,
            task=task,
            definition=definition,
            delegated_context={"objective": task.objective},
            authority=AuthorityContext("root"),
        )
        # Only the AgentRun is forced RUNNING, matching the real lifecycle
        # exactly; the Task record is left untouched (still QUEUED).
        async with execution.store._session_factory() as session:  # noqa: SLF001
            run_record = await session.get(AgentRunRecord, run.id)
            assert run_record is not None
            run_record.status = "RUNNING"
            await session.commit()
        durable_task = await tasks.get_task(task.id)
        assert durable_task is not None and durable_task.status is TaskStatus.QUEUED
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.REQUIRES_USER_DECISION
        )
        recovered_task = await tasks2.get_task(task.id)
        assert recovered_task is not None and recovered_task.status is TaskStatus.PAUSED
        runs = await execution2.store.list_agent_runs_by_task(task.id)
        assert runs[-1].status is AgentRunStatus.FAILED
        assert runs[-1].result is not None
        assert runs[-1].result.get("recovery_required") is True
        # No hidden reasoning resume, no duplicate runner spawned.
        assert task.id not in tasks2._tasks  # noqa: SLF001
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_window_f_waiting_confirmation_survives_without_duplication(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(
            name="gate.i12.write", arguments={"value": "ok"}, subject="root"
        )
        task = await tasks.create_task(
            objective="window F", subject="root", tool_call=call
        )
        await tasks._tasks[task.id]
        waiting = await tasks.get_task(task.id)
        assert waiting is not None and waiting.status is TaskStatus.WAITING_CONFIRMATION
        confirmation_id = tasks.pending_confirmation(task.id)
        assert confirmation_id is not None
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.SAFE_TO_RESUME
        )
        recovered = await tasks2.get_task(task.id)
        assert (
            recovered is not None
            and recovered.status is TaskStatus.WAITING_CONFIRMATION
        )
        assert tasks2.pending_confirmation(task.id) == confirmation_id
        approved = await tasks2.approve_confirmation(task.id, confirmation_id)
        assert approved.status is TaskStatus.SUCCEEDED
        assert approved.result == {"wrote": "ok"}
    finally:
        await tasks2.stop()
        await engine2.dispose()


async def _force_cancelling(
    execution: ExecutionRuntime, task_id: UUID, call_id: UUID, *, owner: str
) -> None:
    """Directly mutate durable state to a CANCELLING Task + RUNNING ToolCall."""

    async with execution.store._session_factory() as session:  # noqa: SLF001
        task_record = await session.get(TaskRecord, task_id)
        call_record = await session.get(ToolCallRecord, call_id)
        assert task_record is not None and call_record is not None
        task_record.status, task_record.claimed_by = "CANCELLING", owner
        task_record.cancellation_requested = True
        call_record.status = "RUNNING"
        attempts = await session.scalars(
            select(TaskAttemptRecord).where(TaskAttemptRecord.task_id == task_id)
        )
        for record in attempts:
            record.status = "RUNNING"
        await session.commit()


@pytest.mark.asyncio
async def test_finding4_cancelling_read_only_reconciles_stale_toolcall(
    db: tuple[Path, str],
) -> None:
    """Gate I12 Finding 4a: CANCELLING never leaves a stale RUNNING ToolCall.

    A read-only/idempotent ToolCall left RUNNING when a Task is CANCELLING
    is reconciled to a terminal, fail-closed outcome — never SUCCEEDED, and
    never left looking like ordinary in-flight work.
    """

    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.read")
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(name="gate.i12.read", arguments={"value": "ok"}, subject="root")
        task = await tasks.create_task(
            objective="cancelling read-only",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await _force_cancelling(execution, task.id, call.id, owner="previous-core")
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.SAFE_TO_RESUME
        )
        assert task.id not in tasks2._tasks  # no execution occurs
        recovered = await tasks2.get_task(task.id)
        assert recovered is not None and recovered.status is TaskStatus.CANCELLED
        stored_call = await execution2.store.get_tool_call(call.id)
        assert stored_call is not None
        assert stored_call[2] == "FAILED"
        assert stored_call[1] is not None and stored_call[1].error is not None
        assert stored_call[1].error.code == "CANCELLED_DURING_RECOVERY"
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_finding4_cancelling_mutating_never_retries(
    db: tuple[Path, str],
) -> None:
    """Gate I12 Finding 4b: a mutating uncertain ToolCall never blind-retries,
    even when the Task was already being cancelled."""

    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.write")
    tasks = TaskRuntime(execution)
    try:
        call = ToolCall(
            name="gate.i12.write", arguments={"value": "ok"}, subject="root"
        )
        task = await tasks.create_task(
            objective="cancelling mutating",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await _force_cancelling(execution, task.id, call.id, owner="previous-core")
        await tasks.stop()
    finally:
        await engine.dispose()

    execution2, engine2 = await _new_execution(tmp_path, url)
    tasks2 = TaskRuntime(execution2)
    try:
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.REQUIRES_RECONCILIATION
        )
        assert task.id not in tasks2._tasks  # no retry
        recovered = await tasks2.get_task(task.id)
        assert recovered is not None and recovered.status is TaskStatus.PAUSED
        assert recovered.error is not None and recovered.error.code == (
            "RECOVERY_REQUIRED"
        )
        stored_call = await execution2.store.get_tool_call(call.id)
        assert stored_call is not None and stored_call[2] == "RECOVERY_REQUIRED"
    finally:
        await tasks2.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_window_g_waiting_schedule_is_left_to_specialized_recovery(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))
    bus = EventBus(execution.store._session_factory, clock, execution.audit)  # noqa: SLF001
    scheduler = Scheduler(bus)
    tasks = TaskRuntime(execution, scheduler=scheduler)
    try:
        call = ToolCall(name="gate.i12.read", arguments={"value": "ok"}, subject="root")
        task = await tasks.create_task(
            objective="window G",
            subject="root",
            tool_call=call,
            wait_until=clock.now(),
        )
        await tasks._tasks[task.id]
        waiting = await tasks.get_task(task.id)
        assert waiting is not None and waiting.status is TaskStatus.WAITING_SCHEDULE

        report = await tasks.recover_stale_work()
        assert task.id not in dict(report.classifications)
        untouched = await tasks.get_task(task.id)
        assert untouched is not None and untouched.status is TaskStatus.WAITING_SCHEDULE
    finally:
        await tasks.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_window_h_memory_replay_converges_without_duplicate_resource(
    db: tuple[Path, str],
) -> None:
    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    await asyncio.to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    sessions = create_session_factory(engine)
    provider = FakeMemoryProvider()
    store = MemoryStore(sessions)
    orchestrator = MemoryOrchestrator(
        store=store,
        provider=provider,
        policy=MemoryPolicy(),
        extractor=_PassthroughExtractor(),
        audit=AuditService(sessions),
        uow_factory=lambda: SqlAlchemyUnitOfWork(sessions),
    )
    try:
        candidate_id = uuid4()
        candidate_turn_id = uuid4()
        idempotency_key = f"sofias-assistant:memory:create:{candidate_id}"
        request = CreateMemoryRequest(
            memory_type=MemoryType.PROFILE,
            scope="global",
            content="Gate I12: prefers dark mode.",
            provenance=MemoryProvenance(
                origin_kind=MemoryOriginKind.USER_ASSERTED, turn_uuid=candidate_turn_id
            ),
        )
        # Remote commit succeeded before the crash...
        remote_item = await provider.create_memory(
            request, idempotency_key=idempotency_key
        )
        # ...but the local candidate never observed completion.
        now = datetime.now(UTC)
        await store.save_candidate(
            MemoryCandidate(
                id=candidate_id,
                memory_type=MemoryType.PROFILE,
                scope="global",
                origin_kind=MemoryOriginKind.USER_ASSERTED,
                decision_status=MemoryCandidateDecisionStatus.APPROVED,
                persistence_status=MemoryCandidatePersistenceStatus.PENDING,
                created_at=now,
                updated_at=now,
                decided_at=now,
                turn_id=candidate_turn_id,
                cloud_context_eligible=True,
                content=request.content,
            )
        )

        report = await orchestrator.recover_pending_operations()
        assert report.auto_replayed == 1
        assert report.evidence_only == 0

        recovered = await store.get_candidate(candidate_id)
        assert recovered is not None
        assert (
            recovered.persistence_status is MemoryCandidatePersistenceStatus.SUCCEEDED
        )
        assert recovered.memory_id == remote_item.memory_id
        # No duplicate resource was created on the provider side.
        recall = await provider.recall_memories(_recall_request("dark mode"))
        matches = [
            item
            for item in recall.items
            if item.memory.content == "Gate I12: prefers dark mode."
        ]
        assert len(matches) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recovery_pause_produces_durable_notification(
    db: tuple[Path, str],
) -> None:
    """A Task paused for reconciliation surfaces durable attention evidence."""

    tmp_path, url = db
    await asyncio.to_thread(upgrade_to_head, url)
    execution, engine = await _new_execution(tmp_path, url)
    grant_id = await _grant(execution, subject="root", capability="gate.i12.write")
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))
    proactivity = ProactivityRuntime(
        execution.store._session_factory,
        execution.audit,
        clock,  # noqa: SLF001
    )
    tasks = TaskRuntime(execution)
    tasks2: TaskRuntime | None = None
    proactivity.bind_tasks(tasks)
    try:
        call = ToolCall(
            name="gate.i12.write", arguments={"value": "ok"}, subject="root"
        )
        task = await tasks.create_task(
            objective="notification evidence",
            subject="root",
            tool_call=call,
            grant_id=grant_id,
        )
        await _force_running(execution, task.id, call.id, owner="previous-core")
        # Simulate the crash from this runtime's own point of view: the
        # in-memory runner tracking must be gone before recovery reconciles
        # the durable state, exactly as a fresh process would find it.
        await tasks.stop()

        tasks2 = TaskRuntime(execution)
        report = await tasks2.recover_stale_work()
        assert dict(report.classifications)[task.id] is (
            RecoveryClassification.REQUIRES_RECONCILIATION
        )

        await proactivity.tick()
        pending = await proactivity.notifications.pending()
        matches = [note for note in pending if note.type == "TaskRecoveryRequired"]
        assert len(matches) == 1
        assert matches[0].action_reference == task.id
        assert "RECOVERY_REQUIRED" in matches[0].summary

        # Idempotent: a second tick never produces a duplicate notification.
        await proactivity.tick()
        pending_again = await proactivity.notifications.pending()
        assert len([n for n in pending_again if n.type == "TaskRecoveryRequired"]) == 1
    finally:
        await proactivity.stop()
        await tasks.stop()
        if tasks2 is not None:
            await tasks2.stop()
        await engine.dispose()


def _recall_request(query: str):
    from sofias_assistant.memory.models import RecallRequest

    return RecallRequest(query=query, scopes=("global",))


class _PassthroughExtractor:
    async def extract(self, *, text: str) -> str:
        return text
