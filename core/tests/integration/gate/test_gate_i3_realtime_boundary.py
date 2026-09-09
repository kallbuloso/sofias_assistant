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
    FakeRealtimeCompleted,
    FakeRealtimePause,
    FakeRealtimeScript,
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
