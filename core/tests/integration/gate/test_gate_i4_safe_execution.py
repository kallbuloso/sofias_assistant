"""Vertical Gate I4 evidence through the authenticated local boundary."""

import asyncio
from asyncio import to_thread
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.execution import (
    ExecutionRuntime,
    GrantLifetime,
    ToolCall,
    ToolResult,
    ToolSideEffect,
    ToolSpec,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.runtime.bootstrap import operational_database_url


def _bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


@pytest.mark.asyncio
async def test_gate_i4_direct_confirmation_deny_and_artifact_paths(
    tmp_path: Path,
) -> None:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    runtime = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    counts = {"read": 0, "mutate": 0, "artifact": 0}

    def read_validator(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(arguments.get("value"), str):
            raise ValueError("value required")
        return arguments

    runtime.register_tool(
        ToolSpec(
            name="test.read",
            version="1",
            description="deterministic read fixture",
            capability="test.read",
            handler=lambda arguments: _read_handler(arguments, counts),
            resource_resolver=lambda arguments: f"fixture:{arguments['value']}",
            input_validator=read_validator,
        )
    )
    with pytest.raises(ValueError, match="already registered"):
        runtime.register_tool(
            ToolSpec(
                name="test.read",
                version="2",
                description="collision",
                capability="test.read",
                handler=lambda _: None,
                resource_resolver=lambda _: "fixture:item",
            )
        )

    async def mutate(_: Mapping[str, Any]) -> dict[str, str]:
        counts["mutate"] += 1
        return {"mutated": "yes"}

    runtime.register_tool(
        ToolSpec(
            name="test.mutate",
            version="1",
            description="deterministic mutating fixture",
            capability="test.mutate",
            handler=mutate,
            resource_resolver=lambda _: "fixture:mutate",
            side_effect=ToolSideEffect.MUTATING,
        )
    )

    async def artifact(arguments: Mapping[str, Any]) -> ToolResult:
        counts["artifact"] += 1
        ref = await runtime.artifacts.create(
            str(arguments["value"]).encode(),
            kind="test-output",
            media_type="text/plain",
        )
        return ToolResult(status="SUCCEEDED", call_id=UUID(int=0), artifact_refs=(ref,))

    runtime.register_tool(
        ToolSpec(
            name="test.artifact",
            version="1",
            description="deterministic artifact fixture",
            capability="test.artifact",
            handler=artifact,
            resource_resolver=lambda arguments: (
                f"fixture:artifact:{arguments['value']}"
            ),
        )
    )

    authenticator, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    app = create_local_http_app(authenticator, sessions, execution=runtime)
    with TestClient(app) as client:
        opened = client.post(
            "/api/v1/client-sessions", headers=_bearer(credential.reveal())
        )
        assert opened.status_code == 201
        session_id = opened.json()["id"]
        headers = {
            **_bearer(credential.reveal()),
            "X-Sofia-Client-Session-ID": session_id,
        }
        subject = f"client:{session_id}"

        listed = client.get("/api/v1/tools", headers=headers)
        assert listed.status_code == 200
        assert {item["name"] for item in listed.json()} == {
            "test.read",
            "test.mutate",
            "test.artifact",
        }

        read_grant = await runtime.create_grant(
            subject=subject,
            capability="test.read",
            resource_scope="fixture:item",
            lifetime=GrantLifetime.UNTIL_REVOKED,
            session_id=UUID(session_id),
        )
        direct = client.post(
            "/api/v1/tools/test.read/invoke",
            headers=headers,
            json={"arguments": {"value": "item"}, "grant_id": str(read_grant.id)},
        )
        assert direct.status_code == 200
        assert direct.json()["status"] == "SUCCEEDED"
        assert counts["read"] == 1
        invalid = client.post(
            "/api/v1/tools/test.read/invoke",
            headers=headers,
            json={"arguments": {}},
        )
        assert invalid.json()["error_code"] == "INVALID_ARGUMENTS"
        mismatch = await runtime.invoke(
            ToolCall(
                name="test.read",
                arguments={"value": "other"},
                subject=subject,
                session_id=UUID(session_id),
            ),
            grant_id=read_grant.id,
        )
        assert mismatch.status == "DENY"

        runtime.registry.disable("test.read")
        disabled = await runtime.invoke(
            ToolCall(
                name="test.read",
                arguments={"value": "item"},
                subject=subject,
                session_id=UUID(session_id),
            ),
            grant_id=read_grant.id,
        )
        assert disabled.error is not None
        assert disabled.error.code == "TOOL_DISABLED"
        runtime.registry.enable("test.read")
        unregistered = await runtime.invoke(
            ToolCall(name="missing", arguments={}, subject=subject),
        )
        assert unregistered.error is not None
        assert unregistered.error.code == "UNREGISTERED_TOOL"

        confirmation = client.post(
            "/api/v1/tools/test.mutate/invoke",
            headers=headers,
            json={"arguments": {}},
        )
        assert confirmation.json()["status"] == "CONFIRMATION_REQUIRED"
        confirmation_id = confirmation.json()["confirmation_id"]
        assert counts["mutate"] == 0
        approved = client.post(
            f"/api/v1/confirmations/{confirmation_id}/approve",
            headers=headers,
            json={"lifetime": "ONE_SHOT"},
        )
        assert approved.json()["status"] == "SUCCEEDED"
        assert counts["mutate"] == 1
        second_approval = client.post(
            f"/api/v1/confirmations/{confirmation_id}/approve",
            headers=headers,
            json={"lifetime": "UNTIL_REVOKED"},
        )
        assert second_approval.status_code == 404

        artifact_grant = await runtime.create_grant(
            subject=subject,
            capability="test.artifact",
            resource_scope="fixture:artifact:item",
            lifetime=GrantLifetime.ONE_SHOT,
            session_id=UUID(session_id),
        )
        artifact_result = await runtime.invoke(
            ToolCall(
                name="test.artifact",
                arguments={"value": "item"},
                subject=subject,
                session_id=UUID(session_id),
            ),
            grant_id=artifact_grant.id,
        )
        assert artifact_result.status == "SUCCEEDED"
        assert len(artifact_result.artifact_refs) == 1
        retrieved = client.get(
            f"/api/v1/artifacts/{artifact_result.artifact_refs[0].id}",
            headers=headers,
        )
        assert retrieved.status_code == 200
        assert retrieved.content == b"item"
        assert counts["artifact"] == 1
    await engine.dispose()


def _read_handler(
    arguments: Mapping[str, Any], counts: dict[str, int]
) -> dict[str, Any]:
    counts["read"] += 1
    return {"value": arguments["value"]}


@pytest.mark.asyncio
async def test_gate_i4_grant_lifetimes_revocation_and_duplicate_execution(
    tmp_path: Path,
) -> None:
    database = tmp_path / "operational.sqlite"
    await to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    runtime = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    executions = 0

    def handler(_: Mapping[str, Any]) -> str:
        nonlocal executions
        executions += 1
        return "ok"

    runtime.register_tool(
        ToolSpec(
            name="test.idempotent",
            version="1",
            description="duplicate guard fixture",
            capability="test.idempotent",
            handler=handler,
            resource_resolver=lambda _: "fixture:stable",
        )
    )
    subject = "client:test"
    session_id = UUID(int=1)
    session_grant = await runtime.create_grant(
        subject=subject,
        capability="test.idempotent",
        resource_scope="fixture:stable",
        lifetime=GrantLifetime.SESSION,
        session_id=session_id,
    )
    call = ToolCall(
        name="test.idempotent",
        arguments={},
        subject=subject,
        session_id=session_id,
    )
    first, second = await asyncio.gather(
        runtime.invoke(call, grant_id=session_grant.id),
        runtime.invoke(call, grant_id=session_grant.id),
    )
    assert first.status == second.status == "SUCCEEDED"
    assert executions == 1

    wrong_session = await runtime.invoke(
        ToolCall(
            name="test.idempotent",
            arguments={},
            subject=subject,
            session_id=UUID(int=2),
        ),
        grant_id=session_grant.id,
    )
    assert wrong_session.status == "DENY"

    revocable = await runtime.create_grant(
        subject=subject,
        capability="test.idempotent",
        resource_scope="fixture:stable",
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    assert await runtime.revoke_grant(revocable.id) is True
    assert (
        await runtime.invoke(
            ToolCall(name="test.idempotent", arguments={}, subject=subject),
            grant_id=revocable.id,
        )
    ).status == "DENY"

    one_shot = await runtime.create_grant(
        subject=subject,
        capability="test.idempotent",
        resource_scope="fixture:stable",
        lifetime=GrantLifetime.ONE_SHOT,
    )
    assert (
        await runtime.invoke(
            ToolCall(name="test.idempotent", arguments={}, subject=subject),
            grant_id=one_shot.id,
        )
    ).status == "SUCCEEDED"
    assert (
        await runtime.invoke(
            ToolCall(name="test.idempotent", arguments={}, subject=subject),
            grant_id=one_shot.id,
        )
    ).status == "DENY"
    await engine.dispose()
