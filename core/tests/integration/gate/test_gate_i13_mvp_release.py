"""Gate I13 — MVP Ready: release-acceptance suite for the Sofia's Assistant MVP.

This suite is the release-acceptance executable for SA-B034. It does not
duplicate the deep coverage already proven by earlier Gates; it references
that coverage explicitly and adds new verticals only where Slice 08 found a
genuine product gap (Scenario F — Web Research, Scenario J — Provider
Routing), plus one product-level SofiaCore composition smoke.

Scenario coverage map (A-J from the Technical Backlog Map):

  A - Text Conversation : new vertical below (test_scenario_a_*) + deep
                          coverage in test_gate_i2_conversation.py.
  B - Realtime Voice    : covered by test_gate_i3_realtime_boundary.py (real
                          SofiaCore WS/HTTP loopback, barge-in, interruption,
                          session loss/reopen). No new vertical is needed for
                          release readiness; a fake, deterministic realtime
                          provider is already release-acceptable evidence.
  C - Memory            : covered by test_gate_i6_memory.py, especially
                          vertical_a (remember -> cross-conversation recall)
                          and vertical_h (recall outage degrades but the
                          conversation still works). The live Sofias Memory
                          smoke from Slice 05 remains valid historical
                          evidence because this Gate does not change that
                          boundary.
  D - Filesystem        : covered by test_gate_i8_capabilities.py (Tool
                          Registry, Policy, Grant, path canonicalization,
                          traversal protection, Audit).
  E - Shell             : covered by test_gate_i8_capabilities.py (argv-only
                          execution, filtered environment, timeout, bounded
                          output) plus test_gate_i12_recovery.py (interrupted
                          subprocess recovery semantics).
  F - Web Research      : NEW vertical below (test_scenario_f_*) — the
                          genuine product gap, closed by
                          sofias_assistant.execution.research.ResearchAgent.
  G - Reminder          : new restart-survival vertical folded into
                          test_sofia_core_integrated_smoke below, plus deep
                          coverage in test_gate_i7_proactivity.py.
  H - Agent             : covered by test_gate_i9_development_analysis.py
                          (root-created AgentRun, narrowed context/tools/
                          authority, bounded result, Audit). The Scenario F
                          ResearchAgent exercises the exact same narrowing
                          machinery for a second specialization.
  I - Recovery          : covered by test_gate_i12_recovery.py plus the
                          SofiaCore-level crash/restart proof in
                          tests/integration/core/test_core.py::
                          test_general_recovery_leaves_scheduled_task_to_specialized_recovery.
  J - Provider Routing  : NEW vertical below (test_scenario_j_*).

Plus one SofiaCore integrated smoke (test_sofia_core_integrated_smoke)
proving product-level composition: create -> start -> authenticated
interaction (text conversation) -> durable reminder -> stop -> restart ->
durable state survives -> stop, over a temporary data directory only.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.ai import (
    AIRequest,
    Capability,
    CapabilityRouter,
    DataLocality,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.contracts import ToolCallProposal
from sofias_assistant.ai.fake import FakeAgentProvider
from sofias_assistant.capabilities.web import WebReader
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.conversation.models import TurnStatus
from sofias_assistant.conversation.runtime import SendTextCommand
from sofias_assistant.core import ConversationRuntimeDependencies, CoreState, SofiaCore
from sofias_assistant.execution import (
    AgentRuntime,
    AuthorityContext,
    ExecutionRuntime,
    GrantLifetime,
    TaskRuntime,
    register_research,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.proactivity.models import FakeClock
from sofias_assistant.runtime.bootstrap import operational_database_url

from ...support.ai import FakeTextSuccess, ScriptedFakeProvider


def _text_dependencies_factory(provider: ScriptedFakeProvider):
    def factory(
        _secret_service: Any, _uow_factory: Any
    ) -> ConversationRuntimeDependencies:
        registry = ModelRegistry()
        registry.register(
            ModelRegistration(
                descriptor=ModelDescriptor(
                    identity=ModelIdentity("fake", "mvp-release"),
                    capabilities=frozenset({Capability.TEXT_GENERATION}),
                    execution_location=ExecutionLocation.LOCAL,
                    context_window=4096,
                ),
                binding=ProviderBinding(text_generation=provider),
            )
        )
        return ConversationRuntimeDependencies(
            router=CapabilityRouter(registry),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext("Core system context", True),
                max_recent_turns=4,
                max_estimated_input_tokens=10_000,
            ),
        )

    return factory


# ---------------------------------------------------------------------------
# Scenario A — Text Conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_a_text_conversation_is_durable_and_authoritative(
    tmp_path: Path,
) -> None:
    """Client -> Conversation -> Turn -> ContextBuilder -> provider -> durable Turn.

    Deep protocol/adversarial coverage lives in test_gate_i2_conversation.py;
    this proves the same path composes through a real SofiaCore instance.
    """

    from tests.integration.core.test_core import (
        FakeSecretStore,
        fake_ownership_factory,
        runtime_config,
    )

    provider = ScriptedFakeProvider(
        text_scripts=[FakeTextSuccess(text="Ola! Como posso ajudar?")]
    )
    core = SofiaCore(
        runtime_config(tmp_path),
        application_version="0.1.0",
        secret_store_factory=FakeSecretStore,
        instance_ownership_factory=fake_ownership_factory,
        conversation_dependencies_factory=_text_dependencies_factory(provider),
    )
    await core.start()
    try:
        conversation = await core.conversation_runtime.create_conversation()
        result = await core.conversation_runtime.send_text(
            SendTextCommand(
                conversation_id=conversation.id,
                text="Oi Sofia",
                locality=DataLocality.LOCAL_ONLY,
                cloud_context_eligible=False,
            )
        )
        assert result.turn.status is TurnStatus.COMPLETED
        assert result.turn.assistant_text == "Ola! Como posso ajudar?"

        state = await core.conversation_runtime.get_conversation_state(conversation.id)
        assert state.conversation.id == conversation.id
        assert [turn.id for turn in state.turns] == [result.turn.id]
    finally:
        await core.stop()


# ---------------------------------------------------------------------------
# Scenario J — Provider Routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_j_capability_locality_selects_different_provider_bindings(
    tmp_path: Path,
) -> None:
    """Same Sofia identity/Conversation; locality alone changes the provider binding.

    Provider/model identity is purely an execution choice made by the real
    CapabilityRouter/ModelRegistry, never part of the Sofia/Conversation
    identity itself.
    """

    from tests.integration.core.test_core import (
        FakeSecretStore,
        fake_ownership_factory,
        runtime_config,
    )

    local_provider = ScriptedFakeProvider(
        text_scripts=[FakeTextSuccess(text="respondido localmente")]
    )
    cloud_provider = ScriptedFakeProvider(
        text_scripts=[FakeTextSuccess(text="respondido na nuvem")]
    )

    def factory(
        _secret_service: Any, _uow_factory: Any
    ) -> ConversationRuntimeDependencies:
        registry = ModelRegistry()
        registry.register(
            ModelRegistration(
                descriptor=ModelDescriptor(
                    identity=ModelIdentity("fake-local", "text-local"),
                    capabilities=frozenset({Capability.TEXT_GENERATION}),
                    execution_location=ExecutionLocation.LOCAL,
                ),
                binding=ProviderBinding(text_generation=local_provider),
            )
        )
        registry.register(
            ModelRegistration(
                descriptor=ModelDescriptor(
                    identity=ModelIdentity("fake-cloud", "text-cloud"),
                    capabilities=frozenset({Capability.TEXT_GENERATION}),
                    execution_location=ExecutionLocation.CLOUD,
                ),
                binding=ProviderBinding(text_generation=cloud_provider),
            )
        )
        return ConversationRuntimeDependencies(
            router=CapabilityRouter(registry),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext("Core system context", True),
                max_recent_turns=4,
                max_estimated_input_tokens=10_000,
            ),
        )

    core = SofiaCore(
        runtime_config(tmp_path),
        application_version="0.1.0",
        secret_store_factory=FakeSecretStore,
        instance_ownership_factory=fake_ownership_factory,
        conversation_dependencies_factory=factory,
    )
    await core.start()
    try:
        conversation = await core.conversation_runtime.create_conversation()

        local_result = await core.conversation_runtime.send_text(
            SendTextCommand(
                conversation_id=conversation.id,
                text="responda localmente",
                locality=DataLocality.LOCAL_ONLY,
                cloud_context_eligible=False,
            )
        )
        cloud_result = await core.conversation_runtime.send_text(
            SendTextCommand(
                conversation_id=conversation.id,
                text="responda na nuvem",
                locality=DataLocality.CLOUD_PREFERRED,
                cloud_context_eligible=True,
            )
        )

        # Same Sofia / same Conversation identity throughout.
        assert local_result.conversation.id == conversation.id
        assert cloud_result.conversation.id == conversation.id

        # Provider/model binding is purely an execution choice driven by locality.
        assert local_result.turn.provider_id == "fake-local"
        assert local_result.turn.model_id == "text-local"
        assert local_result.turn.assistant_text == "respondido localmente"
        assert cloud_result.turn.provider_id == "fake-cloud"
        assert cloud_result.turn.model_id == "text-cloud"
        assert cloud_result.turn.assistant_text == "respondido na nuvem"
    finally:
        await core.stop()


# ---------------------------------------------------------------------------
# Scenario F — Web Research (Search + >=2 distinct sources + bounded synthesis)
# ---------------------------------------------------------------------------


class _ResearchWebHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/source-a":
            self._respond(
                200,
                "text/plain",
                b"Sofia's Assistant ships a bounded multi-source research vertical.",
            )
            return
        if self.path == "/source-b":
            self._respond(
                200,
                "text/plain",
                b"Attribution is preserved through runtime-observed source URLs.",
            )
            return
        if self.path == "/broken":
            # An unreadable content type: WebReader rejects it, so this
            # source deterministically fails without needing a dropped
            # connection.
            self._respond(200, "application/octet-stream", b"\x00\x01binary")
            return
        self.send_response(404)
        self.end_headers()

    def _respond(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


async def _execution_with_web(tmp_path: Path) -> tuple[ExecutionRuntime, AsyncEngine]:
    database = tmp_path / "operational.sqlite"
    import asyncio

    await asyncio.to_thread(upgrade_to_head, operational_database_url(database))
    engine = create_async_engine(operational_database_url(database))
    execution = ExecutionRuntime(
        create_session_factory(engine), artifact_root=tmp_path / "artifacts"
    )
    for spec in WebReader(allow_loopback=True).specs():
        execution.register_tool(spec)
    return execution, engine


def _research_router(provider: FakeAgentProvider) -> CapabilityRouter:
    registry = ModelRegistry()
    registry.register(
        ModelRegistration(
            descriptor=ModelDescriptor(
                identity=ModelIdentity("fake-research", "synthesis"),
                capabilities=frozenset(
                    {Capability.TEXT_GENERATION, Capability.TOOL_CALLING}
                ),
                execution_location=ExecutionLocation.LOCAL,
            ),
            binding=ProviderBinding(text_generation=provider),
        )
    )
    return CapabilityRouter(registry)


class _ResearchServer:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ResearchWebHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}"

    def __exit__(self, *exc_info: object) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.asyncio
async def test_scenario_f_multi_source_research_synthesizes_with_attribution(
    tmp_path: Path,
) -> None:
    """NEW Gate I13 vertical closing the Web Research product gap.

    research query -> web.search -> reads >=2 distinct sources -> bounded
    evidence -> provider synthesis -> result carries runtime-observed source
    attribution, all through the real AgentRuntime/ExecutionRuntime/Policy/
    Audit seams (no direct Tool implementation calls).
    """

    execution, engine = await _execution_with_web(tmp_path)
    with _ResearchServer() as base:
        url_a, url_b = f"{base}/source-a", f"{base}/source-b"
        query = "sofia assistant bounded web research vertical"
        subject = "Sofia/root"
        task_runtime = TaskRuntime(execution)
        try:

            def decide(
                request: AIRequest, turn: int
            ) -> tuple[str, tuple[ToolCallProposal, ...]]:
                if turn == 1:
                    return "", (
                        ToolCallProposal(
                            "s1", "web.search", {"query": query, "max_results": 5}
                        ),
                    )
                if turn == 2:
                    return "", (ToolCallProposal("r1", "web.read", {"url": url_a}),)
                if turn == 3:
                    return "", (ToolCallProposal("r2", "web.read", {"url": url_b}),)
                return (
                    json.dumps(
                        {
                            "summary": "Both sources confirm the bounded research "
                            "vertical exists and preserves attribution.",
                            "findings": [
                                {
                                    "claim": "multi-source research vertical",
                                    "source": url_a,
                                },
                                {"claim": "attribution preserved", "source": url_b},
                            ],
                        }
                    ),
                    (),
                )

            provider = FakeAgentProvider(decide)
            agent_runtime = AgentRuntime(execution)
            definition = await register_research(
                agent_runtime, _research_router(provider)
            )
            task = await task_runtime.create_agent_task(
                objective=query, subject=subject, authority=AuthorityContext(subject)
            )
            search_grant = await execution.create_grant(
                subject=subject,
                capability="web.search",
                resource_scope=f"web.search:{query}",
                lifetime=GrantLifetime.UNTIL_REVOKED,
            )
            read_grant = await execution.create_grant(
                subject=subject,
                capability="web.read",
                resource_scope=f"{base}/*",
                lifetime=GrantLifetime.UNTIL_REVOKED,
            )
            run = await agent_runtime.create_agent_run(
                root_authority=agent_runtime.root_authority,
                task=task,
                definition=definition,
                delegated_context={"objective": query, "constraints": ["bounded"]},
                authority=AuthorityContext(subject),
            )
            completed = await agent_runtime.run(
                run,
                AuthorityContext(subject),
                grants={"web.search": search_grant.id, "web.read": read_grant.id},
            )

            assert completed.status.value == "SUCCEEDED"
            assert sorted(completed.result["sources"]) == sorted([url_a, url_b])
            assert completed.result["summary"]

            trace = await execution.audit.query(agent_run_id=completed.id)
            assert {entry.event_type for entry in trace} >= {
                "AGENT_RUN_CREATED",
                "AGENT_RUN_STARTED",
                "AGENT_PROVIDER_INFERENCE",
                "TOOL_CALL_REQUESTED",
                "POLICY_DECISION",
                "TOOL_EXECUTION_COMPLETED",
                "AGENT_RUN_COMPLETED",
            }
        finally:
            await task_runtime.stop()
            await engine.dispose()


@pytest.mark.asyncio
async def test_scenario_f_insufficient_sources_reports_explicit_degraded_failure(
    tmp_path: Path,
) -> None:
    """One source fails; a provider that claims success anyway is not trusted.

    Below the minimum distinct-source threshold, the Agent must fail
    explicitly (INSUFFICIENT_SOURCES) instead of fabricating attribution for
    content it never actually read.
    """

    execution, engine = await _execution_with_web(tmp_path)
    with _ResearchServer() as base:
        url_ok, url_broken = f"{base}/source-a", f"{base}/broken"
        query = "sofia assistant degraded research case"
        subject = "Sofia/root"
        task_runtime = TaskRuntime(execution)
        try:

            def decide(
                request: AIRequest, turn: int
            ) -> tuple[str, tuple[ToolCallProposal, ...]]:
                if turn == 1:
                    return "", (
                        ToolCallProposal(
                            "s1", "web.search", {"query": query, "max_results": 5}
                        ),
                    )
                if turn == 2:
                    return "", (ToolCallProposal("r1", "web.read", {"url": url_ok}),)
                if turn == 3:
                    return "", (
                        ToolCallProposal("r2", "web.read", {"url": url_broken}),
                    )
                return (
                    json.dumps(
                        {
                            "summary": "Confirmed by two independent sources.",
                            "sources": [url_ok, url_broken],
                        }
                    ),
                    (),
                )

            provider = FakeAgentProvider(decide)
            agent_runtime = AgentRuntime(execution)
            definition = await register_research(
                agent_runtime, _research_router(provider)
            )
            task = await task_runtime.create_agent_task(
                objective=query, subject=subject, authority=AuthorityContext(subject)
            )
            search_grant = await execution.create_grant(
                subject=subject,
                capability="web.search",
                resource_scope=f"web.search:{query}",
                lifetime=GrantLifetime.UNTIL_REVOKED,
            )
            read_grant = await execution.create_grant(
                subject=subject,
                capability="web.read",
                resource_scope=f"{base}/*",
                lifetime=GrantLifetime.UNTIL_REVOKED,
            )
            run = await agent_runtime.create_agent_run(
                root_authority=agent_runtime.root_authority,
                task=task,
                definition=definition,
                delegated_context={"objective": query},
                authority=AuthorityContext(subject),
            )
            completed = await agent_runtime.run(
                run,
                AuthorityContext(subject),
                grants={"web.search": search_grant.id, "web.read": read_grant.id},
            )

            assert completed.status.value == "FAILED"
            assert completed.result["error"]["code"] == "INSUFFICIENT_SOURCES"
            # The provider's claimed second source is never fabricated into
            # the runtime-observed attribution list.
            assert completed.result["sources"] == [url_ok]
        finally:
            await task_runtime.stop()
            await engine.dispose()


# ---------------------------------------------------------------------------
# SofiaCore integrated smoke (Scenario A + Scenario G restart-survival)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sofia_core_integrated_smoke(tmp_path: Path) -> None:
    """Product-level composition smoke: create, start, interact, stop, restart.

    Uses a temporary data directory only. Proves that a text Conversation and
    a Reminder created against one SofiaCore process remain durable and
    correctly reconciled after a full stop/restart against the same
    on-disk state (Scenario G's restart-survival requirement); deep
    Scheduler/Notification coverage lives in test_gate_i7_proactivity.py.
    """

    from tests.integration.core.test_core import (
        FakeSecretStore,
        fake_ownership_factory,
        runtime_config,
    )
    from tests.integration.gate.test_gate_i7_proactivity import reminder

    config = runtime_config(tmp_path)
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))
    provider = ScriptedFakeProvider(
        text_scripts=[FakeTextSuccess(text="Ola, sou a Sofia.")]
    )

    def core() -> SofiaCore:
        return SofiaCore(
            config,
            application_version="0.1.0",
            secret_store_factory=FakeSecretStore,
            instance_ownership_factory=fake_ownership_factory,
            conversation_dependencies_factory=_text_dependencies_factory(provider),
            clock=clock,
        )

    first = core()
    await first.start()
    assert first.state is CoreState.RUNNING
    conversation = await first.conversation_runtime.create_conversation()
    turn_result = await first.conversation_runtime.send_text(
        SendTextCommand(
            conversation_id=conversation.id,
            text="Oi Sofia, tudo bem?",
            locality=DataLocality.LOCAL_ONLY,
            cloud_context_eligible=False,
        )
    )
    assert turn_result.turn.status is TurnStatus.COMPLETED
    schedule = await reminder(first.proactivity, clock)
    await first.stop()
    assert first.state is CoreState.STOPPED

    clock.advance(timedelta(days=1))
    second = core()
    await second.start()
    try:
        assert second.state is CoreState.RUNNING

        state = await second.conversation_runtime.get_conversation_state(
            conversation.id
        )
        assert state.conversation.id == conversation.id
        assert state.turns[0].assistant_text == "Ola, sou a Sofia."

        notes = await second.proactivity.notifications.pending()
        assert len(notes) == 1
        assert notes[0].action_reference == schedule.id

        assert {component.name for component in second.health.components} >= {
            "recovery",
            "scheduler",
            "notifications",
            "event-runtime",
        }
    finally:
        await second.stop()
        assert second.state is CoreState.STOPPED
