"""Gate I5 authenticated Task vertical over the existing local boundary."""

from asyncio import to_thread
from pathlib import Path
from uuid import UUID

import httpx2
import pytest

from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.execution import (
    ExecutionRuntime,
    GrantLifetime,
    TaskRuntime,
    ToolSpec,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.runtime.bootstrap import operational_database_url


@pytest.mark.asyncio
async def test_gate_i5_authenticated_task_lifecycle(tmp_path: Path) -> None:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    execution = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    execution.register_tool(
        ToolSpec(
            name="gate.i5.read",
            version="1",
            description="Gate I5 deterministic read",
            capability="gate.i5.read",
            handler=lambda arguments: {"echo": arguments["value"]},
            resource_resolver=lambda arguments: f"fixture:{arguments['value']}",
        )
    )
    task_runtime = TaskRuntime(execution)
    authenticator, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    app = create_local_http_app(authenticator, sessions, tasks=task_runtime)
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test"
    ) as client:
        opened = await client.post(
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential.reveal()}"},
        )
        assert opened.status_code == 201
        session_id = opened.json()["id"]
        headers = {
            "Authorization": f"Bearer {credential.reveal()}",
            "X-Sofia-Client-Session-ID": session_id,
        }
        grant = await execution.create_grant(
            subject=f"client:{session_id}",
            capability="gate.i5.read",
            resource_scope="fixture:value",
            lifetime=GrantLifetime.UNTIL_REVOKED,
        )
        created = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "objective": "echo a value",
                "tool_name": "gate.i5.read",
                "arguments": {"value": "value"},
                "grant_id": str(grant.id),
            },
        )
        assert created.status_code == 201
        task_id = UUID(created.json()["id"])
        await task_runtime._tasks[task_id]
        observed = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert observed.status_code == 200
        assert observed.json()["status"] == "SUCCEEDED"
        assert observed.json()["result"] == {"echo": "value"}
    await task_runtime.stop()
    await engine.dispose()
