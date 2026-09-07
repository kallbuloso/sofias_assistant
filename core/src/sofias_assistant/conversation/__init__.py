"""Core-owned conversation contracts and process-local coordination."""

from sofias_assistant.conversation.coordination import (
    ConversationActivityConflictError,
    ConversationActivityCoordinator,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)

__all__ = [
    "Conversation",
    "ConversationActivityConflictError",
    "ConversationActivityCoordinator",
    "Turn",
    "TurnInputModality",
    "TurnStatus",
]
