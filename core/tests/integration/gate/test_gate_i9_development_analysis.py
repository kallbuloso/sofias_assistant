"""Gate I9: bounded AI-driven delegation over real Tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sofias_assistant.ai import (
    Capability,
    CapabilityRouter,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
    ProviderResponseMetadata,
)
from sofias_assistant.ai.contracts import AIRequest, ToolCallProposal
from sofias_assistant.ai.fake import FakeAgentProvider
from sofias_assistant.capabilities.filesystem import (
    FilesystemCapability,
    canonicalize_path,
    file_resource,
)
from sofias_assistant.execution import (
    AgentDefinition,
    AgentRuntime,
    AuthorityContext,
    DevelopmentAnalysisAgent,
    ExecutionRuntime,
    GrantLifetime,
    SpecializationRequest,
    TaskRuntime,
    development_analysis_definition,
    register_development_analysis,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.runtime.bootstrap import operational_database_url


async def _runtime(tmp_path: Path) -> tuple[ExecutionRuntime, Any]:
    database = tmp_path / "operational.sqlite"
    await asyncio.to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    runtime = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    for spec in FilesystemCapability(max_read_bytes=1024).specs():
        runtime.register_tool(spec)
    return runtime, engine


def _router(provider: Any) -> CapabilityRouter:
    registry = ModelRegistry()
    identity = ModelIdentity("fake-agent", "development-analysis")
    registry.register(
        ModelRegistration(
            descriptor=ModelDescriptor(
                identity=identity,
                capabilities=frozenset(
                    {Capability.TEXT_GENERATION, Capability.TOOL_CALLING}
                ),
                execution_location=ExecutionLocation.LOCAL,
            ),
            binding=ProviderBinding(text_generation=provider),
        )
    )
    return CapabilityRouter(registry)


async def _grant(
    runtime: ExecutionRuntime, subject: str, capability: str, resource: str
) -> Any:
    grant = await runtime.create_grant(
        subject=subject,
        capability=capability,
        resource_scope=resource,
        lifetime=GrantLifetime.UNTIL_REVOKED,
    )
    return grant.id


@pytest.mark.asyncio
async def test_gate_i9_task_agent_adaptive_multi_tool_and_audit(tmp_path: Path) -> None:
    runtime, engine = await _runtime(tmp_path)
    task_runtime = TaskRuntime(runtime)
    try:
        workspace = tmp_path / "fixture" / "repo"
        workspace.mkdir(parents=True)
        target = workspace / "README.md"
        target.write_text("analysis target", encoding="utf-8")
        subject = "Sofia/root"
        root_resource = file_resource(canonicalize_path(workspace, must_exist=True))
        target_resource = file_resource(canonicalize_path(target, must_exist=True))
        grants = {
            "filesystem.list": await _grant(
                runtime, subject, "filesystem.list", root_resource
            ),
            "filesystem.read": await _grant(
                runtime, subject, "filesystem.read", target_resource
            ),
        }

        def decide(
            request: AIRequest, turn: int
        ) -> tuple[str, tuple[ToolCallProposal, ...]]:
            if turn == 1:
                return "", (
                    ToolCallProposal(
                        "list", "filesystem.list", {"path": str(workspace)}
                    ),
                )
            if turn == 2:
                return "", (
                    ToolCallProposal("read", "filesystem.read", {"path": str(target)}),
                )
            return (
                '{"summary":"read the repository target","findings":[{"file":"README.md"}]}'
            ), ()

        provider = FakeAgentProvider(decide)
        agent_runtime = AgentRuntime(runtime)
        definition = await register_development_analysis(
            agent_runtime, _router(provider)
        )
        task = await task_runtime.create_agent_task(
            objective="Analyze the repository fixture and report findings",
            subject=subject,
            authority=AuthorityContext(subject),
        )
        run = await agent_runtime.create_agent_run(
            root_authority=agent_runtime.root_authority,
            task=task,
            definition=definition,
            delegated_context={
                "objective": task.objective,
                "workspace": str(workspace),
                "constraints": ["read-only"],
                "runtime_limits": {"max_steps": 4},
            },
            authority=AuthorityContext(subject),
            allowed_tools=frozenset({"filesystem.list", "filesystem.read"}),
            workspace=str(workspace),
        )
        completed = await agent_runtime.run(
            run, AuthorityContext(subject), grants=grants
        )
        task_done = await task_runtime.complete_agent_task(
            task.id,
            result=completed.result,
            succeeded=completed.status.value == "SUCCEEDED",
            agent_run_id=completed.id,
        )

        assert completed.status.value == "SUCCEEDED"
        assert task_done.status.value == "SUCCEEDED"
        assert task_done.execution_strategy.value == "AGENT"
        assert completed.result["summary"] == "read the repository target"
        assert completed.result["tool_usage_summary"] == {
            "filesystem.list": 1,
            "filesystem.read": 1,
        }
        assert len(provider.requests) == 3
        assert len(provider.requests[0].tools) == 2
        trace = await runtime.audit.query(agent_run_id=completed.id)
        assert {entry.event_type for entry in trace} >= {
            "AGENT_RUN_CREATED",
            "AGENT_RUN_STARTED",
            "AGENT_PROVIDER_INFERENCE",
            "TOOL_CALL_REQUESTED",
            "POLICY_DECISION",
            "TOOL_EXECUTION_COMPLETED",
            "AGENT_RUN_COMPLETED",
            "TASK_STATE_CHANGED",
        }
    finally:
        await task_runtime.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i9_denies_subset_escape_without_execution(tmp_path: Path) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        provider = FakeAgentProvider(
            lambda request, turn: ("", (ToolCallProposal("x", "shell.execute", {}),))
        )
        agent_runtime = AgentRuntime(runtime)
        definition = development_analysis_definition()
        await agent_runtime.register_durable(
            definition, DevelopmentAnalysisAgent(_router(provider))
        )
        task = await TaskRuntime(runtime).create_agent_task(
            objective="test subset",
            subject="Sofia/root",
            authority=AuthorityContext("Sofia/root"),
        )
        run = await agent_runtime.create_agent_run(
            root_authority=agent_runtime.root_authority,
            task=task,
            definition=definition,
            delegated_context={"workspace": str(tmp_path)},
            authority=AuthorityContext("Sofia/root"),
            allowed_tools=frozenset({"filesystem.read"}),
        )
        done = await agent_runtime.run(run, AuthorityContext("Sofia/root"))
        assert done.status.value == "FAILED"
        assert done.result["error"]["code"] == "TOOL_SUBSET_DENIED"
        assert not any(
            entry.event_type == "TOOL_CALL_REQUESTED"
            and entry.action == "shell.execute"
            for entry in await runtime.audit.query(agent_run_id=done.id)
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i9_workspace_escape_is_denied_by_existing_policy(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        provider = FakeAgentProvider(
            lambda request, turn: (
                ('{"summary":"denied outside"}', ())
                if turn == 2
                else (
                    "",
                    (
                        ToolCallProposal(
                            "escape", "filesystem.read", {"path": str(outside)}
                        ),
                    ),
                )
            )
        )
        agent_runtime = AgentRuntime(runtime)
        definition = await register_development_analysis(
            agent_runtime, _router(provider)
        )
        task = await TaskRuntime(runtime).create_agent_task(
            objective="test workspace",
            subject="Sofia/root",
            authority=AuthorityContext("Sofia/root"),
        )
        root_resource = file_resource(canonicalize_path(workspace, must_exist=True))
        read_grant = await _grant(
            runtime, "Sofia/root", "filesystem.read", root_resource + "/*"
        )
        run = await agent_runtime.create_agent_run(
            root_authority=agent_runtime.root_authority,
            task=task,
            definition=definition,
            delegated_context={"workspace": str(workspace)},
            authority=AuthorityContext("Sofia/root"),
            allowed_tools=frozenset({"filesystem.read"}),
            workspace=str(workspace),
        )
        done = await agent_runtime.run(
            run, AuthorityContext("Sofia/root"), grants={"filesystem.read": read_grant}
        )
        assert done.status.value == "SUCCEEDED", done.result
        assert done.result["summary"] == "denied outside"
        assert any(
            entry.event_type == "TOOL_CALL_DENIED"
            for entry in await runtime.audit.query(agent_run_id=done.id)
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i9_runaway_agent_is_bounded(tmp_path: Path) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        provider = FakeAgentProvider(
            lambda request, turn: (
                "",
                (
                    ToolCallProposal(
                        str(turn), "filesystem.list", {"path": str(workspace)}
                    ),
                ),
            )
        )
        agent_runtime = AgentRuntime(runtime)
        definition = await register_development_analysis(
            agent_runtime,
            _router(provider),
            definition=development_analysis_definition(runtime_limits={"max_steps": 2}),
        )
        task = await TaskRuntime(runtime).create_agent_task(
            objective="run bounded",
            subject="Sofia/root",
            authority=AuthorityContext("Sofia/root"),
        )
        list_resource = file_resource(canonicalize_path(workspace, must_exist=True))
        grant = await _grant(runtime, "Sofia/root", "filesystem.list", list_resource)
        run = await agent_runtime.create_agent_run(
            root_authority=agent_runtime.root_authority,
            task=task,
            definition=definition,
            delegated_context={"workspace": str(workspace)},
            authority=AuthorityContext("Sofia/root"),
            allowed_tools=frozenset({"filesystem.list"}),
            workspace=str(workspace),
        )
        done = await agent_runtime.run(
            run, AuthorityContext("Sofia/root"), grants={"filesystem.list": grant}
        )
        assert done.status.value == "FAILED"
        assert done.result["error"]["code"] == "RUNTIME_LIMIT_EXCEEDED"
        assert len(provider.requests) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i9_malformed_provider_tool_call_never_executes(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:

        class MalformedProvider:
            async def generate_text(self, *, model: Any, request: AIRequest) -> Any:
                return SimpleNamespace(
                    text="",
                    metadata=ProviderResponseMetadata(request.request_id, model),
                    tool_calls=(
                        SimpleNamespace(
                            name="filesystem.read", arguments="not-an-object"
                        ),
                    ),
                )

        provider = MalformedProvider()
        agent_runtime = AgentRuntime(runtime)
        definition = await register_development_analysis(
            agent_runtime, _router(provider)
        )
        task = await TaskRuntime(runtime).create_agent_task(
            objective="malformed proposal",
            subject="Sofia/root",
            authority=AuthorityContext("Sofia/root"),
        )
        run = await agent_runtime.create_agent_run(
            root_authority=agent_runtime.root_authority,
            task=task,
            definition=definition,
            delegated_context={"workspace": str(tmp_path)},
            authority=AuthorityContext("Sofia/root"),
            allowed_tools=frozenset({"filesystem.read"}),
        )
        done = await agent_runtime.run(run, AuthorityContext("Sofia/root"))
        assert done.status.value == "FAILED"
        assert done.result["error"]["code"] == "MALFORMED_TOOL_CALL"
        assert not any(
            entry.event_type == "TOOL_CALL_REQUESTED"
            for entry in await runtime.audit.query(agent_run_id=done.id)
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_i9_agent_can_only_return_specialization_request(
    tmp_path: Path,
) -> None:
    runtime, engine = await _runtime(tmp_path)
    try:
        agent_runtime = AgentRuntime(runtime)
        definition = AgentDefinition(
            name="gate.i9.specialization",
            version="1",
            description="specialization request fixture",
            required_capabilities=frozenset(),
            allowed_tools=frozenset(),
        )

        async def runner(context: Any) -> dict[str, Any]:
            request = context.request_specialization(
                "inspect dependencies",
                frozenset({"filesystem.read"}),
                "needs a narrower capability",
            )
            assert isinstance(request, SpecializationRequest)
            assert not hasattr(context, "create_agent_run")
            return {"specialization_request_id": str(request.id)}

        await agent_runtime.register_durable(definition, runner)
        task = await TaskRuntime(runtime).create_agent_task(
            objective="request specialization",
            subject="Sofia/root",
            authority=AuthorityContext("Sofia/root"),
        )
        run = await agent_runtime.create_agent_run(
            root_authority=agent_runtime.root_authority,
            task=task,
            definition=definition,
            delegated_context={"workspace": str(tmp_path)},
            authority=AuthorityContext("Sofia/root"),
        )
        done = await agent_runtime.run(run, AuthorityContext("Sofia/root"))
        assert done.status.value == "SUCCEEDED"
        assert "specialization_request_id" in done.result
    finally:
        await engine.dispose()
