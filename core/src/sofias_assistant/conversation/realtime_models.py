"""Ephemeral, Core-owned realtime conversation state."""

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from sofias_assistant.ai.contracts import (
    AudioFormat,
    DataLocality,
    ModelIdentity,
    RealtimeInteractionId,
    RealtimeSessionId,
)
from sofias_assistant.conversation.coordination import ConversationActivityLease


class RealtimeSessionState(StrEnum):
    """Small lifecycle for a Core realtime session."""

    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class InteractionGeneration(StrEnum):
    """Internal classification of an interaction ID for one session."""

    ACTIVE = "ACTIVE"
    RETIRED_KNOWN = "RETIRED_KNOWN"
    UNKNOWN = "UNKNOWN"


RETIRED_INTERACTION_LIMIT = 8


@dataclass(slots=True)
class RealtimeInteraction:
    """Ephemeral state for one Core-owned voice interaction."""

    id: RealtimeInteractionId
    lease: ConversationActivityLease
    input_cloud_context_eligible: bool
    response_epoch: int
    next_input_sequence: int = 0
    input_committed: bool = False
    user_transcript_final: str | None = None
    assistant_transcript: str = ""
    assistant_transcript_final: str | None = None
    durable_turn_id: UUID | None = None
    last_provider_sequence: int = -1


@dataclass(slots=True)
class RealtimeSession:
    """Core-owned, non-persistent realtime session distinct from its provider."""

    id: RealtimeSessionId
    conversation_id: UUID
    model: ModelIdentity
    input_audio_format: AudioFormat
    output_audio_format: AudioFormat
    locality: DataLocality
    cloud_context_eligible: bool
    synced_context_revision: int
    state: RealtimeSessionState = RealtimeSessionState.IDLE
    provider_context_stale: bool = False
    active_interaction: RealtimeInteraction | None = None
    provider_session: object | None = field(default=None, repr=False)
    consumer_task: object | None = field(default=None, repr=False)
    event_queue: object | None = field(default=None, repr=False)
    event_consumer_claimed: bool = False
    event_stream_closed: bool = False
    response_epoch: int = 0
    retired_interactions: deque[tuple[RealtimeInteractionId, int]] = field(
        default_factory=deque, repr=False
    )
    retired_interaction_ids: set[RealtimeInteractionId] = field(
        default_factory=set, repr=False
    )

    def next_response_epoch(self) -> int:
        """Allocate exactly one new response generation for an interaction."""

        self.response_epoch += 1
        return self.response_epoch

    def retire_interaction(self, interaction: RealtimeInteraction) -> None:
        """Record one retired interaction in the bounded session history."""

        if interaction.id in self.retired_interaction_ids:
            return
        self.retired_interactions.append((interaction.id, interaction.response_epoch))
        self.retired_interaction_ids.add(interaction.id)
        while len(self.retired_interactions) > RETIRED_INTERACTION_LIMIT:
            retired_id, _ = self.retired_interactions.popleft()
            self.retired_interaction_ids.discard(retired_id)

    def classify_interaction(
        self, interaction_id: RealtimeInteractionId
    ) -> InteractionGeneration:
        """Classify an interaction ID without changing session state."""

        if (
            self.active_interaction is not None
            and self.active_interaction.id == interaction_id
        ):
            return InteractionGeneration.ACTIVE
        if interaction_id in self.retired_interaction_ids:
            return InteractionGeneration.RETIRED_KNOWN
        return InteractionGeneration.UNKNOWN
