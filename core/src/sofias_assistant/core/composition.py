"""Small Core-owned seams for conversation runtime composition."""

from collections.abc import Callable
from dataclasses import dataclass

from sofias_assistant.ai.routing_policy import Router
from sofias_assistant.ai_config.service import (
    AIConfigurationService,
    CanonicalBootstrap,
)
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.memory.contracts import MemoryProvider
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.secrets.service import SecretService


@dataclass(frozen=True, slots=True)
class ConversationRuntimeDependencies:
    """AI dependencies supplied to SofiaCore for its conversation runtime.

    `router` is typically profile-bound (`RoutingPolicy` for `chat.general`)
    in production, but any `Router`-shaped object works, so unit tests may
    keep injecting a bare `CapabilityRouter` unchanged. `realtime_router`
    defaults to `router` when omitted, preserving the single-router Gate I14
    behavior. `ai_configuration_service` is optional and only present once
    Gate I15 persistence/routing is composed; it is exposed by `SofiaCore`
    for the authenticated AI Configuration API.
    """

    router: Router
    context_builder: ContextBuilder
    realtime_router: Router | None = None
    ai_configuration_service: AIConfigurationService | None = None
    ai_configuration_bootstrap: CanonicalBootstrap | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.router, Router):
            raise ValueError("router must be Router-shaped (a route(...) method)")
        if self.realtime_router is not None and not isinstance(
            self.realtime_router, Router
        ):
            raise ValueError("realtime_router must be Router-shaped when provided")
        if not isinstance(self.context_builder, ContextBuilder):
            raise ValueError("context_builder must be a ContextBuilder")


type ConversationDependenciesFactory = Callable[
    [SecretService, Callable[[], SqlAlchemyUnitOfWork]], ConversationRuntimeDependencies
]

type MemoryProviderFactory = Callable[[SecretService], MemoryProvider]
