"""Ephemeral, Core-owned realtime conversation state."""

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


@dataclass(slots=True)
class RealtimeInteraction:
    """Ephemeral state for one Core-owned voice interaction."""

    id: RealtimeInteractionId
    lease: ConversationActivityLease
    input_cloud_context_eligible: bool
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
