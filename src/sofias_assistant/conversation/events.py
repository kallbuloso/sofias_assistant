"""Immutable Core-owned events for one normalized text stream."""

from dataclasses import dataclass
from uuid import UUID

from sofias_assistant.ai.contracts import ModelIdentity, ToolCallProposal, UsageMetadata
from sofias_assistant.conversation.models import Conversation, Turn, TurnStatus


def _require_correlation(
    conversation_id: UUID, turn_id: UUID, ai_request_id: UUID, model: ModelIdentity
) -> None:
    if not all(
        isinstance(value, UUID) for value in (conversation_id, turn_id, ai_request_id)
    ):
        raise ValueError("stream correlation IDs must be UUIDs")
    if not isinstance(model, ModelIdentity):
        raise ValueError("model must be a ModelIdentity")


@dataclass(frozen=True, slots=True)
class ConversationTurnStarted:
    """A durably committed processing turn is ready for streaming inference."""

    conversation: Conversation
    turn: Turn

    def __post_init__(self) -> None:
        if not isinstance(self.conversation, Conversation) or not isinstance(
            self.turn, Turn
        ):
            raise ValueError("conversation and turn must be conversation snapshots")
        if self.turn.status is not TurnStatus.PROCESSING:
            raise ValueError("started event requires a processing turn")
        if self.conversation.id != self.turn.conversation_id:
            raise ValueError("conversation and turn must belong together")


@dataclass(frozen=True, slots=True)
class ConversationTextDelta:
    """One ordered, ephemeral text fragment from a validated provider stream."""

    conversation_id: UUID
    turn_id: UUID
    ai_request_id: UUID
    model: ModelIdentity
    text: str

    def __post_init__(self) -> None:
        _require_correlation(
            self.conversation_id, self.turn_id, self.ai_request_id, self.model
        )
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")


@dataclass(frozen=True, slots=True)
class ConversationUsageUpdated:
    """Ephemeral usage metadata from a validated provider stream."""

    conversation_id: UUID
    turn_id: UUID
    ai_request_id: UUID
    model: ModelIdentity
    usage: UsageMetadata

    def __post_init__(self) -> None:
        _require_correlation(
            self.conversation_id, self.turn_id, self.ai_request_id, self.model
        )
        if not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata")


@dataclass(frozen=True, slots=True)
class ConversationToolCallProposed:
    """An inert normalized proposal that grants no Tool execution authority."""

    conversation_id: UUID
    turn_id: UUID
    ai_request_id: UUID
    model: ModelIdentity
    proposal: ToolCallProposal

    def __post_init__(self) -> None:
        _require_correlation(
            self.conversation_id, self.turn_id, self.ai_request_id, self.model
        )
        if not isinstance(self.proposal, ToolCallProposal):
            raise ValueError("proposal must be a ToolCallProposal")


@dataclass(frozen=True, slots=True)
class ConversationTurnCompleted:
    """A durably committed successful terminal stream result."""

    conversation: Conversation
    turn: Turn
    usage: UsageMetadata | None = None

    def __post_init__(self) -> None:
        _require_terminal(self.conversation, self.turn, TurnStatus.COMPLETED)
        if self.usage is not None and not isinstance(self.usage, UsageMetadata):
            raise ValueError("usage must be UsageMetadata when provided")


@dataclass(frozen=True, slots=True)
class ConversationTurnFailed:
    """A durably committed failed terminal stream result."""

    conversation: Conversation
    turn: Turn

    def __post_init__(self) -> None:
        _require_terminal(self.conversation, self.turn, TurnStatus.FAILED)


@dataclass(frozen=True, slots=True)
class ConversationTurnInterrupted:
    """A durably committed interrupted terminal stream result."""

    conversation: Conversation
    turn: Turn

    def __post_init__(self) -> None:
        _require_terminal(self.conversation, self.turn, TurnStatus.INTERRUPTED)


def _require_terminal(
    conversation: Conversation, turn: Turn, status: TurnStatus
) -> None:
    if not isinstance(conversation, Conversation) or not isinstance(turn, Turn):
        raise ValueError("conversation and turn must be conversation snapshots")
    if conversation.id != turn.conversation_id:
        raise ValueError("conversation and turn must belong together")
    if turn.status is not status:
        raise ValueError(f"terminal event requires a {status.value} turn")


type ConversationStreamEvent = (
    ConversationTurnStarted
    | ConversationTextDelta
    | ConversationUsageUpdated
    | ConversationToolCallProposed
    | ConversationTurnCompleted
    | ConversationTurnFailed
    | ConversationTurnInterrupted
)
