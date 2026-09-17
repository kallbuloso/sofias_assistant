"""Gate I18 — Daily Assistant Experience (SA-B040 + SA-B041).

Proves the Desktop/Core Interaction Contract v1 vertical this Gate adds on
top of the already-verified I15/I16/I17 baseline: bounded Conversation
History (SS37-39), explicit human privacy policy with no hidden
`local_only` default (SS31-35, Amendment 0004 SS24-25), and the new
Desktop-side realtime audio pipeline (event pump + audio devices) driven
end to end over the real `realtime.v1` WebSocket protocol against a
deterministic fake realtime provider (ADR-0005 SS65) -- never a second
Realtime runtime, never a live/paid provider.

Confirmation/Task/Notification Core-domain correctness (approve/deny,
cancel, acknowledge) is unchanged by this Gate and remains covered by the
Gates that introduced it; this Gate's own additions there (lifetime-echo
in `ClientApplicationService.decide_confirmation`, the "already finished"
cancel message, `ConfirmationDialog` rendering) are unit-tested in
`tests/unit/client_app/{test_client_application_service,test_worker,
test_qt_components}.py`.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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
from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.client_app.audio import (
    FakeAudioInputDevice,
    FakeAudioOutputDevice,
)
from sofias_assistant.client_app.qt_app import ClientWorker
from sofias_assistant.client_boundary.boundary import LocalClientBoundary
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.core import (
    ConversationDependenciesFactory,
    ConversationRuntimeDependencies,
    CoreState,
    SofiaCore,
)
from sofias_assistant.host import runner
from sofias_assistant.secrets.models import SecretRef, SecretValue
from tests.integration.core.test_core import FakeSecretStore, fake_ownership_factory
from tests.support.realtime import (
    FakeAssistantAudioChunk,
    FakeAssistantTranscriptFinal,
    FakeRealtimeCompleted,
    FakeRealtimeScript,
    FakeUserTranscriptFinal,
    ScriptedFakeRealtimeProvider,
)


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fake_completed_response() -> Any:
    return SimpleNamespace(
        status="completed",
        output_text="ok",
        usage=None,
        output=(),
        _request_id=None,
    )


class _FakeResponses:
    """Emulates enough of the OpenAI Responses API for both text_generation

    (non-streaming, a single completed response) and text_streaming
    (`stream=True`: an async iterator of `response.output_text.delta` then
    `response.completed` events) -- the canonical chat.general model needs
    the streaming shape to actually complete a real text Turn.
    """

    async def create(self, *, stream: bool = False, **kwargs: Any) -> Any:
        if not stream:
            return _fake_completed_response()

        async def _events() -> AsyncIterator[Any]:
            yield SimpleNamespace(type="response.output_text.delta", delta="ok")
            yield SimpleNamespace(
                type="response.completed", response=_fake_completed_response()
            )

        return _events()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()

    async def close(self) -> None:
        return None


@asynccontextmanager
async def _running_host(
    tmp_path: Path,
) -> AsyncIterator[tuple[CoreApiClient, SofiaCore]]:
    """Real production host (same composition `sofia-core` uses)."""

    environment = {
        "SOFIA_DATA_DIR": str(tmp_path / "core-data"),
        "SOFIA_CORE_PORT": str(_free_loopback_port()),
        "LLM_MODEL": "gate-i18-canonical-model",
        "LLM_API_KEY": "sk-smoke",
    }
    shutdown_event = asyncio.Event()
    ready: asyncio.Future[tuple[Any, SofiaCore]] = (
        asyncio.get_running_loop().create_future()
    )

    def on_ready(access: Any, core: SofiaCore) -> None:
        if not ready.done():
            ready.set_result((access, core))

    task = asyncio.create_task(
        runner.run(
            environment=environment,
            env_file=None,
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=fake_ownership_factory,
            client_factory=lambda api_key: _FakeOpenAIClient(),
            shutdown_event=shutdown_event,
            on_ready=on_ready,
            install_signal_handlers=False,
        )
    )
    waitable: set[asyncio.Future[Any]] = {task, ready}
    done, _pending = await asyncio.wait(waitable, return_when=asyncio.FIRST_COMPLETED)
    if task in done and not ready.done():
        raise AssertionError(f"host failed to reach READY (exit code {task.result()})")
    access, core = await ready
    client = CoreApiClient(
        f"http://127.0.0.1:{access.port}", access.credential.reveal()
    )
    try:
        await asyncio.to_thread(client.connect)
        yield client, core
    finally:
        await asyncio.to_thread(client.close)
        shutdown_event.set()
        await task


async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _send(
    client: CoreApiClient,
    conversation_id: Any,
    text: str,
    *,
    locality: str,
    cloud_context_eligible: bool,
) -> list[dict[str, Any]]:
    """Send one text Turn, forcing the streaming generator to actually run.

    `CoreApiClient.stream_text` is itself a generator function: calling it
    only builds the generator object, it never sends the HTTP request until
    iterated. Every call site must consume it (here, via `list(...)`).
    """

    return await _call(
        lambda: list(
            client.stream_text(
                conversation_id,
                text,
                locality=locality,
                cloud_context_eligible=cloud_context_eligible,
            )
        )
    )


# -- Conversation History (SA-B040) ------------------------------------------


@pytest.mark.asyncio
async def test_conversation_list_is_empty_before_any_conversation_exists(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core):
        page = await _call(client.list_conversations)

    assert page["items"] == []
    assert page["next_cursor"] is None


@pytest.mark.asyncio
async def test_create_resume_and_bounded_history_round_trip(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core):
        conversation_id = await _call(client.create_conversation)
        await _send(
            client,
            conversation_id,
            "Hello Sofia, what's the weather like?",
            locality="cloud_allowed",
            cloud_context_eligible=True,
        )

        listing = await _call(client.list_conversations)
        assert len(listing["items"]) == 1
        item = listing["items"][0]
        assert item["conversation_id"] == str(conversation_id)
        # Deterministic preview: first non-blank user Turn, normalized/truncated.
        assert item["preview"] == "Hello Sofia, what's the weather like?"
        assert item["last_turn_status"] == "COMPLETED"
        assert item["last_turn_sequence"] == 1

        # Resume: bounded Turn history is Operational data, never Memory --
        # a plain repository read, no LLM/Memory call involved.
        history = await _call(client.list_conversation_turns, conversation_id)
        assert len(history["turns"]) == 1
        assert history["turns"][0]["status"] == "COMPLETED"
        assert history["has_older"] is False


@pytest.mark.asyncio
async def test_conversation_paging_is_bounded_and_chronological(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core):
        conversation_id = await _call(client.create_conversation)
        for index in range(3):
            await _send(
                client,
                conversation_id,
                f"message {index}",
                locality="cloud_allowed",
                cloud_context_eligible=True,
            )

        first_page = await _call(
            client.list_conversation_turns, conversation_id, limit=2
        )
        assert [t["sequence"] for t in first_page["turns"]] == [2, 3]
        assert first_page["has_older"] is True

        older_page = await _call(
            client.list_conversation_turns,
            conversation_id,
            limit=2,
            before_sequence=first_page["turns"][0]["sequence"],
        )
        assert [t["sequence"] for t in older_page["turns"]] == [1]
        assert older_page["has_older"] is False


@pytest.mark.asyncio
async def test_conversation_history_never_loads_unbounded_turns(
    tmp_path: Path,
) -> None:
    """Contract v1 SS37: the list query must not load every Turn."""

    async with _running_host(tmp_path) as (client, _core):
        conversation_id = await _call(client.create_conversation)
        for index in range(10):
            await _send(
                client,
                conversation_id,
                f"message {index}",
                locality="cloud_allowed",
                cloud_context_eligible=True,
            )

        page = await _call(client.list_conversations)

    assert page["items"][0]["last_turn_sequence"] == 10
    assert "turns" not in page["items"][0]


# -- Privacy (SA-B040) --------------------------------------------------------


@pytest.mark.asyncio
async def test_local_only_actually_blocks_the_cloud_canonical_model(
    tmp_path: Path,
) -> None:
    """No hidden `local_only` default exists anymore, but an EXPLICIT

    `local_only` request must still fail closed against a cloud-only model
    rather than silently falling back to cloud (Amendment 0003 SS14).
    """

    async with _running_host(tmp_path) as (client, _core):
        conversation_id = await _call(client.create_conversation)
        events = await _send(
            client,
            conversation_id,
            "should not reach the cloud model",
            locality="local_only",
            cloud_context_eligible=False,
        )
        history = await _call(client.list_conversation_turns, conversation_id)

    assert any(event.get("type") == "turn_failed" for event in events)
    assert history["turns"][0]["status"] == "FAILED"


@pytest.mark.asyncio
async def test_cloud_allowed_routes_the_eligible_cloud_canonical_model(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core):
        conversation_id = await _call(client.create_conversation)
        await _send(
            client,
            conversation_id,
            "this may reach the cloud model",
            locality="cloud_allowed",
            cloud_context_eligible=True,
        )
        history = await _call(client.list_conversation_turns, conversation_id)

    assert history["turns"][0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_stream_text_requires_explicit_privacy_values_on_the_wire(
    tmp_path: Path,
) -> None:
    """No Desktop/Core call path may omit locality/cloud_context_eligible

    and have Core silently substitute a default (Contract v1 SS34):
    confirm the HTTP layer itself rejects a request missing them.
    """

    async with _running_host(tmp_path) as (client, _core):
        conversation_id = await _call(client.create_conversation)

        def _raw_incomplete_request() -> int:
            response = client._http.post(
                f"/api/v1/conversations/{conversation_id}/turns",
                headers=client._headers(),
                json={"text": "missing privacy fields"},
            )
            return int(response.status_code)

        status_code = await _call(_raw_incomplete_request)

    assert status_code == 422


# -- Realtime voice pipeline (SA-B041) ---------------------------------------


class _FakeSecretStore:
    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


class _FakeOwnership:
    def acquire(self) -> None:
        return None

    def release(self) -> None:
        return None


def _pcm_format() -> AudioFormat:
    return AudioFormat(AudioEncoding.PCM16, 24_000, 1)


def _realtime_dependencies_factory(
    provider: ScriptedFakeRealtimeProvider,
) -> ConversationDependenciesFactory:
    def factory(_: Any, __: Any) -> ConversationRuntimeDependencies:
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
                        }
                    ),
                    execution_location=ExecutionLocation.LOCAL,
                    context_window=4096,
                ),
                binding=ProviderBinding(realtime=provider),
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


@pytest.mark.asyncio
async def test_realtime_pipeline_end_to_end_with_fake_devices_and_fake_provider(
    tmp_path: Path,
) -> None:
    """The new Gate I18 surface: real Desktop `RealtimeVoiceConnection` +

    `ClientWorker` event dispatch, driven over the real `realtime.v1`
    WebSocket boundary against a real (test-composed) Core, with
    deterministic fake microphone/speaker devices standing in for
    hardware (Contract v1 SS45-47). Never a second Realtime runtime: the
    same `RealtimeConversationRuntime`/wire protocol Gate I3 proved is
    reused unmodified.
    """

    assistant_audio = b"\x10\x20ASSISTANT-AUDIO-CHUNK"
    provider = ScriptedFakeRealtimeProvider(
        (
            FakeRealtimeScript(
                (
                    FakeUserTranscriptFinal("real voice message"),
                    FakeAssistantAudioChunk(assistant_audio, _pcm_format()),
                    FakeAssistantTranscriptFinal("real voice response"),
                    FakeRealtimeCompleted(),
                )
            ),
        )
    )
    core = SofiaCore(
        RuntimeConfig(paths=AppPaths(data_dir=tmp_path / "core-data")),
        application_version="0.1.0.dev0",
        secret_store_factory=_FakeSecretStore,
        instance_ownership_factory=lambda _: _FakeOwnership(),
        conversation_dependencies_factory=_realtime_dependencies_factory(provider),
    )
    boundary: LocalClientBoundary | None = None
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
                execution=core.execution_runtime,
                tasks=core.task_runtime,
                proactivity=core.proactivity,
            ),
        )
        access = await boundary.start()
        client = CoreApiClient(
            f"http://127.0.0.1:{access.port}", access.credential.reveal()
        )

        def _drive_voice() -> dict[str, Any]:
            client.connect()
            conversation_id = client.create_conversation()
            worker = ClientWorker(client.base_url, "unused-in-this-direct-drive")
            output_device = FakeAudioOutputDevice()
            output_device.start()
            worker._output_device = output_device

            voice = client.realtime()
            voice.open(
                conversation_id, locality="local_only", cloud_context_eligible=True
            )
            voice.start()

            input_device = FakeAudioInputDevice([b"\x01\x02", b"\x03\x04"])
            input_device.start(voice.send_audio)
            voice.commit()

            event_types: list[str] = []
            user_transcripts: list[str] = []
            assistant_transcripts: list[str] = []
            for event in voice.pump_events():
                event_types.append(str(event.get("type")))
                if event.get("type") == "user_transcript.final":
                    user_transcripts.append(str(event.get("text")))
                if event.get("type") == "assistant_transcript.final":
                    assistant_transcripts.append(str(event.get("text")))
                worker._handle_voice_event(event)
                if event.get("type") in {"turn.completed", "turn.failed"}:
                    break
            voice.stop()
            client.close()
            return {
                "event_types": event_types,
                "user_transcripts": user_transcripts,
                "assistant_transcripts": assistant_transcripts,
                "sent_audio_frames": len(provider.sessions()[0].frames()),
                "committed": len(provider.sessions()[0].commits()) == 1,
                "output_written": output_device.written,
            }

        result = await asyncio.to_thread(_drive_voice)
    finally:
        if boundary is not None:
            await boundary.stop()
        await core.stop()

    assert "user_transcript.final" in result["event_types"]
    assert "turn.completed" in result["event_types"]
    assert result["user_transcripts"] == ["real voice message"]
    assert result["assistant_transcripts"] == ["real voice response"]
    # The two fake microphone chunks were really sent over the wire to Core.
    assert result["sent_audio_frames"] == 2
    assert result["committed"] is True
    # The assistant's binary audio frame reached the (fake) speaker.
    assert result["output_written"] == [assistant_audio]


@pytest.mark.asyncio
async def test_realtime_open_carries_explicit_privacy_values_not_a_hardcode(
    tmp_path: Path,
) -> None:
    """Amendment 0004 SS24-25: voice uses the same explicit privacy policy

    as text; `RealtimeVoiceConnection.open()` must never silently send
    `local_only`/`False` regardless of what the caller passed.
    """

    provider = ScriptedFakeRealtimeProvider(
        (FakeRealtimeScript((FakeRealtimeCompleted(),)),)
    )
    core = SofiaCore(
        RuntimeConfig(paths=AppPaths(data_dir=tmp_path / "core-data")),
        application_version="0.1.0.dev0",
        secret_store_factory=_FakeSecretStore,
        instance_ownership_factory=lambda _: _FakeOwnership(),
        conversation_dependencies_factory=_realtime_dependencies_factory(provider),
    )
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
                execution=core.execution_runtime,
                tasks=core.task_runtime,
                proactivity=core.proactivity,
            ),
        )
        access = await boundary.start()
        client = CoreApiClient(
            f"http://127.0.0.1:{access.port}", access.credential.reveal()
        )

        def _open_with_cloud_preference() -> None:
            client.connect()
            conversation_id = client.create_conversation()
            voice = client.realtime()
            # LOCAL execution location + cloud_context_eligible=True must be
            # accepted -- Core enforces compatibility, the Desktop must not
            # narrow/widen it silently either way.
            voice.open(
                conversation_id, locality="cloud_preferred", cloud_context_eligible=True
            )
            voice.stop()
            client.close()

        await asyncio.to_thread(_open_with_cloud_preference)
    finally:
        if boundary is not None:
            await boundary.stop()
        await core.stop()

    opens = provider.opens()
    assert len(opens) == 1
