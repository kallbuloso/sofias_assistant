"""Production composition root for the standalone Sofia Core host.

Materializes exactly the flow required by Slice 09 SA-B035:

    provider configuration -> Adapter -> ProviderBinding -> ModelRegistration
    -> CapabilityRouter

and the secret flow required by Amendment 0003 SS5:

    process environment / explicit env file / platform SecretStore
        -> secret source bridge -> SecretService -> Provider Adapter

Nothing here performs inference or contains Conversation/Memory domain
logic; it only wires already-accepted Core seams (`SofiaCore`'s injectable
`secret_store_factory` and `conversation_dependencies_factory`,
`LocalClientBoundary`'s injectable `app_factory`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI

from sofias_assistant.ai.adapters.openai import OpenAIProviderAdapter
from sofias_assistant.ai.contracts import (
    Capability,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
)
from sofias_assistant.ai.registry import (
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.client_boundary.auth import LocalClientAuthenticator
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.client_boundary.sessions import ClientSessionRegistry
from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.core.composition import (
    ConversationDependenciesFactory,
    ConversationRuntimeDependencies,
)
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.host.config import LLMProviderConfig, ProductionRuntimeConfig
from sofias_assistant.host.secret_bridge import (
    bootstrap_secret_mappings,
    provider_api_key_ref,
)
from sofias_assistant.secrets.environment_store import (
    EnvironmentSecretStore,
    LayeredSecretStore,
)
from sofias_assistant.secrets.store import SecretStore
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

_SYSTEM_CONTEXT_TEXT = (
    "You are Sofia, a persistent, local-first personal AI assistant. Provider "
    "and model are execution mechanisms only; they are never your identity."
)
_DEFAULT_MAX_RECENT_TURNS = 20
_DEFAULT_MAX_ESTIMATED_INPUT_TOKENS = 12_000

_OpenAIClientFactory = Callable[[str], Any]


def build_runtime_config(config: ProductionRuntimeConfig) -> RuntimeConfig:
    """Map production bootstrap configuration to the Core's `RuntimeConfig`."""

    return RuntimeConfig(paths=AppPaths(data_dir=config.data_dir), memory=config.memory)


def build_secret_store_factory(
    *,
    environment: Mapping[str, str],
    llm_provider_id: str,
    platform_secret_store_factory: Callable[[], SecretStore] = WindowsCredentialStore,
) -> Callable[[], SecretStore]:
    """Build the layered SecretStore factory required by Amendment 0003 SS5-SS6."""

    mappings = bootstrap_secret_mappings(llm_provider_id=llm_provider_id)
    environment_store = EnvironmentSecretStore(environment, mappings)

    def factory() -> SecretStore:
        return LayeredSecretStore(environment_store, platform_secret_store_factory())

    return factory


def build_conversation_dependencies_factory(
    llm: LLMProviderConfig,
    *,
    client_factory: _OpenAIClientFactory | None = None,
) -> ConversationDependenciesFactory:
    """Build the canonical/default OpenAI production composition (SA-B035 SS11).

    Only capabilities the adapter can actually demonstrate for the
    configured workload are declared: `TEXT_GENERATION` (non-streaming Turn
    completion) and `TEXT_STREAMING` (the streamed Turn endpoint). Tool
    calling, vision, structured output and realtime are deliberately not
    claimed here; Gate I15 owns discovered/declared capability provenance.
    """

    def factory(secret_service: Any) -> ConversationRuntimeDependencies:
        adapter = OpenAIProviderAdapter(
            secret_service=secret_service,
            api_key_ref=provider_api_key_ref(llm.provider_id),
            client_factory=client_factory,
        )
        registry = ModelRegistry()
        registry.register(
            ModelRegistration(
                descriptor=ModelDescriptor(
                    identity=ModelIdentity(llm.provider_id, llm.model_id),
                    capabilities=frozenset(
                        {Capability.TEXT_GENERATION, Capability.TEXT_STREAMING}
                    ),
                    execution_location=ExecutionLocation.CLOUD,
                ),
                binding=ProviderBinding(
                    text_generation=adapter, text_streaming=adapter
                ),
            )
        )
        return ConversationRuntimeDependencies(
            router=CapabilityRouter(registry),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext(_SYSTEM_CONTEXT_TEXT, True),
                max_recent_turns=_DEFAULT_MAX_RECENT_TURNS,
                max_estimated_input_tokens=_DEFAULT_MAX_ESTIMATED_INPUT_TOKENS,
            ),
        )

    return factory


def create_app_factory(
    core: SofiaCore,
) -> Callable[[LocalClientAuthenticator, ClientSessionRegistry], FastAPI]:
    """Wire every Core-owned service the authenticated boundary may expose.

    Only called by `LocalClientBoundary.start()`, which always runs after
    `SofiaCore.start()` in the production lifecycle, so the Core-owned
    properties below are guaranteed to be available.
    """

    def app_factory(
        authenticator: LocalClientAuthenticator, sessions: ClientSessionRegistry
    ) -> FastAPI:
        return create_local_http_app(
            authenticator,
            sessions,
            core=core,
            conversation=core.conversation_runtime,
            realtime=core.realtime_conversation_runtime,
            execution=core.execution_runtime,
            tasks=core.task_runtime,
            proactivity=core.proactivity,
            memory=core.memory_orchestrator,
        )

    return app_factory
