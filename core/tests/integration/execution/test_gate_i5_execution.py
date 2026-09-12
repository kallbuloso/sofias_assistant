"""Deterministic Gate I5 execution runtime evidence."""

import asyncio
import sys
from asyncio import to_thread
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from sofias_assistant.execution import (
    AgentDefinition,
    AgentRuntime,
    AuthorityContext,
    ExecutionRuntime,
    GrantLifetime,
    Task,
    TaskRuntime,
    TaskStatus,
    ToolCall,
    ToolExecutionMode,
    ToolSideEffect,
    ToolSpec,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.runtime.bootstrap import operational_database_url


@pytest.mark.asyncio
async def test_gate_i5_task_lifecycle_and_confirmation(tmp_path: Path) -> None:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    execution = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    execution.register_tool(
        ToolSpec(
            name="i5.read",
            version="1",
            description="deterministic read",
            capability="i5.read",
            handler=lambda arguments: {"value": arguments["value"]},
            resource_resolver=lambda arguments: f"fixture:{arguments['value']}",
        )
    )
    task_runtime = TaskRuntime(execution)
    subject = "client:i5"
    grant = await execution.create_grant(
        subject=subject,
        capability="i5.read",
        resource_scope="fixture:value",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    call = ToolCall(name="i5.read", arguments={"value": "value"}, subject=subject)
    # The Task path preserves the same ToolCall and Policy authority.
    task = await task_runtime.create_task(
        objective="read value", subject=subject, tool_call=call, grant_id=grant.id
    )
    runner = task_runtime._tasks[task.id]
    await runner
    stored = await task_runtime.get_task(task.id)
    assert stored is not None
    assert stored.status is TaskStatus.SUCCEEDED

    # A caller may use the exact grant through the existing authorized path.
    direct = await execution.invoke(call, grant_id=grant.id)
    assert direct.status == "SUCCEEDED"

    execution.register_tool(
        ToolSpec(
            name="i5.mutate",
            version="1",
            description="confirmation fixture",
            capability="i5.mutate",
            handler=lambda _: "mutated",
            resource_resolver=lambda _: "fixture:mutate",
            side_effect=ToolSideEffect.MUTATING,
        )
    )
    waiting = await task_runtime.create_task(
        objective="mutate after approval",
        subject=subject,
        tool_call=ToolCall(name="i5.mutate", arguments={}, subject=subject),
    )
    await task_runtime._tasks[waiting.id]
    pending = await task_runtime.get_task(waiting.id)
    assert pending is not None
    assert pending.status is TaskStatus.WAITING_CONFIRMATION
    confirmation_id = task_runtime.pending_confirmation(waiting.id)
    assert confirmation_id is not None
    resumed = await task_runtime.approve_confirmation(waiting.id, confirmation_id)
    assert resumed.status is TaskStatus.SUCCEEDED

    entered = asyncio.Event()
    release = asyncio.Event()

    async def cancellable(_: Mapping[str, Any]) -> str:
        entered.set()
        await release.wait()
        return "done"

    execution.register_tool(
        ToolSpec(
            name="i5.cancellable",
            version="1",
            description="cancellation fixture",
            capability="i5.cancellable",
            handler=cancellable,
            resource_resolver=lambda _: "fixture:cancellable",
        )
    )
    cancellable_grant = await execution.create_grant(
        subject=subject,
        capability="i5.cancellable",
        resource_scope="fixture:cancellable",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    cancellable_task = await task_runtime.create_task(
        objective="cancel work",
        subject=subject,
        tool_call=ToolCall(name="i5.cancellable", arguments={}, subject=subject),
        grant_id=cancellable_grant.id,
    )
    await entered.wait()
    cancelled = await task_runtime.cancel_task(cancellable_task.id)
    assert cancelled.status is TaskStatus.CANCELLED
    await task_runtime.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i5_subprocess_bounds_and_sandbox_fail_closed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    execution = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    command = (
        sys.executable,
        "-c",
        "import json,sys; data=json.load(sys.stdin); print(json.dumps({'echo': data['value']}))",
    )
    execution.register_tool(
        ToolSpec(
            name="i5.subprocess",
            version="1",
            description="controlled helper",
            capability="i5.subprocess",
            handler=lambda _: None,
            resource_resolver=lambda _: "fixture:subprocess",
            execution_mode=ToolExecutionMode.SUBPROCESS,
            subprocess_command=command,
            subprocess_output_limit_bytes=4096,
        )
    )
    grant = await execution.create_grant(
        subject="root",
        capability="i5.subprocess",
        resource_scope="fixture:subprocess",
        lifetime=GrantLifetime.ONE_SHOT,
    )
    result = await execution.invoke(
        ToolCall(
            name="i5.subprocess",
            arguments={"value": "ok"},
            subject="root",
        ),
        grant_id=grant.id,
    )
    assert result.status == "SUCCEEDED"
    assert result.value == {"echo": "ok"}

    execution.register_tool(
        ToolSpec(
            name="i5.sandbox",
            version="1",
            description="unavailable sandbox",
            capability="i5.sandbox",
            handler=lambda _: None,
            resource_resolver=lambda _: "fixture:sandbox",
            execution_mode=ToolExecutionMode.SANDBOX,
        )
    )
    sandbox_grant = await execution.create_grant(
        subject="root",
        capability="i5.sandbox",
        resource_scope="fixture:sandbox",
        lifetime=GrantLifetime.ONE_SHOT,
    )
    sandbox = await execution.invoke(
        ToolCall(name="i5.sandbox", arguments={}, subject="root"),
        grant_id=sandbox_grant.id,
    )
    assert sandbox.status == "FAILED"
    assert sandbox.error is not None
    assert sandbox.error.code == "SANDBOX_UNAVAILABLE"
    await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i5_agent_is_root_only_and_tools_are_narrowed(
    tmp_path: Path,
) -> None:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    execution = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    execution.register_tool(
        ToolSpec(
            name="i5.agent.read",
            version="1",
            description="agent read",
            capability="i5.agent.read",
            handler=lambda _: "ok",
            resource_resolver=lambda _: "fixture:agent",
        )
    )
    subject = "root"
    agent_grant = await execution.create_grant(
        subject=subject,
        capability="i5.agent.read",
        resource_scope="fixture:agent",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    definition = AgentDefinition(
        name="i5.fake",
        version="1",
        description="deterministic fake",
        required_capabilities=frozenset({"i5.agent.read"}),
        allowed_tools=frozenset({"i5.agent.read"}),
    )
    agent = AgentRuntime(execution)

    async def runner(context):
        result = await context.call_tool("i5.agent.read", {})
        assert result.status == "SUCCEEDED"
        return {"narrowed": True}

    agent.register(definition, runner)
    task = Task(objective="agent objective", subject=subject)
    await execution.store.save_task(task)
    with pytest.raises(PermissionError):
        await agent.create_agent_run(
            root_authority=type("NotRoot", (), {})(),
            task=task,
            definition=definition,
            delegated_context={"objective": task.objective},
            authority=AuthorityContext(subject),
        )
    run = await agent.create_agent_run(
        root_authority=agent.root_authority,
        task=task,
        definition=definition,
        delegated_context={"objective": task.objective},
        authority=AuthorityContext(subject),
    )
    assert run.allowed_tools == frozenset({"i5.agent.read"})
    completed = await agent.run(
        run,
        AuthorityContext(subject),
        grants={"i5.agent.read": agent_grant.id},
    )
    assert completed.status.value == "SUCCEEDED"
    assert completed.result == {"narrowed": True}
    # The runner receives no root capability or create_agent method.
    assert not hasattr(completed, "create_agent")
    await engine.dispose()
