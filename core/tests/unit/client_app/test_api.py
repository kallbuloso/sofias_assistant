"""Transport adapter tests with a deterministic fake HTTP boundary."""

from uuid import uuid4

import pytest

from sofias_assistant.client_app.api import CoreApiClient, CoreApiError


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
        raise AssertionError(path)

    def stream(self, *_: object, **__: object) -> Stream:
        return Stream(Response(200, None), ['{"type":"text_delta","text":"hi"}'])

    def delete(self, *_: object, **__: object) -> Response:
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
    assert list(client.stream_text(fake.conversation_id, "hello"))[0]["text"] == "hi"
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
