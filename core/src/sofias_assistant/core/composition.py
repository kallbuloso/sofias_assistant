"""Small Core-owned seams for conversation runtime composition."""

from collections.abc import Callable
from dataclasses import dataclass

from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.secrets.service import SecretService


@dataclass(frozen=True, slots=True)
class ConversationRuntimeDependencies:
    """AI dependencies supplied to SofiaCore for its conversation runtime."""

    router: CapabilityRouter
    context_builder: ContextBuilder

    def __post_init__(self) -> None:
        if not isinstance(self.router, CapabilityRouter):
            raise ValueError("router must be a CapabilityRouter")
        if not isinstance(self.context_builder, ContextBuilder):
            raise ValueError("context_builder must be a ContextBuilder")


type ConversationDependenciesFactory = Callable[
    [SecretService], ConversationRuntimeDependencies
]
