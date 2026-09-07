"""Core-owned application events for an ephemeral realtime conversation session."""

from dataclasses import dataclass
from uuid import UUID

from sofias_assistant.ai.contracts import (
    AudioFormat,
    ModelIdentity,
    RealtimeInteractionId,
    RealtimeSessionId,
)
from sofias_assistant.conversation.events import (
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
)


def _ids(session_id: RealtimeSessionId, interaction_id: RealtimeInteractionId) -> None:
    if not isinstance(session_id, UUID) or not isinstance(interaction_id, UUID):
        raise ValueError("realtime correlation IDs must be UUIDs")


@dataclass(frozen=True, slots=True)
class RealtimeSessionOpened:
    realtime_session_id: RealtimeSessionId
    conversation_id: UUID
    model: ModelIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.realtime_session_id, UUID) or not isinstance(
            self.conversation_id, UUID
        ):
            raise ValueError("realtime session and conversation IDs must be UUIDs")


@dataclass(frozen=True, slots=True)
class RealtimeInteractionStarted:
    realtime_session_id: RealtimeSessionId
    realtime_interaction_id: RealtimeInteractionId

    def __post_init__(self) -> None:
        _ids(self.realtime_session_id, self.realtime_interaction_id)


@dataclass(frozen=True, slots=True)
class _RealtimeInteractionText:
    realtime_session_id: RealtimeSessionId
    realtime_interaction_id: RealtimeInteractionId
    sequence: int
    text: str

    def __post_init__(self) -> None:
        _ids(self.realtime_session_id, self.realtime_interaction_id)
        if (
            not isinstance(self.sequence, int)
            or self.sequence < 0
            or not isinstance(self.text, str)
        ):
            raise ValueError("realtime text event is invalid")


class RealtimeUserTranscriptPartial(_RealtimeInteractionText):
    pass


class RealtimeUserTranscriptFinal(_RealtimeInteractionText):
    pass


class RealtimeAssistantTranscriptPartial(_RealtimeInteractionText):
    pass


class RealtimeAssistantTranscriptFinal(_RealtimeInteractionText):
    pass


@dataclass(frozen=True, slots=True)
class RealtimeAssistantAudioChunk:
    realtime_session_id: RealtimeSessionId
    realtime_interaction_id: RealtimeInteractionId
    sequence: int
    audio: bytes
    audio_format: AudioFormat

    def __post_init__(self) -> None:
        _ids(self.realtime_session_id, self.realtime_interaction_id)
        if (
            not isinstance(self.sequence, int)
            or self.sequence < 0
            or not isinstance(self.audio, bytes)
            or not self.audio
        ):
            raise ValueError("realtime audio event is invalid")
        if not isinstance(self.audio_format, AudioFormat):
            raise ValueError("audio_format must be AudioFormat")


@dataclass(frozen=True, slots=True)
class RealtimeInteractionFailed:
    realtime_session_id: RealtimeSessionId
    realtime_interaction_id: RealtimeInteractionId
    safe_message: str

    def __post_init__(self) -> None:
        _ids(self.realtime_session_id, self.realtime_interaction_id)
        if not self.safe_message.strip():
            raise ValueError("safe_message must not be blank")


@dataclass(frozen=True, slots=True)
class ConversationRealtimeSessionFailed:
    realtime_session_id: RealtimeSessionId
    safe_message: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.realtime_session_id, UUID)
            or not self.safe_message.strip()
        ):
            raise ValueError("realtime session failure is invalid")


@dataclass(frozen=True, slots=True)
class RealtimeSessionClosed:
    realtime_session_id: RealtimeSessionId

    def __post_init__(self) -> None:
        if not isinstance(self.realtime_session_id, UUID):
            raise ValueError("realtime_session_id must be UUID")


type RealtimeConversationEvent = (
    RealtimeSessionOpened
    | RealtimeInteractionStarted
    | RealtimeUserTranscriptPartial
    | RealtimeUserTranscriptFinal
    | RealtimeAssistantAudioChunk
    | RealtimeAssistantTranscriptPartial
    | RealtimeAssistantTranscriptFinal
    | RealtimeInteractionFailed
    | ConversationRealtimeSessionFailed
    | RealtimeSessionClosed
    | ConversationTurnStarted
    | ConversationTurnCompleted
    | ConversationTurnFailed
    | ConversationTurnInterrupted
)
