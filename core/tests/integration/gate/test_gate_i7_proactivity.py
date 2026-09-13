"""I7 vertical and adversarial scenarios over a real temporary Operational Store."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
import pytest_asyncio
from sqlalchemy import select

from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.client_boundary.proactivity_http import notification_stream
from sofias_assistant.execution import (
    ExecutionRuntime,
    GrantLifetime,
    TaskRuntime,
    ToolCall,
    ToolSpec,
)
from sofias_assistant.execution.models import ToolSideEffect
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.models import EventRecord, ScheduleRecord
from sofias_assistant.proactivity.events import (
    EventBus,
    FakeEventSource,
    consume_source,
)
from sofias_assistant.proactivity.models import Durability, Event, FakeClock, Recurrence
from sofias_assistant.proactivity.runtime import ProactivityRuntime
from sofias_assistant.runtime.bootstrap import operational_database_url


@pytest_asyncio.fixture
async def env(tmp_path: Path):
    url = operational_database_url(tmp_path / "state.sqlite")
    await asyncio.to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    sessions = create_session_factory(engine)
    execution = ExecutionRuntime(sessions, artifact_root=tmp_path / "artifacts")
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))
    runtime = ProactivityRuntime(sessions, execution.audit, clock)
    tasks = TaskRuntime(execution)
    runtime.bind_tasks(tasks)
    try:
        yield runtime, tasks, execution, clock, engine, url
    finally:
        await runtime.stop()
        await tasks.stop()
        await engine.dispose()


async def reminder(runtime, clock, **kwargs):
    return await runtime.scheduler.create_reminder(
        subject="local-user",
        reminder="Check fixture",
        due_at=clock.now() + timedelta(minutes=1),
        zone="UTC",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_one_shot_audit_duplicate_notification_and_ack(env) -> None:
    runtime, _, execution, clock, _, _ = env
    row = await reminder(runtime, clock)
    assert not await runtime.notifications.pending()
    clock.advance(timedelta(minutes=2))
    await runtime.tick()
    notifications = await runtime.notifications.pending()
    assert len(notifications) == 1
    note = notifications[0]
    assert note.type == "ReminderDue" and note.summary.startswith("Overdue:")
    assert note.action_reference == row.id and note.correlation_id == row.correlation_id
    stored = await runtime.scheduler.get(row.id)
    assert stored.status == "COMPLETED" and stored.next_run_at is None
    async with runtime.bus.sessions() as session:
        event_row = await session.get(EventRecord, note.event_id)
        from sofias_assistant.proactivity.events import to_event

        event = to_event(event_row)
    await runtime.bus.publish(event)
    await runtime.notifications.on_event(event)
    await runtime.tick()
    assert len(await runtime.notifications.pending()) == 1
    trace = await execution.audit.trace(row.correlation_id)
    assert {e.event_type for e in trace} >= {
        "SCHEDULE_CREATED",
        "SCHEDULE_OBSERVED",
        "NOTIFICATION_PRODUCED",
        "EVENT_HANDLER_COMPLETED",
    }
    assert "Check fixture" not in repr(trace)
    assert await runtime.notifications.acknowledge(note.id)
    assert not await runtime.notifications.pending()


@pytest.mark.asyncio
async def test_restart_from_database_and_missed_one_shot(env) -> None:
    runtime, tasks, execution, clock, engine, url = env
    schedule_id = (await reminder(runtime, clock)).id
    await runtime.stop()
    await tasks.stop()
    await engine.dispose()
    clock2 = FakeClock(clock.now() + timedelta(days=7))
    engine2 = create_async_engine(url)
    rebuilt = ProactivityRuntime(
        create_session_factory(engine2), execution.audit, clock2
    )
    try:
        await rebuilt.start()
        await rebuilt.tick()
        recovered = await rebuilt.scheduler.get(schedule_id)
        assert recovered is not None and recovered.status == "COMPLETED"
        assert len(await rebuilt.notifications.pending()) == 1
        await rebuilt.tick()
        assert len(await rebuilt.notifications.pending()) == 1
    finally:
        await rebuilt.stop()
        await engine2.dispose()


@pytest.mark.asyncio
async def test_recurrence_no_catchup_storm_and_competing_workers(env) -> None:
    runtime, _, execution, clock, _, _ = env
    row = await reminder(runtime, clock, recurrence=Recurrence("INTERVAL", 60))
    competitor = ProactivityRuntime(runtime.bus.sessions, execution.audit, clock)
    try:
        clock.advance(timedelta(days=100))
        await asyncio.gather(runtime.scheduler.tick(), competitor.scheduler.tick())
        await asyncio.gather(
            runtime.bus.dispatch_pending(), competitor.bus.dispatch_pending()
        )
        assert len(await runtime.notifications.pending()) == 1
        stored = await runtime.scheduler.get(row.id)
        assert stored.next_run_at > clock.now()
        clock.advance(timedelta(minutes=1))
        await runtime.tick()
        assert len(await runtime.notifications.pending()) == 2
    finally:
        await competitor.stop()


@pytest.mark.asyncio
async def test_cancel_before_and_after_due_commit(env) -> None:
    runtime, _, _, clock, _, _ = env
    first = await reminder(runtime, clock)
    assert await runtime.scheduler.cancel(first.id)
    second = await reminder(runtime, clock)
    clock.advance(timedelta(minutes=1))
    await runtime.scheduler.tick()
    assert await runtime.scheduler.cancel(second.id)
    await runtime.tick()
    assert not await runtime.notifications.pending()


@pytest.mark.asyncio
async def test_invalid_schedule_never_persists(env) -> None:
    runtime, _, _, clock, _, _ = env
    for zone, recurrence in [("no/such/zone", Recurrence()), ("UTC", "invalid")]:
        with pytest.raises(ValueError):
            await runtime.scheduler.create_reminder(
                subject="root",
                reminder="invalid",
                due_at=clock.now(),
                zone=zone,
                recurrence=recurrence,
            )
    async with runtime.bus.sessions() as session:
        assert not list(await session.scalars(select(ScheduleRecord)))


@pytest.mark.asyncio
async def test_subscriber_failure_retry_isolated_and_ephemeral_not_persisted(
    env,
) -> None:
    runtime, _, _, clock, _, _ = env
    seen = []
    failed = []

    async def bad(event):
        failed.append(event.id)
        raise RuntimeError("DO_NOT_LOG_SECRET")

    async def good(event):
        seen.append(event.id)

    runtime.bus.subscribe("external", "bad", bad, retry_safe=True)
    runtime.bus.subscribe("external", "good", good, retry_safe=True)
    ephemeral = Event("external", "fixture", clock.now(), kind="EXTERNAL")
    await consume_source(FakeEventSource((ephemeral,)), runtime.bus)
    async with runtime.bus.sessions() as session:
        assert await session.get(EventRecord, ephemeral.id) is None
    durable = replace(ephemeral, id=uuid4(), durability=Durability.DURABLE)
    await runtime.bus.publish(durable)
    await runtime.bus.dispatch_pending()
    clock.advance(timedelta(seconds=10))
    await runtime.bus.dispatch_pending()
    clock.advance(timedelta(seconds=10))
    await runtime.bus.dispatch_pending()
    assert seen == [ephemeral.id, durable.id]
    assert failed.count(durable.id) == 3
    async with runtime.bus.sessions() as session:
        assert (await session.get(EventRecord, durable.id)).status == "FAILED"
    assert "DO_NOT_LOG_SECRET" not in repr(
        await runtime.bus.audit.trace(durable.correlation_id)
    )


@pytest.mark.asyncio
async def test_event_does_not_authorize_protected_tool(env) -> None:
    runtime, _, execution, clock, _, _ = env
    acted = []
    execution.register_tool(
        ToolSpec(
            name="test.protected",
            version="1",
            description="fixture",
            capability="test.protected",
            handler=lambda _: acted.append(True),
            resource_resolver=lambda _: "fixture",
        )
    )
    outcomes = []

    async def handler(event):
        result = await execution.invoke(
            ToolCall(
                "test.protected",
                {},
                "event-source",
                correlation_id=event.correlation_id,
                causation_id=event.id,
            )
        )
        outcomes.append(result.status)

    runtime.bus.subscribe("trigger", "protected", handler)
    await runtime.bus.publish(
        Event("trigger", "external", clock.now(), payload={"authority": "root"})
    )
    assert outcomes == ["DENY"] and not acted


@pytest.mark.asyncio
async def test_waiting_schedule_restarts_and_rechecks_revoked_grant(env) -> None:
    runtime, tasks, execution, clock, _, _ = env
    acted = []
    execution.register_tool(
        ToolSpec(
            name="test.read",
            version="1",
            description="fixture",
            capability="test.read",
            handler=lambda _: acted.append(True),
            resource_resolver=lambda _: "fixture",
        )
    )
    grant = await execution.create_grant(
        subject="root",
        capability="test.read",
        resource_scope="fixture",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    task = await tasks.create_task(
        objective="wait then inspect",
        subject="root",
        tool_call=ToolCall("test.read", {}, "root"),
        grant_id=grant.id,
        wait_until=clock.now() + timedelta(minutes=1),
    )
    await tasks._tasks[task.id]
    assert (await tasks.get_task(task.id)).status.value == "WAITING_SCHEDULE"
    assert not acted
    await tasks.stop()
    await runtime.stop()
    await execution.revoke_grant(grant.id)
    rebuilt = ProactivityRuntime(runtime.bus.sessions, execution.audit, clock)
    rebuilt_tasks = TaskRuntime(execution)
    rebuilt.bind_tasks(rebuilt_tasks)
    try:
        clock.advance(timedelta(minutes=1))
        await rebuilt.tick()
        await asyncio.gather(*tuple(rebuilt_tasks._tasks.values()))
        recovered_task = await rebuilt_tasks.get_task(task.id)
        assert recovered_task is not None and recovered_task.status.value == "FAILED"
        assert not acted
        await rebuilt.tick()
        assert len(await rebuilt.notifications.pending()) == 1
    finally:
        await rebuilt.stop()
        await rebuilt_tasks.stop()


@pytest.mark.asyncio
async def test_waiting_schedule_duplicate_wakeup_and_task_completion(env) -> None:
    runtime, tasks, execution, clock, _, _ = env
    acted = []
    execution.register_tool(
        ToolSpec(
            name="test.read",
            version="1",
            description="fixture",
            capability="test.read",
            handler=lambda _: acted.append(True),
            resource_resolver=lambda _: "fixture",
        )
    )
    grant = await execution.create_grant(
        subject="root",
        capability="test.read",
        resource_scope="fixture",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    task = await tasks.create_task(
        objective="wake",
        subject="root",
        tool_call=ToolCall("test.read", {}, "root"),
        grant_id=grant.id,
        wait_until=clock.now() + timedelta(seconds=1),
    )
    await tasks._tasks[task.id]
    with pytest.raises(ValueError):
        await tasks.resume_schedule(
            Event("TaskScheduleDue", "external", clock.now(), causation_id=task.id)
        )
    clock.advance(timedelta(seconds=1))
    await runtime.tick()
    await asyncio.gather(*tuple(tasks._tasks.values()))
    await runtime.tick()
    assert (await tasks.get_task(task.id)).status.value == "SUCCEEDED"
    assert acted == [True]
    assert any(n.type == "TaskCompleted" for n in await runtime.notifications.pending())
    assert len(await tasks.store.list_task_attempts(task.id)) == 2


@pytest.mark.asyncio
async def test_authenticated_reminder_disconnected_sync_stream_confirmation(
    env,
) -> None:
    runtime, tasks, execution, clock, _, _ = env
    auth, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(auth)
    app = create_local_http_app(
        auth, sessions, execution=execution, tasks=tasks, proactivity=runtime
    )
    acted = []
    execution.register_tool(
        ToolSpec(
            name="test.write",
            version="1",
            description="fixture",
            capability="test.write",
            side_effect=ToolSideEffect.MUTATING,
            handler=lambda _: acted.append(True),
            resource_resolver=lambda _: "fixture",
        )
    )
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/notifications")).status_code == 401
        bearer = {"Authorization": f"Bearer {credential.reveal()}"}
        opened = await client.post("/api/v1/client-sessions", headers=bearer)
        headers = {**bearer, "X-Sofia-Client-Session-ID": opened.json()["id"]}
        created = await client.post(
            "/api/v1/reminders",
            headers=headers,
            json={
                "reminder": "API fixture",
                "due_at": clock.now().isoformat(),
                "timezone": "America/Sao_Paulo",
            },
        )
        assert created.status_code == 201
        await client.delete("/api/v1/client-session", headers=headers)
        await runtime.tick()
        reopened = await client.post("/api/v1/client-sessions", headers=bearer)
        headers["X-Sofia-Client-Session-ID"] = reopened.json()["id"]
        pending = await client.get("/api/v1/notifications", headers=headers)
        assert len(pending.json()) == 1
        session = sessions.get(UUID(reopened.json()["id"]))
        assert session is not None
        stream = notification_stream(runtime, sessions, session)
        assert json.loads(await anext(stream))["summary"] == "API fixture"
        result = await client.post(
            "/api/v1/tools/test.write/invoke", headers=headers, json={"arguments": {}}
        )
        assert result.json()["status"] == "CONFIRMATION_REQUIRED" and not acted
        await runtime.tick()
        note = json.loads(await anext(stream))
        assert note["type"] == "PermissionRequested"
        await client.post(
            f"/api/v1/notifications/{note['id']}/acknowledge", headers=headers
        )
        assert not acted
        approval = await client.post(
            f"/api/v1/confirmations/{result.json()['confirmation_id']}/approve",
            headers=headers,
            json={},
        )
        assert approval.status_code == 200 and acted == [True]
        sessions.close_all()
        await stream.aclose()


@pytest.mark.asyncio
async def test_degraded_transition_and_delivery_failure_retain_notification(
    env,
) -> None:
    runtime, _, _, _, _, _ = env
    await runtime.notifications.observe_health(
        ComponentHealth("fixture", HealthStatus.HEALTHY)
    )
    await runtime.notifications.observe_health(
        ComponentHealth("fixture", HealthStatus.DEGRADED)
    )
    await runtime.notifications.observe_health(
        ComponentHealth("fixture", HealthStatus.DEGRADED)
    )
    async with runtime.notifications.listen() as queue:
        for _ in range(64):
            queue.put_nowait(uuid4())
        await runtime.bus.dispatch_pending()
        assert await queue.get() is None
    assert len(await runtime.notifications.pending()) == 1
    await runtime.notifications.observe_health(
        ComponentHealth("fixture", HealthStatus.HEALTHY)
    )
    await runtime.notifications.observe_health(
        ComponentHealth("fixture", HealthStatus.DEGRADED)
    )
    await runtime.bus.dispatch_pending()
    assert len(await runtime.notifications.pending()) == 2


@pytest.mark.asyncio
async def test_expired_delivery_claim_recovers_after_recreation(env) -> None:
    runtime, _, execution, clock, _, _ = env
    await reminder(runtime, clock)
    clock.advance(timedelta(minutes=1))
    await runtime.scheduler.tick()
    claimed = await runtime.bus._claim()
    assert claimed is not None
    clock.advance(timedelta(seconds=301))
    rebuilt = ProactivityRuntime(runtime.bus.sessions, execution.audit, clock)
    try:
        await rebuilt.bus.dispatch_pending()
        assert len(await rebuilt.notifications.pending()) == 1
    finally:
        await rebuilt.stop()


@pytest.mark.asyncio
async def test_core_restart_without_client_and_health_integration(
    tmp_path: Path,
) -> None:
    from sofias_assistant.core import SofiaCore
    from tests.integration.core.test_core import (
        FakeSecretStore,
        fake_ownership_factory,
        runtime_config,
    )

    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))

    def core():
        return SofiaCore(
            runtime_config(tmp_path),
            application_version="test",
            secret_store_factory=FakeSecretStore,
            instance_ownership_factory=fake_ownership_factory,
            clock=clock,
        )

    first = core()
    await first.start()
    schedule = await reminder(first.proactivity, clock)
    await first.stop()
    clock.advance(timedelta(days=1))
    second = core()
    await second.start()
    try:
        notes = await second.proactivity.notifications.pending()
        assert len(notes) == 1 and notes[0].action_reference == schedule.id
        assert {h.name for h in second.health.components} >= {
            "scheduler",
            "notifications",
            "event-runtime",
        }
        await second.update_health(ComponentHealth("optional", HealthStatus.DEGRADED))
        await second.update_health(ComponentHealth("optional", HealthStatus.DEGRADED))
        await second.proactivity.tick()
        assert len(await second.proactivity.notifications.pending()) == 2
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_real_http_stream_receives_live_notification(env) -> None:
    from sofias_assistant.client_boundary.server import LocalHttpServer

    runtime, _, _, clock, _, _ = env
    auth, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(auth)
    app = create_local_http_app(auth, sessions, proactivity=runtime)
    server = LocalHttpServer(app, port=0)
    await server.start()
    try:
        async with httpx2.AsyncClient(
            base_url=f"http://127.0.0.1:{server.bound_port}", timeout=5
        ) as client:
            bearer = {"Authorization": f"Bearer {credential.reveal()}"}
            opened = await client.post("/api/v1/client-sessions", headers=bearer)
            headers = {**bearer, "X-Sofia-Client-Session-ID": opened.json()["id"]}
            await reminder(runtime, clock)
            async with client.stream(
                "GET", "/api/v1/notification-stream", headers=headers
            ) as response:
                assert response.status_code == 200
                clock.advance(timedelta(minutes=1))
                await runtime.tick()
                async for line in response.aiter_lines():
                    value = json.loads(line)
                    if value["type"] != "heartbeat":
                        assert value["type"] == "ReminderDue"
                        break
            assert len(await runtime.notifications.pending()) == 1
    finally:
        await runtime.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_transaction_rollback_never_advances_without_due_event(
    env, monkeypatch
) -> None:
    import sofias_assistant.proactivity.scheduler as module

    runtime, _, _, clock, _, _ = env
    row = await reminder(runtime, clock)
    clock.advance(timedelta(minutes=1))
    original = module.event_record

    def crash(event):
        raise RuntimeError("simulated before commit")

    monkeypatch.setattr(module, "event_record", crash)
    with pytest.raises(RuntimeError):
        await runtime.scheduler.tick()
    assert (await runtime.scheduler.get(row.id)).status == "ACTIVE"
    monkeypatch.setattr(module, "event_record", original)
    await runtime.tick()
    assert len(await runtime.notifications.pending()) == 1


@pytest.mark.asyncio
async def test_shutdown_during_dispatch_leaves_recoverable_delivery(env) -> None:
    runtime, _, execution, clock, _, _ = env
    entered = asyncio.Event()

    async def interrupted(event):
        entered.set()
        await asyncio.Event().wait()

    runtime.bus.subscribe("interrupted", "subscriber", interrupted, retry_safe=True)
    event = Event("interrupted", "fixture", clock.now(), durability=Durability.DURABLE)
    await runtime.bus.publish(event)
    dispatch = asyncio.create_task(runtime.bus.dispatch_pending())
    await entered.wait()
    dispatch.cancel()
    await asyncio.gather(dispatch, return_exceptions=True)
    recovered = []

    async def handler(event):
        recovered.append(event.id)

    replacement = EventBus(runtime.bus.sessions, clock, execution.audit)
    replacement.subscribe("interrupted", "subscriber", handler, retry_safe=True)
    await replacement.dispatch_pending()
    assert recovered == [event.id]
    await replacement.stop()


@pytest.mark.asyncio
async def test_cancellation_race_and_cancelled_task_do_not_execute(env) -> None:
    runtime, tasks, execution, clock, _, _ = env
    row = await reminder(runtime, clock)
    clock.advance(timedelta(minutes=1))
    await asyncio.gather(runtime.scheduler.cancel(row.id), runtime.scheduler.tick())
    await runtime.bus.dispatch_pending()
    assert not await runtime.notifications.pending()
    task = await tasks.create_task(
        objective="cancel while waiting",
        subject="root",
        tool_call=ToolCall("unregistered", {}, "root"),
        wait_until=clock.now() + timedelta(seconds=1),
    )
    await tasks._tasks[task.id]
    await tasks.cancel_task(task.id)
    clock.advance(timedelta(seconds=1))
    await runtime.tick()
    assert (await tasks.get_task(task.id)).status.value == "CANCELLED"
    assert not any(
        e.event_type == "TOOL_CALL_REQUESTED"
        for e in await execution.audit.trace(task.correlation_id)
    )


@pytest.mark.asyncio
async def test_pending_notification_survives_service_and_client_restart(env) -> None:
    runtime, _, execution, clock, _, _ = env
    await reminder(runtime, clock)
    clock.advance(timedelta(minutes=1))
    await runtime.tick()
    note_id = (await runtime.notifications.pending())[0].id
    await runtime.stop()
    replacement = ProactivityRuntime(runtime.bus.sessions, execution.audit, clock)
    try:
        assert (await replacement.notifications.pending())[0].id == note_id
        auth, credential = LocalClientAuthenticator.create()
        sessions = ClientSessionRegistry(auth)
        session = sessions.open_session(credential)
        stream = notification_stream(replacement, sessions, session)
        assert json.loads(await anext(stream))["id"] == str(note_id)
        await stream.aclose()
    finally:
        await replacement.stop()


@pytest.mark.asyncio
async def test_uncertain_non_retry_safe_handler_is_not_repeated(env) -> None:
    runtime, _, execution, clock, _, _ = env
    entered = asyncio.Event()
    calls = []

    async def effect(event):
        calls.append(event.id)
        entered.set()
        await asyncio.Event().wait()

    event = Event("uncertain", "fixture", clock.now(), durability=Durability.DURABLE)
    runtime.bus.subscribe("uncertain", "effect", effect)
    await runtime.bus.publish(event)
    dispatch = asyncio.create_task(runtime.bus.dispatch_pending())
    await entered.wait()
    dispatch.cancel()
    await asyncio.gather(dispatch, return_exceptions=True)
    rebuilt = EventBus(runtime.bus.sessions, clock, execution.audit)
    independent = []

    async def observer(event):
        independent.append(event.id)

    rebuilt.subscribe("uncertain", "effect", effect)
    rebuilt.subscribe("uncertain", "observer", observer, retry_safe=True)
    try:
        await rebuilt.dispatch_pending()
        assert calls == independent == [event.id]
        async with runtime.bus.sessions() as session:
            row = await session.get(EventRecord, event.id)
            assert row.status == "FAILED"
    finally:
        await rebuilt.stop()


@pytest.mark.asyncio
async def test_uncertain_scheduled_tool_pauses_on_startup(env) -> None:
    from sofias_assistant.persistence.models import TaskRecord, ToolCallRecord

    runtime, tasks, execution, clock, _, _ = env
    call = ToolCall("unregistered", {}, "root")
    task = await tasks.create_task(
        objective="interrupted continuation",
        subject="root",
        tool_call=call,
        wait_until=clock.now() + timedelta(seconds=1),
    )
    await tasks._tasks[task.id]
    clock.advance(timedelta(seconds=1))
    await runtime.scheduler.tick()
    # Persist the exact uncertain post-claim state, then reconstruct runtime owners.
    async with runtime.bus.sessions() as session:
        stored_task = await session.get(TaskRecord, task.id)
        stored_call = await session.get(ToolCallRecord, call.id)
        stored_task.status, stored_task.claimed_by = "RUNNING", "previous-core"
        stored_call.status = "RUNNING"
        await session.commit()
    await tasks.stop()
    rebuilt = TaskRuntime(execution, scheduler=runtime.scheduler)
    try:
        await rebuilt.recover_scheduled_tasks(startup=True)
        recovered = await rebuilt.get_task(task.id)
        assert recovered is not None and recovered.status.value == "PAUSED"
        assert recovered.error is not None
        assert recovered.error.code == "SCHEDULE_RECONCILIATION_REQUIRED"
        assert not rebuilt._tasks
    finally:
        await rebuilt.stop()


@pytest.mark.asyncio
async def test_scheduler_failure_visible_without_duplicate_health_spam(
    env, monkeypatch
) -> None:
    runtime, _, _, _, _, _ = env

    async def fail():
        raise RuntimeError("private backend failure")

    monkeypatch.setattr(runtime.scheduler, "tick", fail)
    await runtime.tick()
    await runtime.tick()
    health = {item.name: item for item in runtime.health}
    assert health["scheduler"].status is HealthStatus.DEGRADED
    assert health["event-runtime"].status is HealthStatus.HEALTHY
    notes = await runtime.notifications.pending()
    assert len(notes) == 1 and "scheduler" in notes[0].summary
    assert "private backend failure" not in notes[0].summary


@pytest.mark.asyncio
async def test_backward_clock_jump_does_not_repeat_occurrence(env) -> None:
    runtime, _, _, clock, _, _ = env
    await reminder(runtime, clock, recurrence=Recurrence("INTERVAL", 60))
    clock.advance(timedelta(minutes=1))
    await runtime.tick()
    clock.advance(timedelta(days=-1))
    await runtime.tick()
    clock.advance(timedelta(days=1))
    await runtime.tick()
    assert len(await runtime.notifications.pending()) == 1


@pytest.mark.asyncio
async def test_notification_rejects_reused_identity_with_modified_fact(env) -> None:
    from sofias_assistant.proactivity.events import to_event

    runtime, _, _, clock, _, _ = env
    await reminder(runtime, clock)
    clock.advance(timedelta(minutes=1))
    await runtime.tick()
    note = (await runtime.notifications.pending())[0]
    async with runtime.bus.sessions() as session:
        event = to_event(await session.get(EventRecord, note.event_id))
    with pytest.raises(ValueError, match="identity mismatch"):
        await runtime.notifications.on_event(replace(event, payload={"late": "false"}))
    with pytest.raises(ValueError, match="identity"):
        await runtime.bus.publish(replace(event, source="different"))
