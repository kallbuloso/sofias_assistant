"""In-process integration tests for the local HTTP client-boundary contract."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sofias_assistant.ai.contracts import ModelIdentity, UsageMetadata
from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.conversation.events import (
    ConversationTextDelta,
    ConversationTurnCompleted,
    ConversationTurnStarted,
    ConversationUsageUpdated,
)
from sofias_assistant.conversation.models import (
    Conversation,
    Turn,
    TurnInputModality,
    TurnStatus,
)
from sofias_assistant.conversation.runtime import (
    ConversationNotFoundError,
    ConversationState,
    SendTextCommand,
)
from sofias_assistant.core import CoreState
from sofias_assistant.health import ComponentHealth, HealthStatus, RuntimeHealthSnapshot
from sofias_assistant.secrets.models import SecretValue


class FakeCoreReadApi:
    """Small read-only Core fake for HTTP adapter contract coverage."""

    def __init__(self) -> None:
        self.state = CoreState.RUNNING
        self.runtime_session_id = uuid4()
        self.health = RuntimeHealthSnapshot(
            (
                ComponentHealth("operational-store", HealthStatus.HEALTHY),
                ComponentHealth("secret-store", HealthStatus.UNKNOWN, "configured"),
            )
        )


class FakeConversationHttpApi:
    """In-memory Core-facing fake that keeps HTTP adapter tests transport-only."""

    def __init__(self) -> None:
        self._conversation_id = uuid4()
        self._turn_id = uuid4()
        self._request_id = uuid4()
        self._timestamp = datetime(2026, 9, 7, tzinfo=UTC)
        self._model = ModelIdentity("fake", "stream")
        self._created = False
        self.commands: list[SendTextCommand] = []

    async def create_conversation(self) -> Conversation:
        self._created = True
        return self._conversation()

    async def get_conversation_state(self, conversation_id: UUID) -> ConversationState:
        if not self._created or conversation_id != self._conversation_id:
            raise ConversationNotFoundError("Conversation was not found")
        return ConversationState(self._conversation(), (self._terminal_turn(),))

    async def stream_text(self, command: SendTextCommand):
        self.commands.append(command)
        conversation = self._conversation()
        processing = self._processing_turn(command.text)
        yield ConversationTurnStarted(conversation, processing)
        yield ConversationTextDelta(
            conversation.id, processing.id, self._request_id, self._model, "answer"
        )
        yield ConversationUsageUpdated(
            conversation.id,
            processing.id,
            self._request_id,
            self._model,
            UsageMetadata(input_tokens=2, output_tokens=1),
        )
        yield ConversationTurnCompleted(conversation, self._terminal_turn())

    def _conversation(self) -> Conversation:
        return Conversation(self._conversation_id, self._timestamp, self._timestamp)

    def _processing_turn(self, text: str) -> Turn:
        return Turn(
            self._turn_id,
            self._conversation_id,
            1,
            TurnStatus.PROCESSING,
            TurnInputModality.TEXT,
            True,
            text,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            self._timestamp,
            self._timestamp,
            None,
        )

    def _terminal_turn(self) -> Turn:
        return self._processing_turn("hello").complete(
            assistant_text="answer",
            ai_request_id=self._request_id,
            provider_id="fake",
            model_id="stream",
            provider_request_id="provider-request-secret",
            provider_session_id="provider-session-secret",
            updated_at=self._timestamp,
            finished_at=self._timestamp,
        )


@pytest.fixture
def boundary() -> tuple[TestClient, ClientSessionRegistry, str]:
    authenticator, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    return (
        TestClient(create_local_http_app(authenticator, sessions)),
        sessions,
        credential.reveal(),
    )


def _bearer(credential: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {credential}"}


def _open_session(client: TestClient, credential: str) -> dict[str, str]:
    response = client.post("/api/v1/client-sessions", headers=_bearer(credential))
    assert response.status_code == 201
    return response.json()


def test_app_creation_is_side_effect_free() -> None:
    authenticator, _ = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    unknown_id = uuid4()

    create_local_http_app(authenticator, sessions)

    assert sessions.get(unknown_id) is None


def test_runtime_documentation_routes_are_disabled(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, _ = boundary

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_open_session_requires_bearer_authentication(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, _ = boundary

    response = client.post("/api/v1/client-sessions")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization", ["Basic credential", "Bearer", "Bearer ", "Bearer   "]
)
def test_malformed_authorization_schemes_are_rejected(
    boundary: tuple[TestClient, ClientSessionRegistry, str], authorization: str
) -> None:
    client, _, _ = boundary

    response = client.post(
        "/api/v1/client-sessions", headers={"Authorization": authorization}
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_bearer_is_rejected_without_serializing_it(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, _ = boundary
    candidate = "client-http-super-secret-sentinel"

    response = client.post("/api/v1/client-sessions", headers=_bearer(candidate))

    assert response.status_code == 401
    assert candidate not in response.text
    assert candidate not in repr(response)


def test_valid_bearer_opens_a_session(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, sessions, credential = boundary

    response = client.post("/api/v1/client-sessions", headers=_bearer(credential))

    assert response.status_code == 201
    body = response.json()
    session_id = UUID(body["id"])
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.tzinfo is not None
    session = sessions.get(session_id)
    assert session is not None
    assert session.created_at == created_at
    assert credential not in response.text
    assert credential not in repr(response)


def test_session_id_alone_is_insufficient(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, credential = boundary
    session = _open_session(client, credential)

    response = client.get(
        "/api/v1/client-session",
        headers={"X-Sofia-Client-Session-ID": session["id"]},
    )

    assert response.status_code == 401


def test_bearer_alone_is_insufficient_after_opening_session(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, credential = boundary
    _open_session(client, credential)

    response = client.get("/api/v1/client-session", headers=_bearer(credential))

    assert response.status_code == 401


def test_invalid_session_uuid_is_rejected_generically(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, credential = boundary
    headers = _bearer(credential) | {"X-Sofia-Client-Session-ID": "not-a-uuid"}

    response = client.get("/api/v1/client-session", headers=headers)

    assert response.status_code == 401
    assert "not-a-uuid" not in response.text


def test_unknown_or_closed_session_is_rejected(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, credential = boundary
    headers = _bearer(credential) | {"X-Sofia-Client-Session-ID": str(uuid4())}

    assert client.get("/api/v1/client-session", headers=headers).status_code == 401


def test_authenticated_current_session_is_returned(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, credential = boundary
    opened = _open_session(client, credential)
    headers = _bearer(credential) | {"X-Sofia-Client-Session-ID": opened["id"]}

    response = client.get("/api/v1/client-session", headers=headers)

    assert response.status_code == 200
    assert response.json() == opened


def test_close_session_revokes_only_the_authenticated_session(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, credential = boundary
    opened = _open_session(client, credential)
    headers = _bearer(credential) | {"X-Sofia-Client-Session-ID": opened["id"]}

    assert client.delete("/api/v1/client-session", headers=headers).status_code == 204
    assert client.get("/api/v1/client-session", headers=headers).status_code == 401


def test_independent_boundaries_do_not_share_credentials() -> None:
    authenticator_a, credential_a = LocalClientAuthenticator.create()
    authenticator_b, _ = LocalClientAuthenticator.create()
    app_b = create_local_http_app(
        authenticator_b, ClientSessionRegistry(authenticator_b)
    )

    response = TestClient(app_b).post(
        "/api/v1/client-sessions", headers=_bearer(credential_a.reveal())
    )

    assert response.status_code == 401


def test_core_route_is_not_registered_without_a_core(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, _ = boundary

    assert client.get("/api/v1/core").status_code == 404


def test_core_route_requires_the_existing_session_authentication() -> None:
    credential = SecretValue("client-core-http-super-secret-sentinel")
    authenticator = LocalClientAuthenticator(
        hashlib.sha256(credential.reveal().encode("utf-8")).digest()
    )
    sessions = ClientSessionRegistry(authenticator)
    client = TestClient(
        create_local_http_app(authenticator, sessions, core=FakeCoreReadApi())
    )

    assert client.get("/api/v1/core").status_code == 401
    assert (
        client.get("/api/v1/core", headers=_bearer(credential.reveal())).status_code
        == 401
    )

    opened = _open_session(client, credential.reveal())
    headers = _bearer(credential.reveal()) | {"X-Sofia-Client-Session-ID": opened["id"]}
    response = client.get("/api/v1/core", headers=headers)

    assert response.status_code == 200
    assert response.json()["state"] == "running"
    assert response.json()["runtime_session_id"] is not None
    assert credential.reveal() not in response.text


def test_conversation_routes_are_registered_only_with_an_injected_service(
    boundary: tuple[TestClient, ClientSessionRegistry, str],
) -> None:
    client, _, _ = boundary

    assert client.post("/api/v1/conversations").status_code == 404


def test_authenticated_conversation_http_contract_is_explicit_and_redacted() -> None:
    authenticator, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    conversation = FakeConversationHttpApi()
    client = TestClient(
        create_local_http_app(authenticator, sessions, conversation=conversation)
    )
    opened = _open_session(client, credential.reveal())
    headers = _bearer(credential.reveal()) | {"X-Sofia-Client-Session-ID": opened["id"]}

    assert client.post("/api/v1/conversations").status_code == 401
    assert (
        client.post(
            "/api/v1/conversations", headers=_bearer(credential.reveal())
        ).status_code
        == 401
    )

    created = client.post("/api/v1/conversations", headers=headers)
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    stream = client.post(
        f"/api/v1/conversations/{conversation_id}/turns",
        headers=headers,
        json={
            "text": "hello",
            "locality": "cloud_allowed",
            "cloud_context_eligible": True,
            "model_override": {"provider_id": "fake", "model_id": "stream"},
        },
    )
    assert "application/x-ndjson" in stream.headers["content-type"]
    records = [json_line for json_line in stream.text.splitlines() if json_line]
    payloads = [json.loads(record) for record in records]
    assert [payload["type"] for payload in payloads] == [
        "turn_started",
        "text_delta",
        "usage_updated",
        "turn_completed",
    ]
    assert payloads[1]["text"] == "answer"
    assert "provider-request-secret" not in stream.text
    assert "provider-session-secret" not in stream.text
    assert conversation.commands[-1].model_override == ModelIdentity("fake", "stream")

    retrieved = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assert retrieved.status_code == 200
    assert retrieved.json()["turns"][0]["status"] == "COMPLETED"
    assert "provider_request_id" not in retrieved.text
    assert "provider_session_id" not in retrieved.text
    assert client.get(f"/api/v1/conversations/{uuid4()}", headers=headers).json() == {
        "detail": "Conversation not found"
    }


def _conversation_request_boundary() -> tuple[
    TestClient, FakeConversationHttpApi, dict[str, str], str
]:
    authenticator, credential = LocalClientAuthenticator.create()
    sessions = ClientSessionRegistry(authenticator)
    conversation = FakeConversationHttpApi()
    client = TestClient(
        create_local_http_app(authenticator, sessions, conversation=conversation)
    )
    opened = _open_session(client, credential.reveal())
    headers = _bearer(credential.reveal()) | {"X-Sofia-Client-Session-ID": opened["id"]}
    created = client.post("/api/v1/conversations", headers=headers)
    assert created.status_code == 201
    return client, conversation, headers, created.json()["id"]


@pytest.mark.parametrize("text", ["", "   "])
def test_conversation_turn_rejects_blank_text_with_422(text: str) -> None:
    client, _, headers, conversation_id = _conversation_request_boundary()

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/turns",
        headers=headers,
        json={
            "text": text,
            "locality": "local_only",
            "cloud_context_eligible": True,
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["provider_id", "model_id"])
@pytest.mark.parametrize("value", ["", "   "])
def test_conversation_turn_rejects_blank_model_override_fields_with_422(
    field: str, value: str
) -> None:
    client, _, headers, conversation_id = _conversation_request_boundary()
    override = {"provider_id": "fake", "model_id": "stream"}
    override[field] = value

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/turns",
        headers=headers,
        json={
            "text": "valid",
            "locality": "local_only",
            "cloud_context_eligible": True,
            "model_override": override,
        },
    )

    assert response.status_code == 422


def test_conversation_turn_preserves_significant_text_whitespace() -> None:
    client, conversation, headers, conversation_id = _conversation_request_boundary()
    text = "  preserve me  "

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/turns",
        headers=headers,
        json={
            "text": text,
            "locality": "local_only",
            "cloud_context_eligible": True,
        },
    )

    assert response.status_code == 200
    assert conversation.commands[-1].text == text
