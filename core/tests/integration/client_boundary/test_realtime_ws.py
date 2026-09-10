"""Real loopback evidence for the authenticated realtime WebSocket adapter."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from sofias_assistant.ai.contracts import (
    AudioEncoding,
    AudioFormat,
    ModelIdentity,
    RealtimeInteractionId,
    RealtimeSessionId,
)
from sofias_assistant.client_boundary.auth import LocalClientAuthenticator
from sofias_assistant.client_boundary.boundary import (
    LocalClientAccess,
    LocalClientBoundary,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.client_boundary.realtime_ws import _event_wire
from sofias_assistant.client_boundary.sessions import ClientSessionRegistry
from sofias_assistant.conversation.events import (
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
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
    InvalidRealtimeStateError,
    OpenRealtimeSessionCommand,
    RealtimeSessionConflictError,
)
from sofias_assistant.conversation.runtime import ConversationNotFoundError


def _format() -> AudioFormat:
    return AudioFormat(AudioEncoding.PCM16, 24_000, 1)


@dataclass(frozen=True, slots=True)
class _Session:
    id: RealtimeSessionId


class _RealtimeApi:
    def __init__(
        self,
        open_error: Exception | None = None,
        *,
        stream_end: bool = False,
        stream_error: Exception | None = None,
    ) -> None:
        self.open_error = open_error
        self.stream_end = stream_end
        self.stream_error = stream_error
        self.events_calls = 0
        self.events_finished = 0
        self.events_cancelled = 0
        self.events_done = asyncio.Event()
        self.commands: list[OpenRealtimeSessionCommand] = []
        self.started_sessions: list[RealtimeSessionId] = []
        self.committed_sessions: list[RealtimeSessionId] = []
        self.cancelled: list[tuple[RealtimeSessionId, RealtimeInteractionId]] = []
        self.interrupted: list[tuple[RealtimeSessionId, RealtimeInteractionId]] = []
        self.audio: list[bytes] = []
        self.closed: list[RealtimeSessionId] = []
        self._queue: asyncio.Queue[RealtimeConversationEvent] = asyncio.Queue(
            maxsize=16
        )
        self._session_id: RealtimeSessionId | None = None
        self._interaction_id: RealtimeInteractionId | None = None

    async def open_session(self, command: OpenRealtimeSessionCommand) -> _Session:
        if self.open_error is not None:
            raise self.open_error
        self.commands.append(command)
        self._session_id = RealtimeSessionId(uuid4())
        await self._queue.put(
            RealtimeSessionOpened(
                self._session_id, command.conversation_id, ModelIdentity("fake", "rt")
            )
        )
        return _Session(self._session_id)

    async def start_interaction(
        self, realtime_session_id: RealtimeSessionId
    ) -> RealtimeInteractionId:
        assert realtime_session_id == self._session_id
        self.started_sessions.append(realtime_session_id)
        self._interaction_id = RealtimeInteractionId(uuid4())
        await self._queue.put(
            RealtimeInteractionStarted(realtime_session_id, self._interaction_id)
        )
        return self._interaction_id

    async def send_audio(
        self, realtime_session_id: RealtimeSessionId, audio: bytes
    ) -> None:
        assert realtime_session_id == self._session_id
        self.audio.append(audio)

    async def commit_interaction(self, realtime_session_id: RealtimeSessionId) -> None:
        assert realtime_session_id == self._session_id
        assert self._interaction_id is not None
        self.committed_sessions.append(realtime_session_id)
        await self._queue.put(
            RealtimeAssistantAudioChunk(
                realtime_session_id, self._interaction_id, 0, b"assistant", _format()
            )
        )

    async def cancel_interaction(
        self,
        realtime_session_id: RealtimeSessionId,
        realtime_interaction_id: RealtimeInteractionId,
    ) -> None:
        assert realtime_session_id == self._session_id
        assert realtime_interaction_id == self._interaction_id
        self.cancelled.append((realtime_session_id, realtime_interaction_id))

    async def interrupt_interaction(
        self,
        realtime_session_id: RealtimeSessionId,
        realtime_interaction_id: RealtimeInteractionId,
    ) -> None:
        assert realtime_session_id == self._session_id
        assert realtime_interaction_id == self._interaction_id
        self.interrupted.append((realtime_session_id, realtime_interaction_id))

    async def close_session(self, realtime_session_id: RealtimeSessionId) -> None:
        self.closed.append(realtime_session_id)
        await self._queue.put(RealtimeSessionClosed(realtime_session_id))

    async def fail_interaction(self) -> None:
        assert self._session_id is not None
        assert self._interaction_id is not None
        await self._queue.put(
            RealtimeInteractionFailed(
                self._session_id, self._interaction_id, "fake terminal failure"
            )
        )

    async def emit(self, event: RealtimeConversationEvent) -> None:
        await self._queue.put(event)

    async def events(
        self, realtime_session_id: RealtimeSessionId
    ) -> AsyncIterator[RealtimeConversationEvent]:
        self.events_calls += 1
        try:
            if self.stream_error is not None or self.stream_end:
                event = await self._queue.get()
                yield event
                if self.stream_error is not None:
                    raise self.stream_error
                return
            while True:
                event = await self._queue.get()
                yield event
                if isinstance(event, RealtimeSessionClosed):
                    return
        except asyncio.CancelledError:
            self.events_cancelled += 1
            raise
        finally:
            self.events_finished += 1
            self.events_done.set()


async def _control(socket: websockets.ClientConnection) -> dict[str, object]:
    received = await socket.recv()
    assert isinstance(received, str)
    value = json.loads(received)
    assert isinstance(value, dict)
    return value


def _auth_payload(access: LocalClientAccess, session_id: object) -> str:
    return json.dumps(
        {
            "protocol_version": "realtime.v1",
            "type": "authenticate",
            "sequence": 0,
            "credential": access.credential.reveal(),
            "client_session_id": str(session_id),
        }
    )


def _pad_json(payload: str, size: int) -> str:
    encoded_length = len(payload.encode("utf-8"))
    assert encoded_length <= size
    return payload + " " * (size - encoded_length)


async def _active_interaction(
    socket: websockets.ClientConnection,
    access: LocalClientAccess,
    session_id: object,
) -> tuple[dict[str, object], dict[str, object]]:
    await socket.send(_auth_payload(access, session_id))
    assert (await _control(socket))["type"] == "authenticated"
    await socket.send(_open_control(1))
    opened = await _control(socket)
    await socket.send(_input_started_control(2, opened["realtime_session_id"]))
    started = await _control(socket)
    return opened, started


async def _opened_session(
    socket: websockets.ClientConnection,
    access: LocalClientAccess,
    session_id: object,
) -> dict[str, object]:
    await socket.send(_auth_payload(access, session_id))
    assert (await _control(socket))["type"] == "authenticated"
    await socket.send(_open_control(1))
    opened = await _control(socket)
    assert opened["type"] == "session.opened"
    return opened


def _turn_snapshot(conversation_id: UUID, status: TurnStatus) -> Turn:
    timestamp = datetime.now(UTC)
    terminal = status is not TurnStatus.PROCESSING
    return Turn(
        id=uuid4(),
        conversation_id=conversation_id,
        sequence=1,
        status=status,
        input_modality=TurnInputModality.VOICE,
        cloud_context_eligible=True,
        user_text="user text",
        assistant_text="assistant text" if terminal else None,
        ai_request_id=uuid4(),
        provider_id="provider-a",
        model_id="model-a",
        provider_request_id="native-request-secret",
        provider_session_id="native-session-secret",
        error_category="provider_error" if status is TurnStatus.FAILED else None,
        error_message="safe turn error" if status is TurnStatus.FAILED else None,
        created_at=timestamp,
        updated_at=timestamp,
        finished_at=timestamp if terminal else None,
    )


def _assert_wire_safe(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload)
    for forbidden in (
        "provider_session_id",
        "provider_request_id",
        "provider_session",
        "consumer_task",
        "event_queue",
        "SecretValue",
        "SecretRef",
        "native-session-secret",
        "native-request-secret",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_real_loopback_websocket_authenticates_and_forwards_binary_audio() -> (
    None
):
    realtime = _RealtimeApi()
    captured_sessions = []

    def app_factory(authenticator, sessions):
        captured_sessions.append(sessions)
        return create_local_http_app(authenticator, sessions, realtime=realtime)

    boundary = LocalClientBoundary(
        port=0,
        app_factory=app_factory,
    )
    access = await boundary.start()
    try:
        session_id = str(captured_sessions[0].open_session(access.credential).id)
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": access.credential.reveal(),
                        "client_session_id": session_id,
                    }
                )
            )
            assert (await _control(socket))["type"] == "authenticated"
            conversation_id = str(uuid4())
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.open",
                        "sequence": 1,
                        "conversation_id": conversation_id,
                        "locality": "local_only",
                        "cloud_context_eligible": True,
                        "input_audio_format": {
                            "encoding": "pcm16",
                            "sample_rate_hz": 24000,
                            "channels": 1,
                        },
                        "output_audio_format": {
                            "encoding": "pcm16",
                            "sample_rate_hz": 24000,
                            "channels": 1,
                        },
                        "model_override": None,
                    }
                )
            )
            opened = await _control(socket)
            assert opened["type"] == "session.opened"
            assert opened["realtime_session_id"] != conversation_id
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": opened["realtime_session_id"],
                    }
                )
            )
            started = await _control(socket)
            assert started["type"] == "interaction.started"
            await socket.send(b"exact-audio")
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": opened["realtime_session_id"],
                        "realtime_interaction_id": started["realtime_interaction_id"],
                    }
                )
            )
            output = await _control(socket)
            assert output["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            assert realtime.audio == [b"exact-audio"]
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 4,
                        "realtime_session_id": opened["realtime_session_id"],
                    }
                )
            )
        assert len(realtime.closed) == 1
    finally:
        await boundary.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("open_error", "internal_detail"),
    [
        (
            ConversationNotFoundError(
                "repository detail provider_session_id=secret traceback"
            ),
            "ConversationNotFoundError",
        ),
        (
            RealtimeSessionConflictError(
                "provider_request_id=secret SDK detail object repr"
            ),
            "RealtimeSessionConflictError",
        ),
        (
            InvalidRealtimeStateError("raw provider error traceback"),
            "InvalidRealtimeStateError",
        ),
    ],
)
async def test_session_open_failures_map_to_safe_error_and_close_socket(
    open_error: Exception, internal_detail: str
) -> None:
    boundary, pair, realtime = await _boundary_for_auth(open_error)
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, session.id))
            assert (await _control(socket))["type"] == "authenticated"
            error, close_code = await _error_then_closed(socket, _open_control(1))
            assert error == {
                "protocol_version": "realtime.v1",
                "type": "error",
                "sequence": 1,
                "code": "incompatible_realtime_request",
                "message": "Realtime request could not be processed",
            }
            serialized_error = json.dumps(error)
            assert internal_detail not in serialized_error
            assert "provider_session_id" not in serialized_error
            assert "provider_request_id" not in serialized_error
            assert "traceback" not in serialized_error
            assert "SDK detail" not in serialized_error
            assert "raw provider error" not in serialized_error
            assert "object repr" not in serialized_error
            assert close_code == 1008
        assert realtime.commands == []
        assert realtime.closed == []
        assert realtime.events_calls == 0
        assert realtime._session_id is None
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_unknown_controls_are_protocol_rejected() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, session.id))
            assert (await _control(socket))["type"] == "authenticated"
            payload = json.dumps(
                {
                    "protocol_version": "realtime.v1",
                    "type": "definitely.unknown",
                    "sequence": 1,
                }
            )
            assert await _closed_after_first(socket, payload) == 1002
        assert realtime.commands == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_realtime_application_events_map_to_safe_wire_controls() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    conversation_id = uuid4()
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened_wire, started_wire = await _active_interaction(
                socket, access, client_session.id
            )
            assert realtime._session_id is not None
            assert realtime._interaction_id is not None
            session_id = realtime._session_id
            interaction_id = realtime._interaction_id

            assert opened_wire["type"] == "session.opened"
            assert opened_wire["realtime_session_id"] == str(session_id)
            assert realtime.commands
            assert opened_wire["conversation_id"] == str(
                realtime.commands[0].conversation_id
            )
            assert opened_wire["model"] == {"provider_id": "fake", "model_id": "rt"}
            _assert_wire_safe(opened_wire)
            assert started_wire["type"] == "interaction.started"
            assert started_wire["realtime_session_id"] == str(session_id)
            assert started_wire["realtime_interaction_id"] == str(interaction_id)
            _assert_wire_safe(started_wire)

            expected_text_events: list[
                tuple[
                    RealtimeUserTranscriptPartial
                    | RealtimeUserTranscriptFinal
                    | RealtimeAssistantTranscriptPartial
                    | RealtimeAssistantTranscriptFinal,
                    str,
                ]
            ] = [
                (
                    RealtimeUserTranscriptPartial(
                        session_id, interaction_id, 0, "user partial"
                    ),
                    "user_transcript.partial",
                ),
                (
                    RealtimeUserTranscriptFinal(
                        session_id, interaction_id, 1, "user final"
                    ),
                    "user_transcript.final",
                ),
                (
                    RealtimeAssistantTranscriptPartial(
                        session_id, interaction_id, 2, "assistant partial"
                    ),
                    "assistant_transcript.partial",
                ),
                (
                    RealtimeAssistantTranscriptFinal(
                        session_id, interaction_id, 3, "assistant final"
                    ),
                    "assistant_transcript.final",
                ),
            ]
            for text_event, expected_type in expected_text_events:
                await realtime.emit(text_event)
                payload = await _control(socket)
                assert payload["type"] == expected_type
                assert payload["realtime_session_id"] == str(session_id)
                assert payload["realtime_interaction_id"] == str(interaction_id)
                assert payload["text"] == text_event.text
                _assert_wire_safe(payload)

            conversation = Conversation(
                conversation_id, datetime.now(UTC), datetime.now(UTC)
            )
            processing = _turn_snapshot(conversation_id, TurnStatus.PROCESSING)
            completed = _turn_snapshot(conversation_id, TurnStatus.COMPLETED)
            failed = _turn_snapshot(conversation_id, TurnStatus.FAILED)
            interrupted = _turn_snapshot(conversation_id, TurnStatus.INTERRUPTED)
            turn_events: list[
                tuple[
                    ConversationTurnStarted
                    | ConversationTurnCompleted
                    | ConversationTurnFailed
                    | ConversationTurnInterrupted,
                    str,
                ]
            ] = [
                (ConversationTurnStarted(conversation, processing), "turn.started"),
                (
                    ConversationTurnCompleted(conversation, completed),
                    "turn.completed",
                ),
                (ConversationTurnFailed(conversation, failed), "turn.failed"),
                (
                    ConversationTurnInterrupted(conversation, interrupted),
                    "turn.interrupted",
                ),
            ]
            for turn_event, expected_type in turn_events:
                await realtime.emit(turn_event)
                payload = await _control(socket)
                assert payload["type"] == expected_type
                conversation_payload = payload.get("conversation")
                turn_payload = payload.get("turn")
                assert isinstance(conversation_payload, dict)
                assert isinstance(turn_payload, dict)
                assert conversation_payload["id"] == str(conversation_id)
                assert "provider_id" in turn_payload
                assert "model_id" in turn_payload
                _assert_wire_safe(payload)

            await realtime.emit(
                RealtimeInteractionFailed(session_id, interaction_id, "safe failure")
            )
            payload = await _control(socket)
            assert payload["type"] == "interaction.failed"
            assert payload["message"] == "safe failure"
            _assert_wire_safe(payload)

            await realtime.emit(
                ConversationRealtimeSessionFailed(session_id, "safe session failure")
            )
            payload = await _control(socket)
            assert payload["type"] == "session.failed"
            assert payload["message"] == "safe session failure"
            _assert_wire_safe(payload)

            payload = _event_wire(RealtimeSessionClosed(session_id))
            assert payload["type"] == "session.closed"
            assert payload["realtime_session_id"] == str(session_id)
            _assert_wire_safe(payload)
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_assistant_audio_chunks_frame_once_per_interaction_and_sequence_json_only() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, client_session.id))
            authenticated = await _control(socket)
            assert authenticated["sequence"] == 0
            await socket.send(_open_control(1))
            opened = await _control(socket)
            assert opened["sequence"] == 1
            await socket.send(_input_started_control(2, opened["realtime_session_id"]))
            started_a = await _control(socket)
            assert started_a["sequence"] == 2
            assert realtime._session_id is not None
            assert realtime._interaction_id is not None
            session_id = realtime._session_id
            interaction_a = realtime._interaction_id

            await realtime.emit(
                RealtimeAssistantAudioChunk(
                    session_id, interaction_a, 0, b"A1", _format()
                )
            )
            announced_a = await _control(socket)
            assert announced_a["type"] == "assistant_output.started"
            assert announced_a["sequence"] == 3
            assert announced_a["realtime_interaction_id"] == str(interaction_a)
            assert announced_a["audio_format"] == {
                "encoding": "pcm16",
                "sample_rate_hz": 24000,
                "channels": 1,
            }
            assert await socket.recv() == b"A1"
            _assert_wire_safe(announced_a)

            await realtime.emit(
                RealtimeAssistantAudioChunk(
                    session_id, interaction_a, 1, b"A2", _format()
                )
            )
            assert await socket.recv() == b"A2"

            await realtime.emit(
                RealtimeInteractionFailed(session_id, interaction_a, "ended")
            )
            failed = await _control(socket)
            assert failed["type"] == "interaction.failed"
            assert failed["sequence"] == 4
            _assert_wire_safe(failed)

            await socket.send(_input_started_control(3, opened["realtime_session_id"]))
            started_b = await _control(socket)
            assert started_b["sequence"] == 5
            interaction_b = started_b["realtime_interaction_id"]
            assert interaction_b != str(interaction_a)
            assert realtime._interaction_id is not None
            await realtime.emit(
                RealtimeAssistantAudioChunk(
                    session_id, realtime._interaction_id, 0, b"B1", _format()
                )
            )
            announced_b = await _control(socket)
            assert announced_b["type"] == "assistant_output.started"
            assert announced_b["sequence"] == 6
            assert announced_b["realtime_interaction_id"] == interaction_b
            assert await socket.recv() == b"B1"
            _assert_wire_safe(announced_b)
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_session_close_closes_owned_core_session_once_and_stops_sender() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened = await _opened_session(socket, access, client_session.id)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 2,
                        "realtime_session_id": opened["realtime_session_id"],
                    }
                )
            )
        assert realtime._session_id is not None
        assert realtime.closed == [realtime._session_id]
        assert realtime.events_calls == 1
        assert realtime.events_finished == 1
        assert realtime.events_cancelled in (0, 1)
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_session_close_wrong_id_never_closes_wrong_core_session() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    wrong_id = str(uuid4())
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened = await _opened_session(socket, access, client_session.id)
            wrong_close = json.dumps(
                {
                    "protocol_version": "realtime.v1",
                    "type": "session.close",
                    "sequence": 2,
                    "realtime_session_id": wrong_id,
                }
            )
            assert await _closed_after_first(socket, wrong_close) == 1002
        assert realtime._session_id is not None
        assert wrong_id != str(realtime._session_id)
        assert realtime.closed == [realtime._session_id]
        assert realtime.closed.count(realtime._session_id) == 1
        assert opened["realtime_session_id"] == str(realtime._session_id)
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_disconnect_before_session_open_does_not_close_core_session() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, client_session.id))
            assert (await _control(socket))["type"] == "authenticated"
        assert realtime.closed == []
        assert realtime.events_calls == 0
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_disconnect_with_open_session_closes_owned_session_once() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _opened_session(socket, access, client_session.id)
        assert realtime._session_id is not None
        assert realtime.closed == [realtime._session_id]
        assert realtime.events_calls == 1
        assert realtime.events_finished == 1
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_disconnect_during_pre_turn_interaction_delegates_only_to_runtime() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _active_interaction(socket, access, client_session.id)
        assert realtime._session_id is not None
        assert realtime.closed == [realtime._session_id]
        assert len(realtime.commands) == 1
        assert len(realtime.started_sessions) == 1
        assert realtime.committed_sessions == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_disconnect_during_post_turn_interaction_delegates_only_to_runtime() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    conversation_id = uuid4()
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            assert realtime._session_id is not None
            assert realtime._interaction_id is not None
            await realtime.emit(
                RealtimeUserTranscriptFinal(
                    realtime._session_id,
                    realtime._interaction_id,
                    0,
                    "durable user text",
                )
            )
            assert (await _control(socket))["type"] == "user_transcript.final"
            conversation = Conversation(
                conversation_id, datetime.now(UTC), datetime.now(UTC)
            )
            turn = _turn_snapshot(conversation_id, TurnStatus.PROCESSING)
            await realtime.emit(ConversationTurnStarted(conversation, turn))
            assert (await _control(socket))["type"] == "turn.started"
            assert opened["realtime_session_id"] == str(realtime._session_id)
            assert started["realtime_interaction_id"] == str(realtime._interaction_id)
        assert realtime.closed == [realtime._session_id]
        assert realtime.committed_sessions == []
        assert len(realtime.started_sessions) == 1
    finally:
        await boundary.stop()


async def _boundary_for_auth(
    open_error: Exception | None = None,
    *,
    stream_end: bool = False,
    stream_error: Exception | None = None,
) -> tuple[
    LocalClientBoundary, tuple[LocalClientAccess, ClientSessionRegistry], _RealtimeApi
]:
    realtime = _RealtimeApi(
        open_error, stream_end=stream_end, stream_error=stream_error
    )
    captured: list[ClientSessionRegistry] = []

    def factory(
        authenticator: LocalClientAuthenticator, sessions: ClientSessionRegistry
    ):
        captured.append(sessions)
        return create_local_http_app(authenticator, sessions, realtime=realtime)

    boundary = LocalClientBoundary(port=0, app_factory=factory)
    access = await boundary.start()
    return boundary, (access, captured[0]), realtime


async def _closed_after_first(
    socket: websockets.ClientConnection, payload: str | bytes
) -> int:
    await socket.send(payload)
    with pytest.raises(ConnectionClosed) as closed:
        await socket.recv()
    assert closed.value.rcvd is not None
    return closed.value.rcvd.code


async def _error_then_closed(
    socket: websockets.ClientConnection, payload: str
) -> tuple[dict[str, object], int]:
    await socket.send(payload)
    error = await _control(socket)
    with pytest.raises(ConnectionClosed) as closed:
        await socket.recv()
    assert closed.value.rcvd is not None
    return error, closed.value.rcvd.code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"binary",
        "{",
        json.dumps(
            {
                "protocol_version": "wrong",
                "type": "authenticate",
                "sequence": 0,
                "credential": "x",
                "client_session_id": str(uuid4()),
            }
        ),
        json.dumps(
            {
                "protocol_version": "realtime.v1",
                "type": "wrong",
                "sequence": 0,
                "credential": "x",
                "client_session_id": str(uuid4()),
            }
        ),
        json.dumps(
            {
                "protocol_version": "realtime.v1",
                "type": "authenticate",
                "sequence": 1,
                "credential": "x",
                "client_session_id": str(uuid4()),
            }
        ),
        json.dumps(
            {
                "protocol_version": "realtime.v1",
                "type": "authenticate",
                "sequence": 0,
                "credential": "",
                "client_session_id": str(uuid4()),
            }
        ),
        json.dumps(
            {
                "protocol_version": "realtime.v1",
                "type": "authenticate",
                "sequence": 0,
                "client_session_id": str(uuid4()),
            }
        ),
    ],
)
async def test_authentication_first_frame_negative_matrix(payload: str | bytes) -> None:
    boundary, access_and_sessions, realtime = await _boundary_for_auth()
    access, _ = access_and_sessions
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            assert await _closed_after_first(socket, payload) == 1008
        assert realtime.commands == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_auth_oracle_and_query_credential_are_indistinguishable() -> None:
    boundary, access_and_sessions, realtime = await _boundary_for_auth()
    access, sessions = access_and_sessions
    existing = sessions.open_session(access.credential)
    revoked = sessions.open_session(access.credential)
    sessions.close_session(revoked.id)
    cases = [
        ("wrong", existing.id),
        (access.credential.reveal(), uuid4()),
        (access.credential.reveal(), revoked.id),
    ]
    codes = []
    try:
        for credential, session_id in cases:
            async with websockets.connect(
                f"ws://{access.host}:{access.port}/api/v1/realtime"
            ) as socket:
                payload = json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": str(session_id),
                    }
                )
                codes.append(await _closed_after_first(socket, payload))
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime?credential={access.credential.reveal()}"
        ) as socket:
            codes.append(await _closed_after_first(socket, b"x"))
        assert codes == [1008, 1008, 1008, 1008]
        assert realtime.commands == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_post_auth_revocation_rejects_json_and_binary_without_runtime_calls() -> (
    None
):
    boundary, access_and_sessions, realtime = await _boundary_for_auth()
    access, sessions = access_and_sessions
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": access.credential.reveal(),
                        "client_session_id": str(session.id),
                    }
                )
            )
            assert (await _control(socket))["type"] == "authenticated"
            sessions.close_session(session.id)
            assert (
                await _closed_after_first(
                    socket,
                    json.dumps(
                        {
                            "protocol_version": "realtime.v1",
                            "type": "session.open",
                            "sequence": 1,
                            "conversation_id": str(uuid4()),
                            "locality": "local_only",
                            "cloud_context_eligible": True,
                            "input_audio_format": {
                                "encoding": "pcm16",
                                "sample_rate_hz": 24000,
                                "channels": 1,
                            },
                            "output_audio_format": {
                                "encoding": "pcm16",
                                "sample_rate_hz": 24000,
                                "channels": 1,
                            },
                            "model_override": None,
                        }
                    ),
                )
                == 1008
            )
        assert realtime.commands == [] and realtime.audio == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_post_auth_revocation_rejects_privileged_binary_without_forwarding() -> (
    None
):
    boundary, access_and_sessions, realtime = await _boundary_for_auth()
    access, sessions = access_and_sessions
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": access.credential.reveal(),
                        "client_session_id": str(session.id),
                    }
                )
            )
            assert (await _control(socket))["type"] == "authenticated"
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.open",
                        "sequence": 1,
                        "conversation_id": str(uuid4()),
                        "locality": "local_only",
                        "cloud_context_eligible": True,
                        "input_audio_format": {
                            "encoding": "pcm16",
                            "sample_rate_hz": 24000,
                            "channels": 1,
                        },
                        "output_audio_format": {
                            "encoding": "pcm16",
                            "sample_rate_hz": 24000,
                            "channels": 1,
                        },
                        "model_override": None,
                    }
                )
            )
            opened = await _control(socket)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": opened["realtime_session_id"],
                    }
                )
            )
            assert (await _control(socket))["type"] == "interaction.started"
            sessions.close_session(session.id)
            assert await _closed_after_first(socket, b"revoked-audio") == 1008
        assert realtime.audio == []
    finally:
        await boundary.stop()


def _open_control(sequence: int, **extra: object) -> str:
    payload: dict[str, object] = {
        "protocol_version": "realtime.v1",
        "type": "session.open",
        "sequence": sequence,
        "conversation_id": str(uuid4()),
        "locality": "local_only",
        "cloud_context_eligible": True,
        "input_audio_format": {
            "encoding": "pcm16",
            "sample_rate_hz": 24000,
            "channels": 1,
        },
        "output_audio_format": {
            "encoding": "pcm16",
            "sample_rate_hz": 24000,
            "channels": 1,
        },
        "model_override": None,
    }
    payload.update(extra)
    return json.dumps(payload)


def _input_started_control(
    sequence: int, realtime_session_id: object, **extra: object
) -> str:
    payload: dict[str, object] = {
        "protocol_version": "realtime.v1",
        "type": "input_started",
        "sequence": sequence,
        "realtime_session_id": str(realtime_session_id),
    }
    payload.update(extra)
    return json.dumps(payload)


def _input_committed_control(
    sequence: int, realtime_session_id: object, realtime_interaction_id: object
) -> str:
    return json.dumps(
        {
            "protocol_version": "realtime.v1",
            "type": "input_committed",
            "sequence": sequence,
            "realtime_session_id": str(realtime_session_id),
            "realtime_interaction_id": str(realtime_interaction_id),
        }
    )


def _interaction_control(
    kind: str,
    sequence: int,
    session_id: object,
    interaction_id: object,
    **extra: object,
) -> str:
    payload: dict[str, object] = {
        "protocol_version": "realtime.v1",
        "type": kind,
        "sequence": sequence,
        "realtime_session_id": str(session_id),
        "realtime_interaction_id": str(interaction_id),
    }
    payload.update(extra)
    return json.dumps(payload)


def _input_cancelled_control(
    sequence: int, session_id: object, interaction_id: object, **extra: object
) -> str:
    return _interaction_control(
        "input_cancelled", sequence, session_id, interaction_id, **extra
    )


def _response_interrupt_control(
    sequence: int, session_id: object, interaction_id: object, **extra: object
) -> str:
    return _interaction_control(
        "response.interrupt", sequence, session_id, interaction_id, **extra
    )


async def _authenticated_socket(
    socket: websockets.ClientConnection, access: LocalClientAccess, session_id: object
) -> None:
    await socket.send(
        json.dumps(
            {
                "protocol_version": "realtime.v1",
                "type": "authenticate",
                "sequence": 0,
                "credential": access.credential.reveal(),
                "client_session_id": str(session_id),
            }
        )
    )
    assert (await _control(socket))["type"] == "authenticated"


@pytest.mark.asyncio
async def test_binary_frames_do_not_advance_valid_client_control_sequence() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            opened = await _control(socket)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": opened["realtime_session_id"],
                    }
                )
            )
            started = await _control(socket)
            await socket.send(b"a")
            await socket.send(b"b")
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": opened["realtime_session_id"],
                        "realtime_interaction_id": started["realtime_interaction_id"],
                    }
                )
            )
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert realtime.audio == [b"a", b"b"]
    finally:
        await boundary.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [1, 0, 3])
async def test_duplicate_backward_and_gap_controls_are_rejected(invalid: int) -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            await _control(socket)
            assert await _closed_after_first(socket, _open_control(invalid)) == 1002
        assert len(realtime.commands) == 1
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_client_cannot_supply_realtime_session_id_when_opening_session() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            assert (
                await _closed_after_first(
                    socket,
                    _open_control(1, realtime_session_id=str(uuid4())),
                )
                == 1002
            )
        assert realtime.commands == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_core_realtime_session_id_is_preserved_for_subsequent_calls() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            opened = await _control(socket)
            assert realtime._session_id is not None
            assert opened["realtime_session_id"] == str(realtime._session_id)
            await socket.send(_input_started_control(2, opened["realtime_session_id"]))
            assert (await _control(socket))["type"] == "interaction.started"
        assert realtime.started_sessions == [realtime._session_id]
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_client_cannot_supply_realtime_interaction_id_when_starting_input() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            opened = await _control(socket)
            assert (
                await _closed_after_first(
                    socket,
                    _input_started_control(
                        2,
                        opened["realtime_session_id"],
                        realtime_interaction_id=str(uuid4()),
                    ),
                )
                == 1002
            )
        assert realtime.started_sessions == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_core_interaction_id_is_preserved_and_valid_commit_is_correlated() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            opened = await _control(socket)
            await socket.send(_input_started_control(2, opened["realtime_session_id"]))
            started = await _control(socket)
            assert realtime._interaction_id is not None
            assert started["realtime_interaction_id"] == str(realtime._interaction_id)
            await socket.send(
                _input_committed_control(
                    3,
                    opened["realtime_session_id"],
                    started["realtime_interaction_id"],
                )
            )
            assert (await _control(socket))["type"] == "assistant_output.started"
        assert realtime._session_id is not None
        assert realtime.committed_sessions == [realtime._session_id]
    finally:
        await boundary.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_session_id", [True, False])
async def test_input_committed_rejects_wrong_core_correlation(
    wrong_session_id: bool,
) -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            opened = await _control(socket)
            await socket.send(_input_started_control(2, opened["realtime_session_id"]))
            started = await _control(socket)
            assert (
                await _closed_after_first(
                    socket,
                    _input_committed_control(
                        3,
                        str(uuid4())
                        if wrong_session_id
                        else opened["realtime_session_id"],
                        started["realtime_interaction_id"]
                        if wrong_session_id
                        else str(uuid4()),
                    ),
                )
                == 1002
            )
        assert realtime.committed_sessions == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_duplicate_input_committed_is_rejected_without_second_commit() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _authenticated_socket(socket, access, session.id)
            await socket.send(_open_control(1))
            opened = await _control(socket)
            await socket.send(_input_started_control(2, opened["realtime_session_id"]))
            started = await _control(socket)
            valid_commit = _input_committed_control(
                3,
                opened["realtime_session_id"],
                started["realtime_interaction_id"],
            )
            await socket.send(valid_commit)
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            assert (
                await _closed_after_first(
                    socket,
                    _input_committed_control(
                        4,
                        opened["realtime_session_id"],
                        started["realtime_interaction_id"],
                    ),
                )
                == 1002
            )
        assert len(realtime.committed_sessions) == 1
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_auth_frame_at_4_kib_is_accepted() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            payload = _pad_json(_auth_payload(access, session.id), 4096)
            assert len(payload.encode("utf-8")) == 4096
            await socket.send(payload)
            assert (await _control(socket))["type"] == "authenticated"
        assert realtime.commands == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_auth_frame_over_4_kib_closes_1009_without_runtime_call() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            payload = _pad_json(_auth_payload(access, session.id), 4097)
            assert len(payload.encode("utf-8")) == 4097
            assert await _closed_after_first(socket, payload) == 1009
        assert realtime.commands == [] and realtime.audio == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_normal_control_frame_at_16_kib_is_accepted() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, session.id))
            assert (await _control(socket))["type"] == "authenticated"
            payload = _pad_json(_open_control(1), 16 * 1024)
            assert len(payload.encode("utf-8")) == 16 * 1024
            await socket.send(payload)
            assert (await _control(socket))["type"] == "session.opened"
        assert len(realtime.commands) == 1
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_normal_control_frame_over_16_kib_closes_1009_without_opening() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, session.id))
            assert (await _control(socket))["type"] == "authenticated"
            payload = _pad_json(_open_control(1), 16 * 1024 + 1)
            assert len(payload.encode("utf-8")) == 16 * 1024 + 1
            assert await _closed_after_first(socket, payload) == 1009
        assert realtime.commands == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_frame_exactly_64_kib_is_forwarded_byte_for_byte() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    audio = b"a" * (64 * 1024)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _active_interaction(socket, access, session.id)
            await socket.send(audio)
        assert realtime.audio == [audio]
        assert len(realtime.audio[0]) == 65536
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_frame_over_64_kib_closes_1009_without_forwarding() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _active_interaction(socket, access, session.id)
            audio = b"a" * (64 * 1024 + 1)
            assert await _closed_after_first(socket, audio) == 1009
        assert realtime.audio == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_after_auth_before_session_open_is_rejected() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, session.id))
            assert (await _control(socket))["type"] == "authenticated"
            assert await _closed_after_first(socket, b"before-open") == 1002
        assert realtime.audio == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_after_session_open_before_input_started_is_rejected() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(_auth_payload(access, session.id))
            assert (await _control(socket))["type"] == "authenticated"
            await socket.send(_open_control(1))
            assert (await _control(socket))["type"] == "session.opened"
            assert await _closed_after_first(socket, b"before-input") == 1002
        assert realtime.audio == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_during_active_interaction_is_forwarded_exactly_once() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    audio = b"valid-audio"
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _active_interaction(socket, access, session.id)
            await socket.send(audio)
        assert realtime.audio == [audio]
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_after_input_committed_is_rejected_without_forwarding() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(socket, access, session.id)
            await socket.send(b"first-audio")
            await socket.send(
                _input_committed_control(
                    3,
                    opened["realtime_session_id"],
                    started["realtime_interaction_id"],
                )
            )
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            assert await _closed_after_first(socket, b"after-commit") == 1002
        assert realtime.audio == [b"first-audio"]
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_binary_after_terminal_interaction_is_rejected_without_forwarding() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _active_interaction(socket, access, session.id)
            await realtime.fail_interaction()
            assert (await _control(socket))["type"] == "interaction.failed"
            assert await _closed_after_first(socket, b"after-terminal") == 1002
        assert realtime.audio == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_input_cancelled_calls_core_once_and_allows_new_input() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = opened["realtime_session_id"]
            interaction_id = started["realtime_interaction_id"]
            await socket.send(_input_cancelled_control(3, session_id, interaction_id))
            await socket.send(_input_started_control(4, session_id))
            replacement = await _control(socket)
            assert replacement["type"] == "interaction.started"
            assert len(realtime.cancelled) == 1
            assert str(realtime.cancelled[0][0]) == str(session_id)
            assert str(realtime.cancelled[0][1]) == str(interaction_id)
            assert realtime.interrupted == []
            assert len(realtime.started_sessions) == 2
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_input_cancelled_after_commit_is_protocol_rejected() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = opened["realtime_session_id"]
            interaction_id = started["realtime_interaction_id"]
            await socket.send(_input_committed_control(3, session_id, interaction_id))
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            assert (
                await _closed_after_first(
                    socket,
                    _input_cancelled_control(4, session_id, interaction_id),
                )
                == 1002
            )
        assert realtime.cancelled == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_response_interrupt_calls_core_once_and_allows_new_input() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = opened["realtime_session_id"]
            interaction_id = started["realtime_interaction_id"]
            await socket.send(_input_committed_control(3, session_id, interaction_id))
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            await socket.send(
                _response_interrupt_control(4, session_id, interaction_id)
            )
            await socket.send(_input_started_control(5, session_id))
            replacement = await _control(socket)
            assert replacement["type"] == "interaction.started"
            assert len(realtime.interrupted) == 1
            assert str(realtime.interrupted[0][0]) == str(session_id)
            assert str(realtime.interrupted[0][1]) == str(interaction_id)
            assert realtime.cancelled == []
            assert len(realtime.started_sessions) == 2
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_response_interrupt_before_commit_is_protocol_rejected() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            assert (
                await _closed_after_first(
                    socket,
                    _response_interrupt_control(
                        3,
                        opened["realtime_session_id"],
                        started["realtime_interaction_id"],
                    ),
                )
                == 1002
            )
        assert realtime.interrupted == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_committed_input_started_uses_core_barge_in_without_explicit_interrupt() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = opened["realtime_session_id"]
            old_id = started["realtime_interaction_id"]
            await socket.send(_input_committed_control(3, session_id, old_id))
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            await socket.send(_input_started_control(4, session_id))
            replacement = await _control(socket)
            new_id = replacement["realtime_interaction_id"]
            assert new_id != old_id
            assert realtime.interrupted == []
            await socket.send(b"new-audio")
        assert realtime.audio == [b"new-audio"]
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_uncommitted_second_input_started_is_rejected_without_core_calls() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, _ = await _active_interaction(socket, access, client_session.id)
            assert (
                await _closed_after_first(
                    socket,
                    _input_started_control(3, opened["realtime_session_id"]),
                )
                == 1002
            )
        assert len(realtime.started_sessions) == 1
        assert realtime.interrupted == []
        assert realtime.cancelled == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_old_turn_terminal_does_not_clear_new_interaction() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = RealtimeSessionId(UUID(str(opened["realtime_session_id"])))
            old_id = RealtimeInteractionId(
                UUID(str(started["realtime_interaction_id"]))
            )
            conversation_id = realtime.commands[0].conversation_id
            await realtime.emit(
                RealtimeUserTranscriptFinal(session_id, old_id, 1, "old input")
            )
            old_turn = _turn_snapshot(conversation_id, TurnStatus.PROCESSING)
            await realtime.emit(
                ConversationTurnStarted(
                    Conversation(conversation_id, datetime.now(UTC), datetime.now(UTC)),
                    old_turn,
                )
            )
            assert (await _control(socket))["type"] == "user_transcript.final"
            assert (await _control(socket))["type"] == "turn.started"
            await socket.send(
                _input_committed_control(3, opened["realtime_session_id"], old_id)
            )
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            await socket.send(_input_started_control(4, opened["realtime_session_id"]))
            replacement = await _control(socket)
            new_id = RealtimeInteractionId(
                UUID(str(replacement["realtime_interaction_id"]))
            )
            finished_at = datetime.now(UTC)
            interrupted_turn = replace(
                old_turn,
                status=TurnStatus.INTERRUPTED,
                assistant_text="",
                updated_at=finished_at,
                finished_at=finished_at,
            )
            await realtime.emit(
                ConversationTurnInterrupted(
                    Conversation(conversation_id, datetime.now(UTC), datetime.now(UTC)),
                    interrupted_turn,
                )
            )
            assert (await _control(socket))["type"] == "turn.interrupted"
            await socket.send(b"new-audio")
        assert realtime.audio[-1] == b"new-audio"
        assert new_id != old_id
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_old_interaction_failure_does_not_clear_new_interaction() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = RealtimeSessionId(UUID(str(opened["realtime_session_id"])))
            old_id = RealtimeInteractionId(
                UUID(str(started["realtime_interaction_id"]))
            )
            await socket.send(_input_committed_control(3, session_id, old_id))
            assert (await _control(socket))["type"] == "assistant_output.started"
            assert await socket.recv() == b"assistant"
            await socket.send(_input_started_control(4, session_id))
            replacement = await _control(socket)
            new_id = RealtimeInteractionId(
                UUID(str(replacement["realtime_interaction_id"]))
            )
            await realtime.emit(
                RealtimeInteractionFailed(session_id, old_id, "old failure")
            )
            failure = await _control(socket)
            assert failure["type"] == "interaction.failed"
            await socket.send(b"new-audio")
        assert realtime.audio[-1] == b"new-audio"
        assert new_id != old_id
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_new_interaction_terminal_clears_new_state() -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = RealtimeSessionId(UUID(str(opened["realtime_session_id"])))
            interaction_id = RealtimeInteractionId(
                UUID(str(started["realtime_interaction_id"]))
            )
            await realtime.emit(
                RealtimeInteractionFailed(session_id, interaction_id, "new failure")
            )
            assert (await _control(socket))["type"] == "interaction.failed"
            assert await _closed_after_first(socket, b"after-terminal") == 1002
    finally:
        await boundary.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["input_cancelled", "response.interrupt"])
@pytest.mark.parametrize(
    "variant", ["missing", "extra", "wrong_session", "wrong_interaction"]
)
async def test_new_controls_remain_strict_and_fail_closed(
    kind: str, variant: str
) -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = opened["realtime_session_id"]
            interaction_id = started["realtime_interaction_id"]
            if kind == "response.interrupt":
                await socket.send(
                    _input_committed_control(3, session_id, interaction_id)
                )
                assert (await _control(socket))["type"] == "assistant_output.started"
                assert await socket.recv() == b"assistant"
                sequence = 4
            else:
                sequence = 3
            payload = json.loads(
                _interaction_control(kind, sequence, session_id, interaction_id)
            )
            if variant == "missing":
                del payload["realtime_interaction_id"]
            elif variant == "extra":
                payload["unexpected"] = True
            elif variant == "wrong_session":
                payload["realtime_session_id"] = str(uuid4())
            else:
                payload["realtime_interaction_id"] = str(uuid4())
            assert await _closed_after_first(socket, json.dumps(payload)) == 1002
        assert realtime.cancelled == []
        assert realtime.interrupted == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["input_cancelled", "response.interrupt"])
async def test_new_controls_recheck_revoked_client_session(kind: str) -> None:
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            opened, started = await _active_interaction(
                socket, access, client_session.id
            )
            session_id = opened["realtime_session_id"]
            interaction_id = started["realtime_interaction_id"]
            if kind == "response.interrupt":
                await socket.send(
                    _input_committed_control(3, session_id, interaction_id)
                )
                assert (await _control(socket))["type"] == "assistant_output.started"
                assert await socket.recv() == b"assistant"
                sequence = 4
            else:
                sequence = 3
            sessions.close_session(client_session.id)
            payload = (
                _input_cancelled_control
                if kind == "input_cancelled"
                else _response_interrupt_control
            )(sequence, session_id, interaction_id)
            assert await _closed_after_first(socket, payload) == 1008
        assert realtime.cancelled == []
        assert realtime.interrupted == []
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_core_session_failed_delivers_terminal_event_and_closes_idle_socket() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _opened_session(socket, access, client_session.id)
            assert realtime._session_id is not None
            await realtime.emit(
                ConversationRealtimeSessionFailed(realtime._session_id, "safe failure")
            )
            payload = await _control(socket)
            assert payload["type"] == "session.failed"
            assert payload["message"] == "safe failure"
            with pytest.raises(ConnectionClosed):
                await socket.recv()
        assert realtime.closed == []
        assert realtime.events_finished == 1
        assert realtime.events_done.is_set()
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_core_session_closed_delivers_terminal_event_and_closes_idle_socket() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth()
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _opened_session(socket, access, client_session.id)
            assert realtime._session_id is not None
            await realtime.emit(RealtimeSessionClosed(realtime._session_id))
            payload = await _control(socket)
            assert payload["type"] == "session.closed"
            with pytest.raises(ConnectionClosed):
                await socket.recv()
        assert realtime.closed == []
        assert realtime.events_finished == 1
        assert realtime.events_done.is_set()
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_unexpected_event_stream_end_closes_owned_session_once() -> None:
    boundary, pair, realtime = await _boundary_for_auth(stream_end=True)
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _opened_session(socket, access, client_session.id)
            await realtime.events_done.wait()
            payload = await _control(socket)
            assert payload["type"] == "error"
            assert payload["code"] == "internal_realtime_error"
            with pytest.raises(ConnectionClosed):
                await socket.recv()
        assert realtime._session_id is not None
        assert realtime.closed == [realtime._session_id]
        assert realtime.events_finished == 1
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_unexpected_event_stream_error_is_safe_and_closes_owned_session_once() -> (
    None
):
    boundary, pair, realtime = await _boundary_for_auth(
        stream_error=RuntimeError("sensitive internal sender failure")
    )
    access, sessions = pair
    client_session = sessions.open_session(access.credential)
    try:
        async with websockets.connect(
            f"ws://{access.host}:{access.port}/api/v1/realtime"
        ) as socket:
            await _opened_session(socket, access, client_session.id)
            await realtime.events_done.wait()
            payload = await _control(socket)
            assert payload["type"] == "error"
            assert payload["code"] == "internal_realtime_error"
            assert "sensitive internal sender failure" not in json.dumps(payload)
            with pytest.raises(ConnectionClosed):
                await socket.recv()
        assert realtime._session_id is not None
        assert realtime.closed == [realtime._session_id]
        assert realtime.events_finished == 1
    finally:
        await boundary.stop()
