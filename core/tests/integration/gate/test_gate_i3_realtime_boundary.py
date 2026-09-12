"""Gate I3: real SofiaCore realtime voice vertical over HTTP and WebSocket loopback."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest
import websockets

from sofias_assistant.ai.contracts import (
    AudioEncoding,
    AudioFormat,
    Capability,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ProviderError,
    ProviderErrorCategory,
)
from sofias_assistant.ai.registry import (
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.client_boundary.boundary import LocalClientBoundary
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.conversation.models import TurnInputModality, TurnStatus
from sofias_assistant.core import ConversationRuntimeDependencies, CoreState, SofiaCore
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService

from ...support.ai import (
    FakeStreamCompleted,
    FakeStreamScript,
    FakeTextDelta,
    ScriptedFakeProvider,
)
from ...support.realtime import (
    FakeAssistantAudioChunk,
    FakeAssistantTranscriptFinal,
    FakeAssistantTranscriptPartial,
    FakeRealtimeBarrier,
    FakeRealtimeCompleted,
    FakeRealtimePause,
    FakeRealtimeScript,
    FakeRealtimeSessionFailed,
    FakeUserTranscriptFinal,
    ScriptedFakeRealtimeProvider,
)


class FakeSecretStore:
    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


class FakeOwnership:
    def acquire(self) -> None:
        return None

    def release(self) -> None:
        return None


def _format() -> AudioFormat:
    return AudioFormat(AudioEncoding.PCM16, 24_000, 1)


def _format_wire(value: AudioFormat) -> dict[str, object]:
    return {
        "encoding": value.encoding.value,
        "sample_rate_hz": value.sample_rate_hz,
        "channels": value.channels,
    }


def _dependencies_factory(
    provider: ScriptedFakeRealtimeProvider,
    text_provider: ScriptedFakeProvider | None = None,
) -> Callable[[SecretService], ConversationRuntimeDependencies]:
    def factory(_: SecretService) -> ConversationRuntimeDependencies:
        registry = ModelRegistry()
        registry.register(
            ModelRegistration(
                descriptor=ModelDescriptor(
                    identity=ModelIdentity("fake", "realtime"),
                    capabilities=frozenset(
                        {
                            Capability.REALTIME,
                            Capability.AUDIO_INPUT,
                            Capability.AUDIO_OUTPUT,
                            *(
                                {Capability.TEXT_STREAMING}
                                if text_provider is not None
                                else set()
                            ),
                        }
                    ),
                    execution_location=ExecutionLocation.LOCAL,
                    context_window=4096,
                ),
                binding=ProviderBinding(
                    realtime=provider,
                    text_streaming=text_provider,
                ),
            )
        )
        return ConversationRuntimeDependencies(
            router=CapabilityRouter(registry),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext("Core system context", True),
                max_recent_turns=1,
                max_estimated_input_tokens=10_000,
            ),
        )

    return factory


def _core(
    data_dir: Path,
    provider: ScriptedFakeRealtimeProvider,
    text_provider: ScriptedFakeProvider | None = None,
) -> SofiaCore:
    return SofiaCore(
        RuntimeConfig(paths=AppPaths(data_dir=data_dir)),
        application_version="0.1.0.dev0",
        secret_store_factory=FakeSecretStore,
        instance_ownership_factory=lambda _: FakeOwnership(),
        conversation_dependencies_factory=_dependencies_factory(
            provider, text_provider
        ),
    )


async def _request(
    port: int,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    payload: object | None = None,
) -> tuple[int, bytes, bytes]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {
        "Host": "127.0.0.1",
        "Connection": "close",
        **(headers or {}),
        "Content-Length": str(len(body)),
    }
    if body:
        request_headers["Content-Type"] = "application/json"
    head = "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(f"{method} {path} HTTP/1.1\r\n{head}\r\n".encode() + body)
        await writer.drain()
        response = await reader.read()
    finally:
        writer.close()
        await writer.wait_closed()
    raw_head, raw_body = response.split(b"\r\n\r\n", maxsplit=1)
    if b"transfer-encoding: chunked" in raw_head.lower():
        raw_body = _decode_chunked(raw_body)
    return int(raw_head.split(maxsplit=2)[1]), raw_body, raw_head


def _decode_chunked(raw_body: bytes) -> bytes:
    decoded = bytearray()
    remainder = raw_body
    while True:
        size_line, remainder = remainder.split(b"\r\n", maxsplit=1)
        size = int(size_line, 16)
        if size == 0:
            return bytes(decoded)
        decoded.extend(remainder[:size])
        remainder = remainder[size + 2 :]


async def _control(socket: websockets.ClientConnection) -> dict[str, object]:
    value = await socket.recv()
    assert isinstance(value, str)
    payload = json.loads(value)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.asyncio
async def test_gate_i3_real_sofia_core_realtime_voice_loopback(tmp_path: Path) -> None:
    release_provider = asyncio.Event()
    input_audio = b"\x01\x02\x03\x04REAL-VOICE"
    assistant_audio = b"\x10\x20ASSISTANT-AUDIO"
    provider = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("mensagem de voz real"),
                    FakeRealtimePause(release_provider),
                    FakeAssistantAudioChunk(assistant_audio, _format()),
                    FakeAssistantTranscriptFinal("resposta de voz real"),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    core = _core(tmp_path / "core-data", provider)
    boundary: LocalClientBoundary | None = None
    conversation_id: UUID | None = None
    try:
        await core.start()
        assert core.state is CoreState.RUNNING
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()

        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])

        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
                    }
                )
            )
            authenticated = await _control(socket)
            assert authenticated["type"] == "authenticated"
            assert authenticated["sequence"] == 0
            assert "credential" not in authenticated

            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.open",
                        "sequence": 1,
                        "conversation_id": str(conversation_id),
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
            session_id = UUID(str(opened["realtime_session_id"]))
            assert provider.opens()[0].request.realtime_session_id == session_id
            assert opened["conversation_id"] == str(conversation_id)

            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": str(session_id),
                    }
                )
            )
            started = await _control(socket)
            assert started["type"] == "interaction.started"
            interaction_id = UUID(str(started["realtime_interaction_id"]))

            await socket.send(input_audio)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": str(session_id),
                        "realtime_interaction_id": str(interaction_id),
                    }
                )
            )
            provider_session = provider.sessions()[0]
            release_provider.set()

            observed: list[dict[str, object] | bytes] = []
            while True:
                item = await socket.recv()
                if isinstance(item, bytes):
                    observed.append(item)
                    continue
                payload = json.loads(item)
                assert isinstance(payload, dict)
                observed.append(payload)
                if payload["type"] == "turn.completed":
                    break

            types = [
                item["type"] if isinstance(item, dict) else "binary"
                for item in observed
            ]
            assert types == [
                "user_transcript.final",
                "turn.started",
                "assistant_output.started",
                "binary",
                "assistant_transcript.final",
                "turn.completed",
            ]
            controls = [item for item in observed if isinstance(item, dict)]
            assert [item["sequence"] for item in controls] == [3, 4, 5, 6, 7]
            user_event, turn_started_event, audio_started_event = observed[:3]
            assistant_transcript_event, turn_completed_event = observed[4:]
            assert isinstance(user_event, dict)
            assert isinstance(turn_started_event, dict)
            assert isinstance(audio_started_event, dict)
            assert isinstance(assistant_transcript_event, dict)
            assert isinstance(turn_completed_event, dict)
            turn_started_wire = turn_started_event.get("turn")
            turn_completed_wire = turn_completed_event.get("turn")
            assert isinstance(turn_started_wire, dict)
            assert isinstance(turn_completed_wire, dict)
            assert user_event["text"] == "mensagem de voz real"
            assert turn_started_wire["status"] == "PROCESSING"
            assert audio_started_event["type"] == "assistant_output.started"
            assert observed[3] == assistant_audio
            assert assistant_transcript_event["text"] == "resposta de voz real"
            assert turn_completed_wire["status"] == "COMPLETED"

            assert provider_session.frames()[0].audio == input_audio
            assert provider_session.frames()[0].sequence == 0
            assert provider_session.commits() == (interaction_id,)

            state = await core.conversation_runtime.get_conversation_state(
                conversation_id
            )
            assert len(state.turns) == 1
            turn = state.turns[0]
            assert turn.input_modality is TurnInputModality.VOICE
            assert turn.status is TurnStatus.COMPLETED
            assert turn.user_text == "mensagem de voz real"
            assert turn.assistant_text == "resposta de voz real"
            assert (turn.provider_id, turn.model_id) == ("fake", "realtime")
            assert not hasattr(turn, "input_audio")
            assert not hasattr(turn, "assistant_audio")
            assert input_audio.decode("latin1") not in repr(turn)
            assert assistant_audio.decode("latin1") not in repr(turn)

            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 4,
                        "realtime_session_id": str(session_id),
                    }
                )
            )
        assert provider_session.close_calls == 1
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_gate_i3_http_ndjson_coexists_with_realtime_route(tmp_path: Path) -> None:
    realtime_provider = ScriptedFakeRealtimeProvider()
    text_provider = ScriptedFakeProvider(
        stream_scripts=(
            FakeStreamScript(
                items=(
                    FakeTextDelta("text coexistence response"),
                    FakeStreamCompleted(),
                )
            ),
        )
    )
    core = _core(tmp_path / "core-data", realtime_provider, text_provider)
    boundary: LocalClientBoundary | None = None
    try:
        await core.start()
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])
        status, ndjson_body, response_head = await _request(
            access.port,
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=headers,
            payload={
                "text": "text coexistence request",
                "locality": "local_only",
                "cloud_context_eligible": True,
            },
        )
        assert status == 200
        assert b"content-type: application/x-ndjson" in response_head.lower()
        records = [
            json.loads(line)
            for line in ndjson_body.decode("utf-8").splitlines()
            if line
        ]
        assert [record["type"] for record in records] == [
            "turn_started",
            "text_delta",
            "turn_completed",
        ]
        assert records[1]["text"] == "text coexistence response"
        state_status, state_body, _ = await _request(
            access.port,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
            headers=headers,
        )
        assert state_status == 200
        state = json.loads(state_body)
        assert state["turns"][0]["status"] == "COMPLETED"
        assert state["turns"][0]["user_text"] == "text coexistence request"
        missing_auth_status, _missing_body, _ = await _request(
            access.port,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
        )
        assert missing_auth_status == 401
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_gate_i3_real_input_cancelled_and_reuse(tmp_path: Path) -> None:
    provider = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript(()), FakeRealtimeScript(()))
    )
    core = _core(tmp_path / "core-data", provider)
    boundary: LocalClientBoundary | None = None
    try:
        await core.start()
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])
        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
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
                        "conversation_id": str(conversation_id),
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
            session_id = str(opened["realtime_session_id"])
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": session_id,
                    }
                )
            )
            started = await _control(socket)
            interaction_id = str(started["realtime_interaction_id"])
            await socket.send(b"cancelled-audio")
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_cancelled",
                        "sequence": 3,
                        "realtime_session_id": session_id,
                        "realtime_interaction_id": interaction_id,
                    }
                )
            )
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 4,
                        "realtime_session_id": session_id,
                    }
                )
            )
            replacement = await _control(socket)
            assert replacement["type"] == "interaction.started"
            assert replacement["realtime_interaction_id"] != interaction_id
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 5,
                        "realtime_session_id": session_id,
                    }
                )
            )
        provider_session = provider.sessions()[0]
        assert provider_session.interrupts() == (UUID(interaction_id),)
        state = await core.conversation_runtime.get_conversation_state(conversation_id)
        assert state.turns == ()
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_gate_i3_real_response_interrupt_pre_transcript_and_reuse(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    provider = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript((FakeRealtimeBarrier(entered, release),)),
            FakeRealtimeScript(()),
        )
    )
    core = _core(tmp_path / "core-data", provider)
    boundary: LocalClientBoundary | None = None
    try:
        await core.start()
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])
        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
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
                        "conversation_id": str(conversation_id),
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
            session_id = str(opened["realtime_session_id"])
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": session_id,
                    }
                )
            )
            started = await _control(socket)
            interaction_id = str(started["realtime_interaction_id"])
            await entered.wait()
            await socket.send(b"interrupt-audio")
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": session_id,
                        "realtime_interaction_id": interaction_id,
                    }
                )
            )
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "response.interrupt",
                        "sequence": 4,
                        "realtime_session_id": session_id,
                        "realtime_interaction_id": interaction_id,
                    }
                )
            )
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 5,
                        "realtime_session_id": session_id,
                    }
                )
            )
            replacement = await _control(socket)
            assert replacement["type"] == "interaction.started"
            release.set()
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 6,
                        "realtime_session_id": session_id,
                    }
                )
            )
        provider_session = provider.sessions()[0]
        assert provider_session.interrupts() == (UUID(interaction_id),)
        state = await core.conversation_runtime.get_conversation_state(conversation_id)
        assert state.turns == ()
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_gate_i3_real_automatic_barge_in_old_terminal_and_new_completion(
    tmp_path: Path,
) -> None:
    old_entered = asyncio.Event()
    old_release = asyncio.Event()
    new_entered = asyncio.Event()
    new_release = asyncio.Event()
    old_audio = b"OLD-AUDIO"
    new_audio = b"NEW-AUDIO-EXACT"
    old_input = b"OLD-INPUT"
    new_input = b"NEW-INPUT"
    provider = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("mensagem antiga"),
                    FakeAssistantAudioChunk(old_audio, _format()),
                    FakeAssistantTranscriptPartial("parcial antigo"),
                    FakeRealtimeBarrier(old_entered, old_release),
                    FakeAssistantAudioChunk(b"OLD-LATE-AUDIO", _format()),
                    FakeAssistantTranscriptPartial(" late old"),
                    FakeAssistantTranscriptFinal("late old final"),
                    FakeRealtimeCompleted(),
                )
            ),
            FakeRealtimeScript(
                (
                    FakeRealtimeBarrier(new_entered, new_release),
                    FakeUserTranscriptFinal("mensagem nova"),
                    FakeAssistantAudioChunk(new_audio, _format()),
                    FakeAssistantTranscriptFinal("resposta nova"),
                    FakeRealtimeCompleted(),
                )
            ),
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("terceira mensagem"),
                    FakeAssistantTranscriptFinal("terceira resposta"),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    core = _core(tmp_path / "core-data", provider)
    boundary: LocalClientBoundary | None = None
    try:
        await core.start()
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])
        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
                    }
                )
            )
            wire_controls: list[dict[str, object]] = []
            wire_items: list[dict[str, object] | bytes] = []

            def record(value: dict[str, object] | bytes) -> None:
                wire_items.append(value)
                if isinstance(value, dict):
                    wire_controls.append(value)

            record(await _control(socket))
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.open",
                        "sequence": 1,
                        "conversation_id": str(conversation_id),
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
            record(opened)
            session_id = str(opened["realtime_session_id"])
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": session_id,
                    }
                )
            )
            started_old = await _control(socket)
            record(started_old)
            old_id = str(started_old["realtime_interaction_id"])
            await socket.send(old_input)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": session_id,
                        "realtime_interaction_id": old_id,
                    }
                )
            )
            old_audio_seen = False
            seen_old_processing = False
            while not (old_entered.is_set() and seen_old_processing and old_audio_seen):
                item = await socket.recv()
                if isinstance(item, bytes):
                    record(item)
                    old_audio_seen = item == old_audio
                    continue
                payload = json.loads(item)
                assert isinstance(payload, dict)
                record(payload)
                if payload["type"] == "turn.started":
                    turn = payload["turn"]
                    assert isinstance(turn, dict)
                    assert turn["status"] == "PROCESSING"
                    seen_old_processing = True
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 4,
                        "realtime_session_id": session_id,
                    }
                )
            )
            seen_new = False
            seen_old_interrupted = False
            while not (seen_new and seen_old_interrupted):
                item = await socket.recv()
                if isinstance(item, bytes):
                    record(item)
                    continue
                payload = json.loads(item)
                assert isinstance(payload, dict)
                record(payload)
                seen_new |= payload["type"] == "interaction.started"
                seen_old_interrupted |= payload["type"] == "turn.interrupted"
            new_id = str(
                next(
                    item["realtime_interaction_id"]
                    for item in wire_controls
                    if item["type"] == "interaction.started"
                    and item["realtime_interaction_id"] != old_id
                )
            )
            assert new_id != old_id
            await new_entered.wait()
            await socket.send(new_input)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 5,
                        "realtime_session_id": session_id,
                        "realtime_interaction_id": new_id,
                    }
                )
            )
            old_release.set()
            new_release.set()
            while True:
                item = await socket.recv()
                if isinstance(item, bytes):
                    record(item)
                    continue
                payload = json.loads(item)
                assert isinstance(payload, dict)
                record(payload)
                if payload["type"] == "turn.completed":
                    break
        assert provider.sessions()[0].interrupts() == (UUID(old_id),)
        assert provider.sessions()[0].frames()[0].audio == old_input
        assert provider.sessions()[1].frames()[0].audio == new_input
        assert provider.sessions()[1].commits() == (UUID(new_id),)
        assert not any(
            item == b"OLD-LATE-AUDIO"
            or (isinstance(item, dict) and "late old" in json.dumps(item))
            for item in wire_items
            if isinstance(item, (bytes, dict))
        )
        new_audio_positions = [
            index
            for index, item in enumerate(wire_items)
            if isinstance(item, bytes) and item == new_audio
        ]
        assert len(new_audio_positions) == 1
        new_started_positions = [
            index
            for index, item in enumerate(wire_items)
            if isinstance(item, dict)
            and item["type"] == "assistant_output.started"
            and item["realtime_interaction_id"] == new_id
        ]
        assert len(new_started_positions) == 1
        assert new_started_positions[0] < new_audio_positions[0]
        assert [
            item["type"] for item in wire_controls if item["type"] == "turn.completed"
        ] == ["turn.completed"]
        assert [item["sequence"] for item in wire_controls] == list(
            range(len(wire_controls))
        )
        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as followup:
            await followup.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
                    }
                )
            )
            assert (await _control(followup))["type"] == "authenticated"
            await followup.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.open",
                        "sequence": 1,
                        "conversation_id": str(conversation_id),
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
            followup_opened = await _control(followup)
            followup_session_id = str(followup_opened["realtime_session_id"])
            await followup.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": followup_session_id,
                    }
                )
            )
            third_started = await _control(followup)
            third_id = str(third_started["realtime_interaction_id"])
            await followup.send(b"THIRD-INPUT")
            await followup.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": followup_session_id,
                        "realtime_interaction_id": third_id,
                    }
                )
            )
            while True:
                item = await followup.recv()
                if isinstance(item, bytes):
                    continue
                payload = json.loads(item)
                assert isinstance(payload, dict)
                if payload["type"] == "turn.completed":
                    break
            await followup.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 4,
                        "realtime_session_id": followup_session_id,
                    }
                )
            )
        state = await core.conversation_runtime.get_conversation_state(conversation_id)
        assert len(state.turns) == 3
        old_turn, new_turn, third_turn = state.turns
        assert old_turn.status is TurnStatus.INTERRUPTED
        assert old_turn.user_text == "mensagem antiga"
        assert old_turn.assistant_text == "parcial antigo"
        assert new_turn.status is TurnStatus.COMPLETED
        assert new_turn.user_text == "mensagem nova"
        assert new_turn.assistant_text == "resposta nova"
        assert state.turns[2].user_text == "terceira mensagem"
        assert state.turns[2].assistant_text == "terceira resposta"
        assert third_turn.status is TurnStatus.COMPLETED
        assert old_turn.conversation_id == new_turn.conversation_id == conversation_id
        assert old_turn.sequence == 1
        assert new_turn.sequence == 2
        assert third_turn.sequence == 3
        assert not hasattr(old_turn, "input_audio")
        assert not hasattr(new_turn, "assistant_audio")
        assert "OLD-AUDIO" not in repr(old_turn)
        assert "NEW-AUDIO" not in repr(new_turn)
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_gate_i3_real_post_transcript_session_loss_closes_and_allows_reopen(
    tmp_path: Path,
) -> None:
    failure_entered = asyncio.Event()
    release_failure = asyncio.Event()
    safe_message = "safe provider session failure"
    input_before_failure = b"VOICE-BEFORE-FAILURE"
    input_after_failure = b"VOICE-AFTER-FAILURE"
    provider = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("fala antes da queda"),
                    FakeAssistantTranscriptPartial("resposta parcial"),
                    FakeRealtimeBarrier(failure_entered, release_failure),
                    FakeRealtimeSessionFailed(
                        ProviderError(
                            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                            safe_message,
                            False,
                        )
                    ),
                )
            ),
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("fala depois da queda"),
                    FakeAssistantTranscriptFinal("resposta depois da queda"),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    core = _core(tmp_path / "core-data", provider)
    boundary: LocalClientBoundary | None = None
    try:
        await core.start()
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])

        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
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
                        "conversation_id": str(conversation_id),
                        "locality": "local_only",
                        "cloud_context_eligible": True,
                        "input_audio_format": _format_wire(_format()),
                        "output_audio_format": _format_wire(_format()),
                        "model_override": None,
                    }
                )
            )
            opened = await _control(socket)
            failed_session_id = str(opened["realtime_session_id"])
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": failed_session_id,
                    }
                )
            )
            started = await _control(socket)
            interaction_id = str(started["realtime_interaction_id"])
            await socket.send(input_before_failure)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": failed_session_id,
                        "realtime_interaction_id": interaction_id,
                    }
                )
            )

            before_failure: list[dict[str, object]] = []
            while not any(item["type"] == "turn.started" for item in before_failure):
                before_failure.append(await _control(socket))
            await failure_entered.wait()
            state = await core.conversation_runtime.get_conversation_state(
                conversation_id
            )
            assert state.turns[0].status is TurnStatus.PROCESSING

            release_failure.set()
            terminal: list[dict[str, object]] = []
            while True:
                payload = await _control(socket)
                terminal.append(payload)
                if payload["type"] == "session.failed":
                    break
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await socket.recv()

        terminal_types = [payload["type"] for payload in terminal]
        assert terminal_types[-2:] == ["turn.failed", "session.failed"]
        assert "turn.interrupted" not in terminal_types
        assert "turn.completed" not in terminal_types
        assert "session.closed" not in terminal_types
        session_failed = terminal[-1]
        assert session_failed["message"] == safe_message
        assert "SECRET" not in json.dumps(terminal)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1000
        assert provider.sessions()[0].close_calls == 1

        state = await core.conversation_runtime.get_conversation_state(conversation_id)
        assert len(state.turns) == 1
        failed_turn = state.turns[0]
        assert failed_turn.input_modality is TurnInputModality.VOICE
        assert failed_turn.status is TurnStatus.FAILED
        assert failed_turn.user_text == "fala antes da queda"
        assert failed_turn.assistant_text == "resposta parcial"
        assert (failed_turn.provider_id, failed_turn.model_id) == ("fake", "realtime")
        assert failed_turn.finished_at is not None
        assert not hasattr(failed_turn, "input_audio")
        assert not hasattr(failed_turn, "assistant_audio")
        assert not hasattr(failed_turn, "assistant_transcript_partial")
        assert failed_turn.provider_session_id is None
        assert "VOICE-BEFORE-FAILURE" not in repr(failed_turn)

        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
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
                        "conversation_id": str(conversation_id),
                        "locality": "local_only",
                        "cloud_context_eligible": True,
                        "input_audio_format": _format_wire(_format()),
                        "output_audio_format": _format_wire(_format()),
                        "model_override": None,
                    }
                )
            )
            reopened = await _control(socket)
            reopened_session_id = str(reopened["realtime_session_id"])
            assert reopened_session_id != failed_session_id
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": reopened_session_id,
                    }
                )
            )
            restarted = await _control(socket)
            restarted_interaction_id = str(restarted["realtime_interaction_id"])
            await socket.send(input_after_failure)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": reopened_session_id,
                        "realtime_interaction_id": restarted_interaction_id,
                    }
                )
            )
            recovered: list[dict[str, object]] = []
            while not any(item["type"] == "turn.completed" for item in recovered):
                recovered.append(await _control(socket))
            assert [item["type"] for item in recovered] == [
                "user_transcript.final",
                "turn.started",
                "assistant_transcript.final",
                "turn.completed",
            ]
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 4,
                        "realtime_session_id": reopened_session_id,
                    }
                )
            )
            assert (await _control(socket)) == {
                "protocol_version": "realtime.v1",
                "type": "session.closed",
                "sequence": 7,
                "realtime_session_id": reopened_session_id,
            }
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await socket.recv()
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 1000

        assert provider.sessions()[1].frames()[0].audio == input_after_failure
        assert provider.sessions()[1].close_calls == 1
        final_state = await core.conversation_runtime.get_conversation_state(
            conversation_id
        )
        assert len(final_state.turns) == 2
        first, second = final_state.turns
        assert (first.status, second.status) == (
            TurnStatus.FAILED,
            TurnStatus.COMPLETED,
        )
        assert first.user_text == "fala antes da queda"
        assert first.assistant_text == "resposta parcial"
        assert second.user_text == "fala depois da queda"
        assert second.assistant_text == "resposta depois da queda"
        assert not hasattr(second, "input_audio")
        assert not hasattr(second, "assistant_audio")
        assert second.provider_session_id is None
        assert "VOICE-AFTER-FAILURE" not in repr(second)
        assert first.conversation_id == second.conversation_id == conversation_id
        assert (first.sequence, second.sequence) == (1, 2)
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()


@pytest.mark.asyncio
async def test_gate_i3_real_pre_transcript_session_loss_creates_no_turn(
    tmp_path: Path,
) -> None:
    failure_entered = asyncio.Event()
    release_failure = asyncio.Event()
    provider = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeRealtimeBarrier(failure_entered, release_failure),
                    FakeRealtimeSessionFailed(
                        ProviderError(
                            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                            "safe pre-transcript failure",
                            False,
                        )
                    ),
                )
            ),
            FakeRealtimeScript(()),
        )
    )
    core = _core(tmp_path / "core-data", provider)
    boundary: LocalClientBoundary | None = None
    try:
        await core.start()
        boundary = LocalClientBoundary(
            port=0,
            app_factory=lambda authenticator, sessions: create_local_http_app(
                authenticator,
                sessions,
                core=core,
                conversation=core.conversation_runtime,
                realtime=core.realtime_conversation_runtime,
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body, _ = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        client_session_id = json.loads(body)["id"]
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": client_session_id,
        }
        status, body, _ = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])

        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
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
                        "conversation_id": str(conversation_id),
                        "locality": "local_only",
                        "cloud_context_eligible": True,
                        "input_audio_format": _format_wire(_format()),
                        "output_audio_format": _format_wire(_format()),
                        "model_override": None,
                    }
                )
            )
            opened = await _control(socket)
            failed_session_id = str(opened["realtime_session_id"])
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_started",
                        "sequence": 2,
                        "realtime_session_id": failed_session_id,
                    }
                )
            )
            started = await _control(socket)
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "input_committed",
                        "sequence": 3,
                        "realtime_session_id": failed_session_id,
                        "realtime_interaction_id": str(
                            started["realtime_interaction_id"]
                        ),
                    }
                )
            )
            await failure_entered.wait()
            release_failure.set()
            received: list[dict[str, object]] = []
            while True:
                payload = await _control(socket)
                received.append(payload)
                if payload["type"] == "session.failed":
                    break
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await socket.recv()

        assert [item["type"] for item in received] == ["session.failed"]
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1000
        assert provider.sessions()[0].close_calls == 1
        state = await core.conversation_runtime.get_conversation_state(conversation_id)
        assert state.turns == ()

        async with websockets.connect(
            f"ws://127.0.0.1:{access.port}/api/v1/realtime"
        ) as socket:
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "authenticate",
                        "sequence": 0,
                        "credential": credential,
                        "client_session_id": client_session_id,
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
                        "conversation_id": str(conversation_id),
                        "locality": "local_only",
                        "cloud_context_eligible": True,
                        "input_audio_format": _format_wire(_format()),
                        "output_audio_format": _format_wire(_format()),
                        "model_override": None,
                    }
                )
            )
            reopened = await _control(socket)
            assert reopened["realtime_session_id"] != failed_session_id
            await socket.send(
                json.dumps(
                    {
                        "protocol_version": "realtime.v1",
                        "type": "session.close",
                        "sequence": 2,
                        "realtime_session_id": reopened["realtime_session_id"],
                    }
                )
            )
            assert (await _control(socket)) == {
                "protocol_version": "realtime.v1",
                "type": "session.closed",
                "sequence": 2,
                "realtime_session_id": reopened["realtime_session_id"],
            }
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await socket.recv()
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 1000
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()
