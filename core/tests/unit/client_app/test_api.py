"""Transport adapter tests with a deterministic fake HTTP boundary."""

import json
from typing import Any, cast
from uuid import uuid4

import pytest
from websockets.exceptions import ConnectionClosed

from sofias_assistant.client_app.api import (
    CoreApiClient,
    CoreApiError,
    CoreValidationError,
    RealtimeVoiceConnection,
)


class Response:
    def __init__(self, status_code: int, value: object) -> None:
        self.status_code = status_code
        self._value = value

    def json(self) -> object:
        return self._value


class Stream:
    def __init__(self, response: Response, lines: list[str]) -> None:
        self.status_code = response.status_code
        self._lines = lines

    def __enter__(self) -> "Stream":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def iter_lines(self):
        return iter(self._lines)


class FakeHttp:
    def __init__(self) -> None:
        self.session_id = uuid4()
        self.conversation_id = uuid4()
        self.shutdown_status_code = 202
        self.last_stream_call: tuple[tuple[object, ...], dict[str, object]] | None = (
            None
        )
        self.runtime_identity: dict[str, object] = {
            "instance_key": "a" * 64,
            "runtime_session_id": str(uuid4()),
            "application_version": "0.1.0",
            "protocol_version": 1,
            "state": "running",
        }

    def post(self, path: str, **_: object) -> Response:
        if path == "/api/v1/client-sessions":
            return Response(201, {"id": str(self.session_id)})
        if path == "/api/v1/conversations":
            return Response(201, {"id": str(self.conversation_id)})
        if path.endswith("/acknowledge"):
            return Response(200, {"acknowledged": True})
        if path == "/api/v1/runtime/shutdown":
            return Response(self.shutdown_status_code, {"accepted": True})
        if path == "/api/v1/ai/models/refresh":
            return Response(200, [])
        if path == "/api/v1/ai/routing/preview":
            return Response(
                200,
                {
                    "profile": "coding",
                    "selected": {"provider_id": "openai", "model_id": "gpt-x"},
                    "fallback": False,
                    "reason_code": "PROFILE_BINDING_SELECTED",
                    "reason": "Highest-priority eligible profile binding selected.",
                },
            )
        raise AssertionError(path)

    def put(self, path: str, **_: object) -> Response:
        if path == "/api/v1/ai/providers/openai/credential":
            return Response(
                200,
                {
                    "credential_ref": "providers/openai/api-key",
                    "configured": True,
                    "effective_source": "platform_store",
                    "writable_source": "platform_store",
                    "shadowed": False,
                },
            )
        if path == "/api/v1/ai/providers/does-not-exist/credential":
            return Response(404, {"detail": "Provider not found"})
        if path == "/api/v1/integrations/sofias-memory/credential":
            return Response(
                200,
                {
                    "credential_ref": "integrations/sofias-memory/api-key",
                    "configured": True,
                    "effective_source": "platform_store",
                    "writable_source": "platform_store",
                    "shadowed": False,
                },
            )
        raise AssertionError(path)

    def patch(self, path: str, **_: object) -> Response:
        if path == "/api/v1/ai/providers/openai":
            return Response(
                200,
                {
                    "id": "openai",
                    "display_name": "OpenAI",
                    "adapter_type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "enabled": False,
                    "execution_location": "cloud",
                    "credential": {
                        "ref": "providers/openai/api-key",
                        "configured": True,
                    },
                },
            )
        if path == "/api/v1/ai/providers/does-not-exist":
            return Response(404, {"detail": "Provider not found"})
        if path == "/api/v1/ai/profiles/coding":
            return Response(
                200,
                {
                    "key": "coding",
                    "display_name": "coding",
                    "description": "Baseline coding workload profile",
                    "required_capabilities": ["text_generation", "tool_calling"],
                    "preferred_capabilities": [],
                    "locality": "cloud_allowed",
                    "enabled": True,
                    "fallback_policy": "ordered_then_canonical",
                    "bindings": [],
                },
            )
        if path == "/api/v1/ai/profiles/incompatible":
            return Response(422, {"detail": "Binding is not LOCAL_ONLY compatible"})
        raise AssertionError(path)

    def get(self, path: str, **_: object) -> Response:
        if path == "/api/v1/core":
            return Response(
                200,
                {
                    "state": "running",
                    "runtime_session_id": None,
                    "health": {"status": "healthy", "components": []},
                },
            )
        if path.startswith("/api/v1/notifications"):
            return Response(200, [])
        if path.startswith("/api/v1/tasks"):
            return Response(200, [])
        if path.startswith("/api/v1/conversations/"):
            return Response(
                200,
                {
                    "conversation": {
                        "id": str(self.conversation_id),
                        "created_at": "2030-01-01T00:00:00Z",
                        "updated_at": "2030-01-01T00:00:00Z",
                    },
                    "turns": [],
                },
            )
        if path == "/api/v1/runtime/identity":
            return Response(200, self.runtime_identity)
        if path == "/api/v1/ai/providers":
            return Response(
                200,
                [
                    {
                        "id": "openai",
                        "display_name": "OpenAI",
                        "adapter_type": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "enabled": True,
                        "execution_location": "cloud",
                        "credential": {
                            "ref": "providers/openai/api-key",
                            "configured": True,
                        },
                    }
                ],
            )
        if path == "/api/v1/ai/models":
            return Response(200, [])
        if path == "/api/v1/ai/profiles":
            return Response(200, [])
        if path == "/api/v1/ai/profiles/coding":
            return Response(
                200,
                {
                    "key": "coding",
                    "display_name": "coding",
                    "description": "Baseline coding workload profile",
                    "required_capabilities": ["text_generation", "tool_calling"],
                    "preferred_capabilities": [],
                    "locality": "cloud_allowed",
                    "enabled": True,
                    "fallback_policy": "ordered_then_canonical",
                    "bindings": [],
                },
            )
        if path == "/api/v1/integrations/sofias-memory":
            return Response(
                200,
                {
                    "enabled": True,
                    "base_url": "https://memory.invalid",
                    "credential": {
                        "credential_ref": "integrations/sofias-memory/api-key",
                        "configured": True,
                        "effective_source": "platform_store",
                        "writable_source": "platform_store",
                        "shadowed": False,
                    },
                    "health": {"status": "healthy", "detail": None},
                },
            )
        raise AssertionError(path)

    def stream(self, *args: object, **kwargs: object) -> Stream:
        self.last_stream_call = (args, kwargs)
        return Stream(Response(200, None), ['{"type":"text_delta","text":"hi"}'])

    def delete(self, path: str = "", **_: object) -> Response:
        if path == "/api/v1/ai/providers/openai/credential":
            return Response(
                200,
                {
                    "credential_ref": "providers/openai/api-key",
                    "configured": False,
                    "effective_source": "missing",
                    "writable_source": "platform_store",
                    "shadowed": False,
                },
            )
        if path == "/api/v1/integrations/sofias-memory/credential":
            return Response(
                200,
                {
                    "credential_ref": "integrations/sofias-memory/api-key",
                    "configured": False,
                    "effective_source": "missing",
                    "writable_source": "platform_store",
                    "shadowed": False,
                },
            )
        return Response(204, {})

    def close(self) -> None:
        return None


def test_client_authenticates_and_uses_single_transport_adapter() -> None:
    fake = FakeHttp()
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    payload = client.connect()
    assert client.session_id == fake.session_id
    assert payload["core"]["state"] == "running"
    assert client.create_conversation() == fake.conversation_id
    assert (
        list(
            client.stream_text(
                fake.conversation_id,
                "hello",
                locality="local_only",
                cloud_context_eligible=False,
            )
        )[0]["text"]
        == "hi"
    )
    assert client.acknowledge(uuid4()) is True
    assert "secret-token" not in repr(client)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8989",
        "http://192.168.1.2:8989",
        "http://127.0.0.1:8989/?token=secret",
    ],
)
def test_client_rejects_non_loopback_or_credential_bearing_urls(url: str) -> None:
    with pytest.raises(ValueError):
        CoreApiClient(url, "credential")


def test_stream_text_forwards_the_callers_explicit_privacy_values() -> None:
    fake = FakeHttp()
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    client.connect()

    list(
        client.stream_text(
            fake.conversation_id,
            "hello",
            locality="cloud_preferred",
            cloud_context_eligible=True,
        )
    )

    assert fake.last_stream_call is not None
    _, kwargs = fake.last_stream_call
    body = cast("dict[str, object]", kwargs["json"])
    assert body["locality"] == "cloud_preferred"
    assert body["cloud_context_eligible"] is True


def test_realtime_connection_targets_the_realtime_websocket_route() -> None:
    fake = FakeHttp()
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    client.connect()

    connection = client.realtime()

    assert connection._url == "ws://127.0.0.1:8989/api/v1/realtime"  # noqa: SLF001


def test_get_runtime_identity_returns_the_safe_payload() -> None:
    fake = FakeHttp()
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    client.connect()

    identity = client.get_runtime_identity()

    assert identity == fake.runtime_identity


def test_request_runtime_shutdown_accepted_returns_true() -> None:
    fake = FakeHttp()
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    client.connect()

    accepted = client.request_runtime_shutdown(uuid4(), reason="user_requested")

    assert accepted is True


def test_request_runtime_shutdown_lifecycle_mismatch_returns_false() -> None:
    fake = FakeHttp()
    fake.shutdown_status_code = 409
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    client.connect()

    accepted = client.request_runtime_shutdown(uuid4())

    assert accepted is False


def test_authentication_failure_is_safe() -> None:
    class Unauthorized(FakeHttp):
        def post(self, path: str, **_: object) -> Response:
            return Response(401, {"detail": "credential leaked"})

    client = CoreApiClient(
        "http://127.0.0.1:8989", "secret-token", http_client=Unauthorized()
    )
    with pytest.raises(CoreApiError, match="authentication") as error:
        client.connect()
    assert "secret-token" not in str(error.value)
    assert "credential leaked" not in str(error.value)


def _connected_client() -> CoreApiClient:
    fake = FakeHttp()
    client = CoreApiClient("http://127.0.0.1:8989", "secret-token", http_client=fake)
    client.connect()
    return client


def test_list_ai_providers_returns_the_decoded_payload() -> None:
    providers = _connected_client().list_ai_providers()
    assert providers[0]["id"] == "openai"
    assert "credential" in providers[0]


def test_update_ai_provider_applies_a_sparse_patch() -> None:
    updated = _connected_client().update_ai_provider("openai", {"enabled": False})
    assert updated["enabled"] is False


def test_update_ai_provider_unknown_id_raises_validation_error() -> None:
    client = _connected_client()
    with pytest.raises(CoreValidationError, match="Provider not found"):
        client.update_ai_provider("does-not-exist", {"enabled": False})


def test_list_ai_models_and_profiles_return_decoded_payloads() -> None:
    client = _connected_client()
    assert client.list_ai_models() == []
    assert client.list_ai_profiles() == []


def test_refresh_ai_models_posts_the_provider_id() -> None:
    assert _connected_client().refresh_ai_models("openai") == []


def test_get_and_update_ai_profile_round_trip() -> None:
    client = _connected_client()
    profile = client.get_ai_profile("coding")
    assert profile["key"] == "coding"
    updated = client.update_ai_profile("coding", {"enabled": True})
    assert updated["key"] == "coding"


def test_update_ai_profile_surfaces_a_safe_validation_reason() -> None:
    client = _connected_client()
    with pytest.raises(CoreValidationError, match="LOCAL_ONLY"):
        client.update_ai_profile("incompatible", {"bindings": []})


def test_preview_ai_routing_returns_the_decoded_decision() -> None:
    decision = _connected_client().preview_ai_routing(
        {"profile": "coding", "locality": "cloud_allowed"}
    )
    assert decision["selected"]["provider_id"] == "openai"


def test_set_and_delete_ai_provider_credential_never_echo_the_value() -> None:
    client = _connected_client()

    written = client.set_ai_provider_credential("openai", "sk-super-secret")
    assert written["configured"] is True
    assert "sk-super-secret" not in str(written)

    deleted = client.delete_ai_provider_credential("openai")
    assert deleted["configured"] is False


def test_set_ai_provider_credential_unknown_provider_raises_validation_error() -> None:
    client = _connected_client()
    with pytest.raises(CoreValidationError, match="Provider not found"):
        client.set_ai_provider_credential("does-not-exist", "sk-x")


def test_memory_integration_round_trip_never_echoes_credential_value() -> None:
    client = _connected_client()

    integration = client.get_memory_integration()
    assert integration["enabled"] is True
    assert integration["credential"]["configured"] is True

    written = client.set_memory_credential("sk-memory-secret")
    assert "sk-memory-secret" not in str(written)

    deleted = client.delete_memory_credential()
    assert deleted["configured"] is False


class _FakeRealtimeSocket:
    """A minimal `ClientConnection` stand-in: a scripted inbound frame queue."""

    def __init__(self, frames: list[str | bytes]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []

    def send(self, value: str) -> None:
        self.sent.append(value)

    def recv(self, timeout: float | None = None) -> str | bytes:
        if not self._frames:
            raise ConnectionClosed(None, None)
        return self._frames.pop(0)

    def close(self) -> None:
        return None


def _realtime_connection(frames: list[str | bytes]) -> RealtimeVoiceConnection:
    connection = RealtimeVoiceConnection(
        "ws://127.0.0.1:8989/api/v1/realtime", "secret-token", uuid4()
    )
    connection._socket = cast("Any", _FakeRealtimeSocket(frames))  # noqa: SLF001
    connection.session_id = uuid4()
    return connection


def test_start_matches_the_servers_dotted_interaction_started_type() -> None:
    """Regression: the server sends `interaction.started` (Gate I18 found

    `start()` checking the wrong, undotted `interaction_started`, which
    hung every voice session waiting for a confirmation that could never
    match).
    """

    interaction_id = uuid4()
    connection = _realtime_connection(
        [
            json.dumps(
                {
                    "type": "interaction.started",
                    "realtime_session_id": str(uuid4()),
                    "realtime_interaction_id": str(interaction_id),
                }
            )
        ]
    )

    started = connection.start()

    assert started == interaction_id
    assert connection.interaction_id == interaction_id


def test_start_buffers_assistant_events_that_race_ahead_of_confirmation() -> None:
    """Regression: a fast provider may emit assistant events before the

    client's `start()` finishes waiting for `interaction.started` -- those
    frames must be buffered and replayed by `pump_events()`, never dropped
    or treated as a protocol error.
    """

    interaction_id = uuid4()
    early_audio = b"\x01\x02"
    early_transcript = json.dumps(
        {"type": "assistant_transcript.partial", "text": "hel"}
    )
    confirmation = json.dumps(
        {
            "type": "interaction.started",
            "realtime_session_id": str(uuid4()),
            "realtime_interaction_id": str(interaction_id),
        }
    )
    connection = _realtime_connection([early_audio, early_transcript, confirmation])

    connection.start()
    events = list(connection.pump_events())

    assert events == [
        {"type": "assistant_audio_chunk", "audio": early_audio},
        {"type": "assistant_transcript.partial", "text": "hel"},
    ]
