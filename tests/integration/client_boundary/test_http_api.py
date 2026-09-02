"""In-process integration tests for the local HTTP client-boundary contract."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app


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
