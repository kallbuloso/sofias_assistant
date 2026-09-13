"""The first real, bounded Agent specialization: repository analysis."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sofias_assistant.ai import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    AIRequestRequirements,
    AIToolDefinition,
    Capability,
    CapabilityRouter,
    DataLocality,
)
from sofias_assistant.execution.agents import AgentExecutionContext, AgentRuntime
from sofias_assistant.execution.models import (
    AgentDefinition,
    AgentExecutionOutcome,
    AgentRun,
    ToolResult,
)

_DEFAULT_LIMITS = {"max_steps": 8, "max_tool_calls": 12, "max_duration": 30.0}
_MAX_OBSERVATION_BYTES = 8_192
_MAX_FINAL_TEXT_BYTES = 16_384


@dataclass(frozen=True, slots=True)
class DelegatedContext:
    """The only context projected from Sofia/root into this specialization."""

    objective: str
    workspace: str
    constraints: tuple[str, ...] = ()
    selected_context: tuple[str, ...] = ()
    runtime_limits: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.objective.strip() or not self.workspace.strip():
            raise ValueError("delegated objective and workspace must not be blank")

    def as_mapping(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "workspace": self.workspace,
            "constraints": list(self.constraints),
            "selected_context": list(self.selected_context),
            "runtime_limits": dict(self.runtime_limits),
        }


def development_analysis_definition(
    *,
    runtime_limits: Mapping[str, Any] | None = None,
    provider_requirements: Mapping[str, Any] | None = None,
) -> AgentDefinition:
    """Return the least-privileged registered definition for repository analysis."""

    return AgentDefinition(
        name="development-analysis",
        version="1",
        description="Read-only, AI-driven repository analysis",
        required_capabilities=frozenset({"repository-analysis"}),
        allowed_tools=frozenset({"filesystem.list", "filesystem.read"}),
        context_policy="delegated_context_only",
        provider_requirements=dict(provider_requirements or {}),
        runtime_limits={**_DEFAULT_LIMITS, **dict(runtime_limits or {})},
    )


class DevelopmentAnalysisAgent:
    """Agent runner that delegates every action to the existing runtime."""

    def __init__(self, router: CapabilityRouter) -> None:
        self._router = router

    async def __call__(self, context: AgentExecutionContext) -> AgentExecutionOutcome:
        return await self.run(context)

    async def run(self, context: AgentExecutionContext) -> AgentExecutionOutcome:
        run = context.run
        limits = _limits(run.runtime_limits)
        try:
            return await asyncio.wait_for(
                self._loop(context, limits), timeout=limits["max_duration"]
            )
        except TimeoutError:
            return _failed("RUNTIME_LIMIT_EXCEEDED", "Agent duration limit exceeded")
        except Exception:
            return _failed("AGENT_LOOP_FAILED", "Agent loop failed safely")

    async def _loop(
        self, context: AgentExecutionContext, limits: Mapping[str, int | float]
    ) -> AgentExecutionOutcome:
        run = context.run
        requirements = _requirements(run.provider_requirements)
        route = self._router.route(requirements)
        provider = route.binding.text_generation
        if provider is None:
            return _failed("PROVIDER_UNAVAILABLE", "No text generation provider")

        tool_definitions = tuple(
            _tool_definition(context, name) for name in sorted(run.allowed_tools)
        )
        messages = _initial_messages(run, tool_definitions)
        inspected: list[str] = []
        usage = Counter[str]()
        observations: list[dict[str, Any]] = []
        provider_calls = 0
        tool_calls = 0

        for _ in range(int(limits["max_steps"])):
            provider_calls += 1
            request = AIRequest(uuid4(), tuple(messages), tool_definitions)
            response = await provider.generate_text(
                model=route.descriptor.identity, request=request
            )
            await context._execution.audit.record(
                event_type="AGENT_PROVIDER_INFERENCE",
                actor="Sofia/root",
                subject=context._authority.subject,
                action="agent.provider.inference",
                resource=route.descriptor.identity.provider_id
                + "/"
                + route.descriptor.identity.model_id,
                outcome="SUCCEEDED",
                origin="AGENT_RUN",
                correlation_id=run.correlation_id,
                causation_id=run.id,
                task_id=run.task_id,
                agent_run_id=run.id,
                metadata={
                    "provider_id": route.descriptor.identity.provider_id,
                    "model_id": route.descriptor.identity.model_id,
                    "provider_request_id": response.metadata.provider_request_id,
                    "tool_proposal_count": len(response.tool_calls),
                },
            )
            if not response.tool_calls:
                return _final_result(
                    response.text,
                    inspected,
                    usage,
                    provider_calls,
                    tool_calls,
                    observations,
                )

            for proposal in response.tool_calls:
                if tool_calls >= int(limits["max_tool_calls"]):
                    return _failed(
                        "RUNTIME_LIMIT_EXCEEDED", "Agent Tool call limit exceeded"
                    )
                tool_calls += 1
                if not isinstance(proposal.name, str) or not isinstance(
                    proposal.arguments, Mapping
                ):
                    return _failed(
                        "MALFORMED_TOOL_CALL",
                        "Provider ToolCall must contain an object argument map",
                    )
                usage[proposal.name] += 1
                if proposal.name not in run.allowed_tools:
                    await context._execution.audit.record(
                        event_type="AGENT_TOOL_PROPOSAL_DENIED",
                        actor="Sofia/root",
                        subject=context._authority.subject,
                        action=proposal.name,
                        resource=proposal.name,
                        outcome="DENY",
                        origin="AGENT_RUN",
                        correlation_id=run.correlation_id,
                        causation_id=run.id,
                        task_id=run.task_id,
                        agent_run_id=run.id,
                        metadata={"reason": "outside_agent_tool_subset"},
                    )
                    return _failed(
                        "TOOL_SUBSET_DENIED",
                        "Provider proposed a Tool outside the AgentRun subset",
                    )
                result = await context.call_tool(
                    proposal.name, dict(proposal.arguments)
                )
                inspected.append(_inspected_resource(proposal.name, proposal.arguments))
                observations.append(_observation(proposal.name, result))
                messages.append(
                    AIMessage(
                        AIMessageRole.USER,
                        _bounded_json(
                            {"tool_observation": observations[-1]},
                            _MAX_OBSERVATION_BYTES,
                        ),
                    )
                )
        return _failed("RUNTIME_LIMIT_EXCEEDED", "Agent step limit exceeded")


async def register_development_analysis(
    runtime: AgentRuntime,
    router: CapabilityRouter,
    *,
    definition: AgentDefinition | None = None,
) -> AgentDefinition:
    """Register the specialization in the authoritative AgentRuntime."""

    selected = definition or development_analysis_definition()
    await runtime.register_durable(selected, DevelopmentAnalysisAgent(router))
    return selected


def _requirements(values: Mapping[str, Any]) -> AIRequestRequirements:
    required_values = values.get(
        "required_capabilities",
        [Capability.TEXT_GENERATION.value, Capability.TOOL_CALLING.value],
    )
    preferred_values = values.get("preferred_capabilities", [])
    required = frozenset(Capability(value) for value in required_values)
    preferred = frozenset(Capability(value) for value in preferred_values)
    locality = DataLocality(values.get("locality", DataLocality.LOCAL_ONLY.value))
    return AIRequestRequirements(required, preferred, locality)


def _limits(values: Mapping[str, Any]) -> dict[str, int | float]:
    limits: dict[str, int | float] = {}
    for key, default in _DEFAULT_LIMITS.items():
        value = values.get(key, default)
        if isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                value = default
        elif (
            isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0
        ):
            value = default
        limits[key] = value
    return limits


def _tool_definition(context: AgentExecutionContext, name: str) -> AIToolDefinition:
    spec = context._execution.registry.resolve(name)
    return AIToolDefinition(
        name=spec.name,
        description=spec.description,
        parameters={"type": "object", "additionalProperties": True},
    )


def _initial_messages(
    run: AgentRun, tools: tuple[AIToolDefinition, ...]
) -> list[AIMessage]:
    context = {
        "objective": run.objective,
        "workspace": run.workspace or run.delegated_context.get("workspace"),
        "constraints": run.delegated_context.get("constraints", []),
        "allowed_tools": [tool.name for tool in tools],
        "limits": dict(run.runtime_limits),
    }
    return [
        AIMessage(
            AIMessageRole.SYSTEM,
            "You are a read-only development analysis specialist. "
            "Inspect only through the listed Tools, never edit files, and return "
            "a JSON object with summary, findings, inspected_resources, "
            "tool_usage_summary, unresolved_items, and artifacts.\n"
            + _bounded_json(context, _MAX_OBSERVATION_BYTES),
        ),
        AIMessage(AIMessageRole.USER, run.objective),
    ]


def _observation(name: str, result: ToolResult) -> dict[str, Any]:
    return {
        "tool": name,
        "status": result.status,
        "value": result.value,
        "error": (
            {"code": result.error.code, "message": result.error.message}
            if result.error
            else None
        ),
    }


def _inspected_resource(name: str, arguments: Mapping[str, Any]) -> str:
    value = arguments.get("path") or arguments.get("workspace") or name
    return str(value)[:512]


def _final_result(
    text: str,
    inspected: list[str],
    usage: Counter[str],
    provider_calls: int,
    tool_calls: int,
    observations: list[dict[str, Any]],
) -> AgentExecutionOutcome:
    try:
        payload = json.loads(text[:_MAX_FINAL_TEXT_BYTES])
    except (TypeError, json.JSONDecodeError):
        payload = {"summary": text[:_MAX_FINAL_TEXT_BYTES]}
    if not isinstance(payload, dict):
        return _failed("INVALID_AGENT_RESULT", "Agent final result must be an object")
    payload.setdefault("summary", "")
    payload.setdefault("findings", [])
    payload.setdefault("inspected_resources", inspected)
    payload.setdefault("tool_usage_summary", dict(usage))
    payload.setdefault("unresolved_items", [])
    payload.setdefault("artifacts", [])
    payload["runtime"] = {
        "provider_calls": provider_calls,
        "tool_calls": tool_calls,
        "observation_count": len(observations),
    }
    return AgentExecutionOutcome(payload)


def _failed(code: str, message: str) -> AgentExecutionOutcome:
    return AgentExecutionOutcome(
        {
            "summary": "Development analysis did not complete",
            "findings": [],
            "inspected_resources": [],
            "tool_usage_summary": {},
            "unresolved_items": [],
            "artifacts": [],
            "error": {"code": code, "message": message},
        },
        succeeded=False,
    )


def _bounded_json(value: Any, limit: int) -> str:
    encoded = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return encoded[:limit]
