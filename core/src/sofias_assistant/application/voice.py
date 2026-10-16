"""Native realtime voice application service for SAS-03D."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sofias_assistant.ai.contracts import (
    AudioEncoding,
    AudioFormat,
    DataLocality,
    RealtimeInteractionId,
    RealtimeSessionId,
)
from sofias_assistant.conversation.events import (
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
)
from sofias_assistant.conversation.realtime_events import (
    ConversationRealtimeSessionFailed,
    RealtimeAssistantAudioChunk,
    RealtimeAssistantTranscriptFinal,
    RealtimeAssistantTranscriptPartial,
    RealtimeConversationEvent,
    RealtimeInteractionFailed,
    RealtimeInteractionStarted,
    RealtimeSessionClosed,
    RealtimeSessionOpened,
    RealtimeUserTranscriptFinal,
    RealtimeUserTranscriptPartial,
)
from sofias_assistant.conversation.realtime_runtime import (
    OpenRealtimeSessionCommand,
    RealtimeConversationRuntime,
)

_PCM_24K_MONO = AudioFormat(AudioEncoding.PCM16, 24_000, 1)


class VoiceService:
    """Transport-free application boundary for Desktop realtime voice."""

    def __init__(self, runtime: RealtimeConversationRuntime) -> None:
        self._runtime = runtime

    async def open(
        self,
        conversation_id,
        *,
        locality: str,
        cloud_context_eligible: bool,
    ) -> RealtimeSessionId:
        session = await self._runtime.open_session(
            OpenRealtimeSessionCommand(
                conversation_id=conversation_id,
                locality=DataLocality(locality),
                cloud_context_eligible=cloud_context_eligible,
                input_audio_format=_PCM_24K_MONO,
                output_audio_format=_PCM_24K_MONO,
            )
        )
        return session.id

    async def start(self, session_id: RealtimeSessionId) -> RealtimeInteractionId:
        return await self._runtime.start_interaction(session_id)

    async def send_audio(self, session_id: RealtimeSessionId, audio: bytes) -> None:
        await self._runtime.send_audio(session_id, audio)

    async def commit(self, session_id: RealtimeSessionId) -> None:
        await self._runtime.commit_interaction(session_id)

    async def interrupt(
        self,
        session_id: RealtimeSessionId,
        interaction_id: RealtimeInteractionId,
    ) -> None:
        await self._runtime.interrupt_interaction(session_id, interaction_id)

    async def cancel(
        self,
        session_id: RealtimeSessionId,
        interaction_id: RealtimeInteractionId,
    ) -> None:
        await self._runtime.cancel_interaction(session_id, interaction_id)

    async def close(self, session_id: RealtimeSessionId) -> None:
        await self._runtime.close_session(session_id)

    async def events(
        self, session_id: RealtimeSessionId
    ) -> AsyncIterator[dict[str, object]]:
        async for event in self._runtime.events(session_id):
            yield _event_record(event)


def _turn_record(turn) -> dict[str, object]:
    return {
        "id": str(turn.id),
        "conversation_id": str(turn.conversation_id),
        "sequence": turn.sequence,
        "status": turn.status.value,
        "input_modality": turn.input_modality.value,
        "cloud_context_eligible": turn.cloud_context_eligible,
        "user_text": turn.user_text,
        "assistant_text": turn.assistant_text,
        "provider_id": turn.provider_id,
        "model_id": turn.model_id,
        "error_category": turn.error_category,
        "error_message": turn.error_message,
    }


def _event_record(event: RealtimeConversationEvent) -> dict[str, object]:
    if isinstance(event, RealtimeSessionOpened):
        return {
            "type": "session.opened",
            "realtime_session_id": str(event.realtime_session_id),
            "conversation_id": str(event.conversation_id),
            "model": {
                "provider_id": event.model.provider_id,
                "model_id": event.model.model_id,
            },
        }
    if isinstance(event, RealtimeInteractionStarted):
        return {
            "type": "interaction.started",
            "realtime_session_id": str(event.realtime_session_id),
            "realtime_interaction_id": str(event.realtime_interaction_id),
        }
    if isinstance(
        event,
        (
            RealtimeUserTranscriptPartial,
            RealtimeUserTranscriptFinal,
            RealtimeAssistantTranscriptPartial,
            RealtimeAssistantTranscriptFinal,
        ),
    ):
        names = {
            RealtimeUserTranscriptPartial: "user_transcript.partial",
            RealtimeUserTranscriptFinal: "user_transcript.final",
            RealtimeAssistantTranscriptPartial: "assistant_transcript.partial",
            RealtimeAssistantTranscriptFinal: "assistant_transcript.final",
        }
        return {
            "type": names[type(event)],
            "realtime_session_id": str(event.realtime_session_id),
            "realtime_interaction_id": str(event.realtime_interaction_id),
            "text": event.text,
        }
    if isinstance(event, RealtimeAssistantAudioChunk):
        return {
            "type": "assistant_audio_chunk",
            "realtime_session_id": str(event.realtime_session_id),
            "realtime_interaction_id": str(event.realtime_interaction_id),
            "audio": event.audio,
        }
    if isinstance(event, ConversationTurnStarted):
        return {
            "type": "turn.started",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_record(event.turn),
        }
    if isinstance(event, ConversationTurnCompleted):
        return {
            "type": "turn.completed",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_record(event.turn),
        }
    if isinstance(event, ConversationTurnFailed):
        return {
            "type": "turn.failed",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_record(event.turn),
        }
    if isinstance(event, ConversationTurnInterrupted):
        return {
            "type": "turn.interrupted",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_record(event.turn),
        }
    if isinstance(event, RealtimeInteractionFailed):
        return {
            "type": "interaction.failed",
            "realtime_session_id": str(event.realtime_session_id),
            "realtime_interaction_id": str(event.realtime_interaction_id),
            "message": event.safe_message,
        }
    if isinstance(event, ConversationRealtimeSessionFailed):
        return {
            "type": "session.failed",
            "realtime_session_id": str(event.realtime_session_id),
            "message": event.safe_message,
        }
    if isinstance(event, RealtimeSessionClosed):
        return {
            "type": "session.closed",
            "realtime_session_id": str(event.realtime_session_id),
        }
    raise AssertionError(f"Unsupported realtime event: {type(event).__name__}")
