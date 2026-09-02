"""Real Core-to-loopback integration coverage for the authenticated HTTP adapter."""

import asyncio
import json
from pathlib import Path

import pytest

from sofias_assistant.client_boundary.boundary import LocalClientBoundary
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.config.models import AppPaths, RuntimeConfig
from sofias_assistant.core import CoreState, SofiaCore
from sofias_assistant.secrets.models import SecretRef, SecretValue


class FakeSecretStore:
    """In-memory secret backend that never accesses Credential Manager."""

    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


class FakeOwnership:
    """In-memory ownership fake that leaves the real Win32 mutex untouched."""

    def acquire(self) -> None:
        return None

    def release(self) -> None:
        return None


async def _request(port: int, request: str) -> tuple[str, dict[str, object]]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(request.encode("ascii"))
        await writer.drain()
        response = (await reader.read()).decode("utf-8")
    finally:
        writer.close()
        await writer.wait_closed()

    _, _, body = response.partition("\r\n\r\n")
    return response, json.loads(body)


@pytest.mark.asyncio
async def test_real_core_is_exposed_only_to_authenticated_loopback_session(
    tmp_path: Path,
) -> None:
    config = RuntimeConfig(paths=AppPaths(data_dir=tmp_path / "core-data"))
    core = SofiaCore(
        config,
        application_version="0.1.0.dev0",
        secret_store_factory=FakeSecretStore,
        instance_ownership_factory=lambda _: FakeOwnership(),
    )
    assert core.state is CoreState.CREATED

    await core.start()
    assert core.state is CoreState.RUNNING
    boundary = LocalClientBoundary(
        port=0,
        app_factory=lambda authenticator, sessions: create_local_http_app(
            authenticator, sessions, core=core
        ),
    )
    boundary_started = False
    try:
        access = await boundary.start()
        boundary_started = True
        opened_response, opened_body = await _request(
            access.port,
            "POST /api/v1/client-sessions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"Authorization: Bearer {access.credential.reveal()}\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n\r\n",
        )
        assert opened_response.startswith("HTTP/1.1 201")
        session_id = opened_body["id"]

        missing_bearer_response, _ = await _request(
            access.port,
            "GET /api/v1/core HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"X-Sofia-Client-Session-ID: {session_id}\r\n"
            "Connection: close\r\n\r\n",
        )
        assert missing_bearer_response.startswith("HTTP/1.1 401")

        unknown_session_response, _ = await _request(
            access.port,
            "GET /api/v1/core HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"Authorization: Bearer {access.credential.reveal()}\r\n"
            "X-Sofia-Client-Session-ID: 00000000-0000-0000-0000-000000000000\r\n"
            "Connection: close\r\n\r\n",
        )
        assert unknown_session_response.startswith("HTTP/1.1 401")

        response, body = await _request(
            access.port,
            "GET /api/v1/core HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"Authorization: Bearer {access.credential.reveal()}\r\n"
            f"X-Sofia-Client-Session-ID: {session_id}\r\n"
            "Connection: close\r\n\r\n",
        )
        assert response.startswith("HTTP/1.1 200")
        assert body == {
            "state": "running",
            "runtime_session_id": str(core.runtime_session_id),
            "health": {
                "status": "unknown",
                "components": [
                    {"name": "operational-store", "status": "healthy", "detail": None},
                    {
                        "name": "secret-store",
                        "status": "unknown",
                        "detail": "Backend configured; no active probe performed",
                    },
                ],
            },
        }
        assert access.credential.reveal() not in response
    finally:
        if boundary_started:
            await boundary.stop()
        await core.stop()
