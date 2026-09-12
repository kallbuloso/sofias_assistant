"""Gate I10 vertical evidence over the real Operational Store and boundary."""

from asyncio import to_thread
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.execution import (
    AgentDefinition,
    AgentRuntime,
    AuthorityContext,
    ExecutionRuntime,
    GrantLifetime,
    TaskRuntime,
    ToolCall,
    ToolSpec,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.runtime.bootstrap import operational_database_url


async def _runtime(tmp_path: Path) -> tuple[ExecutionRuntime, AsyncEngine]:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    runtime = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    runtime.register_tool(
        ToolSpec(
            name="gate.i10.echo",
            version="1",
            description="Deterministic audit fixture",
            capability="gate.i10.echo",
            handler=lambda arguments: {"echo": arguments["value"]},
            resource_resolver=lambda arguments: f"fixture:{arguments['value']}",
        )
    )
    return runtime, engine


@pytest.mark.asyncio
async def test_gate_i10_direct_trace_and_safe_authenticated_query(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    authenticator, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    app = create_local_http_app(authenticator, sessions, execution=runtime)
    try:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            opened = await client.post(
                "/api/v1/client-sessions",
                headers={"Authorization": f"Bearer {credential.reveal()}"},
            )
            session_id = opened.json()["id"]
            headers = {
                "Authorization": f"Bearer {credential.reveal()}",
                "X-Sofia-Client-Session-ID": session_id,
            }
            grant = await runtime.create_grant(
                subject=f"client:{session_id}",
                capability="gate.i10.echo",
                resource_scope="fixture:hello",
                lifetime=GrantLifetime.ONE_SHOT,
            )
            call_id = UUID(int=101)
            correlation_id = UUID(int=102)
            response = await client.post(
                "/api/v1/tools/gate.i10.echo/invoke",
                headers=headers,
                json={
                    "call_id": str(call_id),
                    "correlation_id": str(correlation_id),
                    "grant_id": str(grant.id),
                    "arguments": {
                        "value": "hello",
                        "api_key": "SUPER_SECRET_SENTINEL_I10",
                    },
                },
            )
            assert response.status_code == 200
            assert response.json()["status"] == "SUCCEEDED"
            trace = await client.get(
                "/api/v1/audit/traces/" + str(correlation_id), headers=headers
            )
            assert trace.status_code == 200
            body = trace.json()
            assert {item["event_type"] for item in body} >= {
                "TOOL_CALL_REQUESTED",
                "POLICY_DECISION",
                "TOOL_EXECUTION_STARTED",
                "TOOL_EXECUTION_COMPLETED",
            }
            assert "SUPER_SECRET_SENTINEL_I10" not in trace.text
            listed = await client.get("/api/v1/audit", headers=headers)
            assert listed.status_code == 200
            assert all("SUPER_SECRET_SENTINEL_I10" not in item for item in listed.text)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i10_denied_task_and_agent_trace_are_correlated(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    task_runtime = TaskRuntime(runtime)
    try:
        call = ToolCall(
            name="gate.i10.echo",
            arguments={"value": "denied"},
            subject="client:gate-i10",
        )
        denied = await runtime.invoke(call)
        assert denied.status == "DENY"
        denied_trace = await runtime.audit.trace(call.correlation_id)
        assert {entry.event_type for entry in denied_trace} >= {
            "TOOL_CALL_REQUESTED",
            "POLICY_DECISION",
        }
        task = await task_runtime.create_task(
            objective="audit task",
            subject="client:gate-i10",
            tool_call=ToolCall(
                name="gate.i10.echo",
                arguments={"value": "task"},
                subject="client:gate-i10",
            ),
        )
        await task_runtime._tasks[task.id]
        task_trace = await runtime.audit.trace(task.correlation_id)
        assert {entry.event_type for entry in task_trace} >= {
            "TASK_CREATED",
            "TASK_ATTEMPT_STARTED",
            "TASK_STATE_CHANGED",
        }
        definition = AgentDefinition(
            name="gate.i10.agent",
            version="1",
            description="deterministic agent",
            required_capabilities=frozenset(),
            allowed_tools=frozenset({"gate.i10.echo"}),
        )
        agent = AgentRuntime(runtime)

        async def run_agent(context: Any) -> dict[str, str]:
            result = await context.call_tool("gate.i10.echo", {"value": "agent"})
            return {"status": result.status}

        await agent.register_durable(definition, run_agent)
        run = await agent.create_agent_run(
            root_authority=agent.root_authority,
            task=task,
            definition=definition,
            delegated_context={"purpose": "gate"},
            authority=AuthorityContext("Sofia/root"),
        )
        await agent.run(run, AuthorityContext("Sofia/root"))
        agent_trace = await runtime.audit.trace(run.correlation_id)
        assert {entry.event_type for entry in agent_trace} >= {
            "AGENT_RUN_CREATED",
            "AGENT_RUN_STARTED",
            "TOOL_CALL_REQUESTED",
            "AGENT_RUN_COMPLETED",
        }
    finally:
        await task_runtime.stop()
        await engine.dispose()
