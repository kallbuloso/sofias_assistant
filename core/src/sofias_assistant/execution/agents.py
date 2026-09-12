"""Root-owned Agent definitions and deterministic execution seam."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sofias_assistant.execution.models import (
    AgentDefinition,
    AgentRun,
    AgentRunStatus,
    AuthorityContext,
    SpecializationRequest,
    Task,
    ToolCall,
)
from sofias_assistant.execution.runtime import ExecutionRuntime
from sofias_assistant.execution.store import ExecutionStore

AgentRunner = Callable[["AgentExecutionContext"], Awaitable[Any]]


class AgentRegistry:
    """Separate collision-checked registry for Agent definitions."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> None:
        key = (definition.name, definition.version)
        if key in self._definitions:
            raise ValueError("Agent definition is already registered")
        self._definitions[key] = definition

    def resolve(self, name: str, version: str) -> AgentDefinition:
        return self._definitions[(name, version)]

    def list(self) -> tuple[AgentDefinition, ...]:
        return tuple(self._definitions.values())

    def enable(self, name: str, version: str) -> None:
        definition = self.resolve(name, version)
        self._definitions[(name, version)] = replace(definition, enabled=True)

    def disable(self, name: str, version: str) -> None:
        definition = self.resolve(name, version)
        self._definitions[(name, version)] = replace(definition, enabled=False)


class RootAuthority:
    """Opaque capability held only by the Core AgentRuntime owner."""

    __slots__ = ()


class AgentExecutionContext:
    """Narrow view exposed to a deterministic Agent runner."""

    def __init__(
        self,
        run: AgentRun,
        execution: ExecutionRuntime,
        authority: AuthorityContext,
        grants: Mapping[str, UUID] | None = None,
    ) -> None:
        self.run = run
        self._execution = execution
        self._authority = authority
        self._grants = dict(grants or {})

    async def call_tool(self, name: str, arguments: Mapping[str, Any]):
        if name not in self.run.allowed_tools:
            raise PermissionError("Tool is outside AgentRun allowed subset")
        return await self._execution.invoke(
            ToolCall(
                name=name,
                arguments=arguments,
                subject=self._authority.subject,
                session_id=self._authority.session_id,
                correlation_id=self.run.correlation_id,
                causation_id=self.run.id,
            ),
            grant_id=self._grants.get(name),
        )

    def request_specialization(
        self, objective: str, requested_tools: frozenset[str], reason: str
    ) -> SpecializationRequest:
        return SpecializationRequest(self.run.id, objective, requested_tools, reason)


class AgentRuntime:
    """Core/root owner of AgentRun creation and execution."""

    def __init__(self, execution: ExecutionRuntime) -> None:
        self.execution = execution
        self.store: ExecutionStore = execution.store
        self.registry = AgentRegistry()
        self._root_authority = RootAuthority()
        self._runners: dict[UUID, AgentRunner] = {}
        self._tasks: dict[UUID, Any] = {}

    @property
    def root_authority(self) -> RootAuthority:
        return self._root_authority

    def register(self, definition: AgentDefinition, runner: AgentRunner) -> None:
        self.registry.register(definition)
        self._runners[definition.id] = runner

    async def register_durable(
        self, definition: AgentDefinition, runner: AgentRunner
    ) -> None:
        self.register(definition, runner)
        await self.store.save_agent_definition(definition)

    async def register_definition(
        self, definition: AgentDefinition, runner: AgentRunner
    ) -> None:
        """Named durable registration seam used by Core composition/tests."""

        await self.register_durable(definition, runner)

    async def create_agent_run(
        self,
        *,
        root_authority: RootAuthority,
        task: Task,
        definition: AgentDefinition,
        delegated_context: Mapping[str, Any],
        authority: AuthorityContext,
    ) -> AgentRun:
        if root_authority is not self._root_authority:
            raise PermissionError("Only Sofia/root may create an AgentRun")
        if not definition.enabled:
            raise ValueError("Agent definition is disabled")
        if not delegated_context:
            raise ValueError("Agent context must be explicitly narrowed")
        run = AgentRun(
            task_id=task.id,
            agent_definition_id=definition.id,
            agent_definition_version=definition.version,
            objective=task.objective,
            delegated_context=dict(delegated_context),
            authority_scope=authority.subject,
            allowed_tools=definition.allowed_tools,
            provider_requirements=definition.provider_requirements,
            runtime_limits=definition.runtime_limits,
        )
        await self.store.save_agent_run(run)
        await self.execution.audit.record(
            event_type="AGENT_RUN_CREATED",
            actor="Sofia/root",
            subject=authority.subject,
            action="agent.run.create",
            resource=definition.name,
            outcome=run.status.value,
            origin="AGENT_RUN",
            correlation_id=run.correlation_id,
            task_id=task.id,
            agent_run_id=run.id,
            metadata={
                "agent": definition.name,
                "version": definition.version,
                "allowed_tools": sorted(definition.allowed_tools),
            },
        )
        return run

    async def run(
        self,
        run: AgentRun,
        authority: AuthorityContext,
        *,
        grants: Mapping[str, UUID] | None = None,
    ) -> AgentRun:
        runner = self._runners.get(run.agent_definition_id)
        if runner is None:
            failed = replace(
                run,
                status=AgentRunStatus.FAILED,
                result={"error": "runner unavailable"},
            )
            await self.store.update_agent_run(failed)
            await self.execution.audit.record(
                event_type="AGENT_RUN_COMPLETED",
                actor="Sofia/root",
                subject=authority.subject,
                action="agent.run",
                resource=str(run.id),
                outcome=failed.status.value,
                origin="AGENT_RUN",
                correlation_id=run.correlation_id,
                causation_id=run.id,
                task_id=run.task_id,
                agent_run_id=run.id,
            )
            return failed
        started = replace(
            run, status=AgentRunStatus.RUNNING, started_at=datetime.now(UTC)
        )
        await self.store.update_agent_run(started)
        await self.execution.audit.record(
            event_type="AGENT_RUN_STARTED",
            actor="Sofia/root",
            subject=authority.subject,
            action="agent.run",
            resource=str(run.id),
            outcome=started.status.value,
            origin="AGENT_RUN",
            correlation_id=run.correlation_id,
            causation_id=run.id,
            task_id=run.task_id,
            agent_run_id=run.id,
        )
        context = AgentExecutionContext(started, self.execution, authority, grants)
        try:
            result = await runner(context)
        except asyncio.CancelledError:
            cancelled = replace(
                started, status=AgentRunStatus.CANCELLED, finished_at=datetime.now(UTC)
            )
            await self.store.update_agent_run(cancelled)
            await self.execution.audit.record(
                event_type="AGENT_RUN_CANCELLED",
                actor="Sofia/root",
                subject=authority.subject,
                action="agent.run",
                resource=str(run.id),
                outcome=cancelled.status.value,
                origin="AGENT_RUN",
                correlation_id=run.correlation_id,
                causation_id=run.id,
                task_id=run.task_id,
                agent_run_id=run.id,
            )
            raise
        except Exception:
            failed = replace(
                started, status=AgentRunStatus.FAILED, finished_at=datetime.now(UTC)
            )
            await self.store.update_agent_run(failed)
            await self.execution.audit.record(
                event_type="AGENT_RUN_COMPLETED",
                actor="Sofia/root",
                subject=authority.subject,
                action="agent.run",
                resource=str(run.id),
                outcome=failed.status.value,
                origin="AGENT_RUN",
                correlation_id=run.correlation_id,
                causation_id=run.id,
                task_id=run.task_id,
                agent_run_id=run.id,
            )
            return failed
        completed = replace(
            started,
            status=AgentRunStatus.SUCCEEDED,
            result=result,
            finished_at=datetime.now(UTC),
        )
        await self.store.update_agent_run(completed)
        await self.execution.audit.record(
            event_type="AGENT_RUN_COMPLETED",
            actor="Sofia/root",
            subject=authority.subject,
            action="agent.run",
            resource=str(run.id),
            outcome=completed.status.value,
            origin="AGENT_RUN",
            correlation_id=run.correlation_id,
            causation_id=run.id,
            task_id=run.task_id,
            agent_run_id=run.id,
        )
        return completed

    async def stop(self) -> None:
        for task in tuple(self._tasks.values()):
            if not task.done():
                task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
