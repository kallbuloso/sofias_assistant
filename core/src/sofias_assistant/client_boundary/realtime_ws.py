"""Authenticated WebSocket adapter for the Core-owned realtime runtime."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from sofias_assistant.ai.contracts import (
    AudioEncoding,
    AudioFormat,
    DataLocality,
    ModelIdentity,
    RealtimeSessionId,
)
from sofias_assistant.client_boundary.auth import LocalClientAuthenticator
from sofias_assistant.client_boundary.sessions import ClientSessionRegistry
from sofias_assistant.conversation.events import (
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
)
from sofias_assistant.conversation.models import Turn
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
from sofias_assistant.conversation.realtime_runtime import OpenRealtimeSessionCommand
from sofias_assistant.secrets.models import SecretValue

PROTOCOL_VERSION = "realtime.v1"
AUTH_TIMEOUT_SECONDS = 5.0
AUTH_JSON_MAX_BYTES = 4 * 1024
CONTROL_JSON_MAX_BYTES = 16 * 1024
AUDIO_MAX_BYTES = 64 * 1024

_CONTROL_FIELDS: dict[str, frozenset[str]] = {
    "session.open": frozenset(
        {
            "protocol_version",
            "type",
            "sequence",
            "conversation_id",
            "locality",
            "cloud_context_eligible",
            "input_audio_format",
            "output_audio_format",
            "model_override",
        }
    ),
    "input_started": frozenset(
        {
            "protocol_version",
            "type",
            "sequence",
            "realtime_session_id",
        }
    ),
    "input_committed": frozenset(
        {
            "protocol_version",
            "type",
            "sequence",
            "realtime_session_id",
            "realtime_interaction_id",
        }
    ),
    "session.close": frozenset(
        {
            "protocol_version",
            "type",
            "sequence",
            "realtime_session_id",
        }
    ),
}


class RealtimeConversationApi(Protocol):
    async def open_session(self, command: OpenRealtimeSessionCommand): ...
    async def start_interaction(self, realtime_session_id: RealtimeSessionId): ...
    async def send_audio(
        self, realtime_session_id: RealtimeSessionId, audio: bytes
    ) -> None: ...
    async def commit_interaction(
        self, realtime_session_id: RealtimeSessionId
    ) -> None: ...
    def events(
        self, realtime_session_id: RealtimeSessionId
    ) -> AsyncIterator[RealtimeConversationEvent]: ...
    async def close_session(self, realtime_session_id: RealtimeSessionId) -> None: ...


class _ProtocolViolation(RuntimeError):
    pass


class _PolicyViolation(RuntimeError):
    pass


class _FrameTooLarge(RuntimeError):
    pass


def register_realtime_websocket(
    app: FastAPI,
    *,
    authenticator: LocalClientAuthenticator,
    sessions: ClientSessionRegistry,
    realtime: RealtimeConversationApi,
) -> None:
    """Register the single, authenticated realtime WebSocket route."""

    @app.websocket("/api/v1/realtime")
    async def realtime_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        connection = _Connection(websocket, authenticator, sessions, realtime)
        await connection.run()


class _Connection:
    def __init__(
        self,
        websocket: WebSocket,
        authenticator: LocalClientAuthenticator,
        sessions: ClientSessionRegistry,
        realtime: RealtimeConversationApi,
    ) -> None:
        self._websocket = websocket
        self._authenticator = authenticator
        self._sessions = sessions
        self._realtime = realtime
        self._client_session_id: UUID | None = None
        self._realtime_session_id: RealtimeSessionId | None = None
        self._interaction_id: UUID | None = None
        self._input_committed = False
        self._assistant_output_interaction_id: UUID | None = None
        self._client_sequence = -1
        self._server_sequence = 0
        self._sender: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()

    async def run(self) -> None:
        try:
            await self._authenticate()
            while True:
                message = await self._websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                await self._require_live_session()
                if message.get("bytes") is not None:
                    await self._audio(message["bytes"])
                elif message.get("text") is not None:
                    await self._control(_json(message["text"], CONTROL_JSON_MAX_BYTES))
                else:
                    raise _ProtocolViolation("unsupported frame")
        except WebSocketDisconnect:
            pass
        except _ProtocolViolation:
            await self._close(1002)
        except _PolicyViolation:
            await self._close(1008)
        except _FrameTooLarge:
            await self._close(1009)
        except Exception:
            await self._safe_error("internal_realtime_error")
            await self._close(1011)
        finally:
            sender = self._sender
            if sender is not None and not sender.done():
                sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass
            if self._realtime_session_id is not None:
                try:
                    await self._realtime.close_session(self._realtime_session_id)
                except Exception:
                    pass

    async def _authenticate(self) -> None:
        try:
            async with asyncio.timeout(AUTH_TIMEOUT_SECONDS):
                message = await self._websocket.receive()
        except TimeoutError as error:
            raise _ProtocolViolation("authentication timeout") from error
        if message["type"] != "websocket.receive" or message.get("text") is None:
            await self._close(1008)
            raise _ProtocolViolation("authentication failed")
        try:
            value = _json(message["text"], AUTH_JSON_MAX_BYTES)
            if (
                value.get("protocol_version") != PROTOCOL_VERSION
                or value.get("type") != "authenticate"
                or value.get("sequence") != 0
            ):
                raise ValueError
            credential = value.get("credential")
            session_id = UUID(_string(value, "client_session_id"))
            if not isinstance(credential, str) or not credential.strip():
                raise ValueError
            if (
                not self._authenticator.authenticate(SecretValue(credential))
                or self._sessions.get(session_id) is None
            ):
                raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError):
            await self._close(1008)
            raise _ProtocolViolation("authentication failed") from None
        self._client_session_id = session_id
        self._client_sequence = 0
        await self._send_control("authenticated", client_session_id=str(session_id))

    async def _control(self, value: dict[str, object]) -> None:
        if value.get("protocol_version") != PROTOCOL_VERSION:
            raise _ProtocolViolation("wrong protocol version")
        sequence = value.get("sequence")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence != self._client_sequence + 1
        ):
            raise _ProtocolViolation("invalid control sequence")
        self._client_sequence = sequence
        kind = value.get("type")
        if not isinstance(kind, str) or kind not in _CONTROL_FIELDS:
            raise _ProtocolViolation("unsupported control")
        if value.keys() - _CONTROL_FIELDS[kind]:
            raise _ProtocolViolation("unexpected control field")
        if kind == "session.open":
            await self._open(value)
        elif kind == "input_started":
            await self._start(value)
        elif kind == "input_committed":
            await self._commit(value)
        elif kind == "session.close":
            await self._client_close(value)

    async def _open(self, value: dict[str, object]) -> None:
        if self._realtime_session_id is not None:
            raise _ProtocolViolation("session already open")
        try:
            command = OpenRealtimeSessionCommand(
                conversation_id=UUID(_string(value, "conversation_id")),
                locality=DataLocality(_string(value, "locality")),
                cloud_context_eligible=_bool(value, "cloud_context_eligible"),
                input_audio_format=_audio_format(value.get("input_audio_format")),
                output_audio_format=_audio_format(value.get("output_audio_format")),
                model_override=_model_override(value.get("model_override")),
            )
            session = await self._realtime.open_session(command)
        except Exception:
            await self._safe_error("incompatible_realtime_request")
            await self._close(1008)
            raise _ProtocolViolation("session open failed") from None
        self._realtime_session_id = session.id
        self._sender = asyncio.create_task(self._forward_events(session.id))

    async def _start(self, value: dict[str, object]) -> None:
        session_id = self._require_session(value)
        if self._interaction_id is not None:
            raise _ProtocolViolation("interaction already active")
        interaction_id = await self._realtime.start_interaction(session_id)
        self._interaction_id = interaction_id
        self._input_committed = False

    async def _audio(self, audio: bytes) -> None:
        if len(audio) > AUDIO_MAX_BYTES:
            raise _FrameTooLarge("oversized audio frame")
        if not audio:
            raise _ProtocolViolation("invalid audio frame")
        if (
            self._realtime_session_id is None
            or self._interaction_id is None
            or self._input_committed
        ):
            raise _ProtocolViolation("audio outside active input")
        await self._realtime.send_audio(self._realtime_session_id, audio)

    async def _commit(self, value: dict[str, object]) -> None:
        session_id = self._require_session(value)
        interaction_id = UUID(_string(value, "realtime_interaction_id"))
        if interaction_id != self._interaction_id or self._input_committed:
            raise _ProtocolViolation("invalid interaction correlation")
        await self._realtime.commit_interaction(session_id)
        self._input_committed = True

    async def _client_close(self, value: dict[str, object]) -> None:
        session_id = self._require_session(value)
        await self._realtime.close_session(session_id)
        await self._close(1000)
        self._realtime_session_id = None

    async def _forward_events(self, session_id: RealtimeSessionId) -> None:
        try:
            async for event in self._realtime.events(session_id):
                await self._forward_event(event)
                if isinstance(
                    event, (ConversationRealtimeSessionFailed, RealtimeSessionClosed)
                ):
                    self._realtime_session_id = None
                    await self._close(1000)
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await self._safe_error("internal_realtime_error")
            except Exception:
                pass
            await self._close(1011)
        else:
            try:
                await self._safe_error("internal_realtime_error")
            except Exception:
                pass
            await self._close(1011)

    async def _forward_event(self, event: RealtimeConversationEvent) -> None:
        if isinstance(event, RealtimeAssistantAudioChunk):
            if self._interaction_id != event.realtime_interaction_id:
                return
            if self._assistant_output_interaction_id != event.realtime_interaction_id:
                await self._send_control(
                    "assistant_output.started",
                    realtime_session_id=str(event.realtime_session_id),
                    realtime_interaction_id=str(event.realtime_interaction_id),
                    audio_format=_format_wire(event.audio_format),
                )
                self._assistant_output_interaction_id = event.realtime_interaction_id
            await self._send_bytes(event.audio)
            return
        payload = _event_wire(event)
        kind = payload.pop("type")
        assert isinstance(kind, str)
        await self._send_control(kind, **payload)
        if isinstance(
            event,
            (
                ConversationTurnCompleted,
                ConversationTurnFailed,
                ConversationTurnInterrupted,
                RealtimeInteractionFailed,
            ),
        ):
            self._interaction_id = None
            self._assistant_output_interaction_id = None

    async def _require_live_session(self) -> None:
        if (
            self._client_session_id is None
            or self._sessions.get(self._client_session_id) is None
        ):
            raise _PolicyViolation("client session revoked")

    def _require_session(self, value: dict[str, object]) -> RealtimeSessionId:
        if (
            self._realtime_session_id is None
            or UUID(_string(value, "realtime_session_id")) != self._realtime_session_id
        ):
            raise _ProtocolViolation("invalid session correlation")
        return self._realtime_session_id

    async def _send_control(self, kind: str, **payload: object) -> None:
        async with self._send_lock:
            await self._websocket.send_json(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "type": kind,
                    "sequence": self._server_sequence,
                    **payload,
                }
            )
            self._server_sequence += 1

    async def _send_bytes(self, audio: bytes) -> None:
        async with self._send_lock:
            await self._websocket.send_bytes(audio)

    async def _safe_error(self, code: str) -> None:
        await self._send_control(
            "error", code=code, message="Realtime request could not be processed"
        )

    async def _close(self, code: int) -> None:
        try:
            await self._websocket.close(code=code)
        except RuntimeError:
            pass


def _json(text: str, maximum: int) -> dict[str, object]:
    if len(text.encode("utf-8")) > maximum:
        raise _FrameTooLarge("oversized control")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise _ProtocolViolation("control must be object")
    return value


def _string(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ValueError(key)
    return result


def _bool(value: dict[str, object], key: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise ValueError(key)
    return result


def _audio_format(value: object) -> AudioFormat:
    if not isinstance(value, dict):
        raise ValueError("audio format")
    encoding = value.get("encoding")
    sample_rate_hz = value.get("sample_rate_hz")
    channels = value.get("channels")
    if (
        not isinstance(encoding, str)
        or isinstance(sample_rate_hz, bool)
        or not isinstance(sample_rate_hz, int)
        or isinstance(channels, bool)
        or not isinstance(channels, int)
    ):
        raise ValueError("audio format")
    result = AudioFormat(AudioEncoding(encoding), sample_rate_hz, channels)
    if result != AudioFormat(AudioEncoding.PCM16, 24_000, 1):
        raise ValueError("unsupported audio format")
    return result


def _model_override(value: object) -> ModelIdentity | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("model override")
    return ModelIdentity(_string(value, "provider_id"), _string(value, "model_id"))


def _format_wire(value: AudioFormat) -> dict[str, object]:
    return {
        "encoding": value.encoding.value,
        "sample_rate_hz": value.sample_rate_hz,
        "channels": value.channels,
    }


def _turn_wire(turn: Turn) -> dict[str, object]:
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


def _event_wire(event: RealtimeConversationEvent) -> dict[str, object]:
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
    if isinstance(event, ConversationTurnStarted):
        return {
            "type": "turn.started",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_wire(event.turn),
        }
    if isinstance(event, ConversationTurnCompleted):
        return {
            "type": "turn.completed",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_wire(event.turn),
        }
    if isinstance(event, ConversationTurnFailed):
        return {
            "type": "turn.failed",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_wire(event.turn),
        }
    if isinstance(event, ConversationTurnInterrupted):
        return {
            "type": "turn.interrupted",
            "conversation": {"id": str(event.conversation.id)},
            "turn": _turn_wire(event.turn),
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
    raise AssertionError("unsupported realtime event")
