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
    CapabilityProvenance,
    ExecutionLocation,
)
from sofias_assistant.ai.discovery import OpenAIModelDiscoveryAdapter
from sofias_assistant.ai.registry import ProviderBinding
from sofias_assistant.ai_config.models import CapabilityClaim, ProviderConfiguration
from sofias_assistant.ai_config.service import (
    AIConfigurationService,
    CanonicalBootstrap,
)
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
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.secrets.environment_store import (
    EnvironmentSecretStore,
    LayeredSecretStore,
)
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

_OPENAI_ADAPTER_TYPE = "openai"

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


def _openai_provider_binding_factory(
    client_factory: _OpenAIClientFactory | None,
) -> Callable[[ProviderConfiguration, SecretService], ProviderBinding]:
    def build(
        provider: ProviderConfiguration, secret_service: SecretService
    ) -> ProviderBinding:
        adapter = OpenAIProviderAdapter(
            secret_service=secret_service,
            api_key_ref=provider_api_key_ref(provider.id),
            client_factory=client_factory,
            base_url=provider.base_url,
        )
        return ProviderBinding(
            text_generation=adapter,
            text_streaming=adapter,
            structured_output=adapter,
            vision=adapter,
            realtime=adapter,
        )

    return build


def _openai_discovery_adapter_factory(
    client_factory: _OpenAIClientFactory | None,
) -> Callable[[ProviderConfiguration, SecretService], OpenAIModelDiscoveryAdapter]:
    def build(
        provider: ProviderConfiguration, secret_service: SecretService
    ) -> OpenAIModelDiscoveryAdapter:
        factory = client_factory or (lambda api_key: _default_openai_client(api_key))

        def bound_client_factory() -> Any:
            secret = secret_service.get(provider_api_key_ref(provider.id))
            if secret is None:
                raise RuntimeError("OpenAI credential is not configured")
            return factory(secret.reveal())

        return OpenAIModelDiscoveryAdapter(client_factory=bound_client_factory)

    return build


def _default_openai_client(api_key: str) -> Any:
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key, max_retries=0, timeout=30.0)


def build_conversation_dependencies_factory(
    llm: LLMProviderConfig,
    *,
    client_factory: _OpenAIClientFactory | None = None,
) -> ConversationDependenciesFactory:
    """Build the canonical/default OpenAI production composition (Gate I15).

    Only capabilities the adapter can actually demonstrate for the canonical
    bootstrap model are declared as `BUILTIN_METADATA`: `TEXT_GENERATION` and
    `TEXT_STREAMING`. Persistent `ProviderConfiguration`/`ModelCatalogEntry`
    are seeded idempotently through `AIConfigurationService`; routing for
    `chat.general`/`realtime` resolves dynamically against the published
    `RoutingSnapshot` instead of a single hardcoded in-memory registration.
    """

    def factory(
        secret_service: Any, uow_factory: Callable[[], SqlAlchemyUnitOfWork]
    ) -> ConversationRuntimeDependencies:
        ai_configuration_service = AIConfigurationService(
            uow_factory=uow_factory,
            secret_service=secret_service,
            provider_binding_factories={
                _OPENAI_ADAPTER_TYPE: _openai_provider_binding_factory(client_factory)
            },
            discovery_adapter_factories={
                _OPENAI_ADAPTER_TYPE: _openai_discovery_adapter_factory(client_factory)
            },
        )
        canonical = CanonicalBootstrap(
            provider_id=llm.provider_id,
            display_name=llm.provider_id.title(),
            adapter_type=_OPENAI_ADAPTER_TYPE,
            base_url=llm.base_url,
            execution_location=ExecutionLocation.CLOUD,
            credential_ref=provider_api_key_ref(llm.provider_id),
            model_id=llm.model_id,
            model_display_name=llm.model_id,
            capabilities=frozenset(
                {
                    CapabilityClaim(
                        Capability.TEXT_GENERATION,
                        CapabilityProvenance.BUILTIN_METADATA,
                    ),
                    CapabilityClaim(
                        Capability.TEXT_STREAMING, CapabilityProvenance.BUILTIN_METADATA
                    ),
                }
            ),
        )
        return ConversationRuntimeDependencies(
            router=ai_configuration_service.routing_policy_for("chat.general"),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext(_SYSTEM_CONTEXT_TEXT, True),
                max_recent_turns=_DEFAULT_MAX_RECENT_TURNS,
                max_estimated_input_tokens=_DEFAULT_MAX_ESTIMATED_INPUT_TOKENS,
            ),
            realtime_router=ai_configuration_service.routing_policy_for("realtime"),
            ai_configuration_service=ai_configuration_service,
            ai_configuration_bootstrap=canonical,
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
            ai_configuration=core.ai_configuration_service,
        )

    return app_factory
