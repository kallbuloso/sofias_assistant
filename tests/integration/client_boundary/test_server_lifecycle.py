"""Real loopback integration tests for the local server and its composition."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from sofias_assistant.ai.contracts import (
    AIRequest,
    Capability,
    ExecutionLocation,
    ModelDescriptor,
    ModelIdentity,
    ProviderCompleted,
    ProviderResponseMetadata,
    ProviderStreamEvent,
    TextDelta,
)
from sofias_assistant.ai.providers import TextStreamingProvider
from sofias_assistant.ai.registry import (
    ModelRegistration,
    ModelRegistry,
    ProviderBinding,
)
from sofias_assistant.ai.routing import CapabilityRouter
from sofias_assistant.client_boundary import (
    ClientSessionRegistry,
    LocalClientAuthenticator,
)
from sofias_assistant.client_boundary.boundary import (
    LocalClientAccess,
    LocalClientBoundary,
)
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.client_boundary.server import (
    DEFAULT_LOCAL_API_PORT,
    LOCAL_API_HOST,
    LocalApiBindError,
    LocalHttpServer,
)
from sofias_assistant.context.builder import ContextBuilder
from sofias_assistant.context.models import CoreSystemContext
from sofias_assistant.conversation.runtime import TextConversationRuntime
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sofias_assistant.secrets.models import SecretValue


def _app():
    authenticator, _ = LocalClientAuthenticator.create()
    return create_local_http_app(authenticator, ClientSessionRegistry(authenticator))


async def _request(port: int, request: str) -> str:
    reader, writer = await asyncio.open_connection(LOCAL_API_HOST, port)
    try:
        writer.write(request.encode("ascii"))
        await writer.drain()
        return (await reader.read()).decode("utf-8")
    finally:
        writer.close()
        await writer.wait_closed()


async def _streaming_runtime_for(
    tmp_path: Path, provider: TextStreamingProvider
) -> tuple[TextConversationRuntime, AsyncEngine]:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'operational.sqlite').as_posix()}"
    await asyncio.to_thread(upgrade_to_head, database_url)
    engine = create_async_engine(database_url)
    session_factory = create_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    descriptor = ModelDescriptor(
        identity=ModelIdentity("fake", "stream"),
        capabilities=frozenset({Capability.TEXT_STREAMING}),
        execution_location=ExecutionLocation.LOCAL,
        context_window=4096,
    )
    registry = ModelRegistry()
    registry.register(
        ModelRegistration(
            descriptor=descriptor,
            binding=ProviderBinding(text_streaming=provider),
        )
    )
    return (
        TextConversationRuntime(
            uow_factory=uow_factory,
            router=CapabilityRouter(registry),
            context_builder=ContextBuilder(
                system_context=CoreSystemContext("System", True),
                max_recent_turns=10,
                max_estimated_input_tokens=10_000,
            ),
        ),
        engine,
    )


class _LoopbackStreamingProvider:
    """Small local provider fake for a real socket test without network I/O."""

    async def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        metadata = ProviderResponseMetadata(request.request_id, model)
        yield TextDelta(metadata, "hello")
        yield ProviderCompleted(metadata)


def test_canonical_loopback_defaults() -> None:
    server = LocalHttpServer(_app())

    assert server.host == "127.0.0.1"
    assert server.requested_port == 8989
    assert LOCAL_API_HOST == "127.0.0.1"
    assert DEFAULT_LOCAL_API_PORT == 8989


def test_construction_is_side_effect_free(monkeypatch: pytest.MonkeyPatch) -> None:
    import sofias_assistant.client_boundary.server as server_module

    def fail_socket(*args: object, **kwargs: object) -> socket.socket:
        raise AssertionError("construction must not create a socket")

    monkeypatch.setattr(server_module.socket, "socket", fail_socket)

    LocalHttpServer(_app())
    LocalClientBoundary()


@pytest.mark.parametrize("port", [0, 1, 65535])
def test_port_validation_accepts_valid_range(port: int) -> None:
    assert LocalHttpServer(_app(), port=port).requested_port == port


@pytest.mark.parametrize("port", [-1, 65536])
def test_port_validation_rejects_outside_valid_range(port: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 65535"):
        LocalHttpServer(_app(), port=port)


def test_local_client_access_redacts_credential() -> None:
    access = LocalClientAccess(
        host=LOCAL_API_HOST,
        port=12345,
        credential=SecretValue("client-access-secret-sentinel"),
    )

    assert "client-access-secret-sentinel" not in repr(access)
    assert "client-access-secret-sentinel" not in str(access)
    assert access.host in repr(access)
    assert str(access.port) in repr(access)


@pytest.mark.asyncio
async def test_server_starts_and_serves_real_loopback_http() -> None:
    server = LocalHttpServer(_app(), port=0)
    await server.start()
    try:
        assert server.bound_port is not None
        assert server.bound_port > 0
        response = await _request(
            server.bound_port,
            "GET /docs HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
        )
        assert response.startswith("HTTP/1.1 404")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_occupied_port_fails_without_fallback() -> None:
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind((LOCAL_API_HOST, 0))
    reserved.listen()
    port = int(reserved.getsockname()[1])
    server = LocalHttpServer(_app(), port=port)
    try:
        with pytest.raises(LocalApiBindError) as raised:
            await server.start()

        assert str(port) in str(raised.value)
        assert server.requested_port == port
        assert server.bound_port is None
    finally:
        reserved.close()


@pytest.mark.asyncio
async def test_clean_stop_releases_the_loopback_port() -> None:
    server = LocalHttpServer(_app(), port=0)
    await server.start()
    port = server.bound_port
    assert port is not None

    await server.stop()

    with pytest.raises(OSError):
        await asyncio.open_connection(LOCAL_API_HOST, port)


@pytest.mark.asyncio
async def test_server_rejects_invalid_lifecycle_transitions() -> None:
    server = LocalHttpServer(_app(), port=0)

    with pytest.raises(RuntimeError, match="only stop"):
        await server.stop()
    await server.start()
    try:
        with pytest.raises(RuntimeError, match="only be started once"):
            await server.start()
    finally:
        await server.stop()
    with pytest.raises(RuntimeError, match="only stop"):
        await server.stop()


@pytest.mark.asyncio
async def test_boundary_start_returns_redacted_ephemeral_access() -> None:
    boundary = LocalClientBoundary(port=0)
    access = await boundary.start()
    try:
        assert isinstance(access.credential, SecretValue)
        assert access.host == LOCAL_API_HOST
        assert access.port > 0
        assert access.credential.reveal() not in repr(access)
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_boundary_serves_authenticated_post_over_real_loopback() -> None:
    boundary = LocalClientBoundary(port=0)
    access = await boundary.start()
    try:
        response = await _request(
            access.port,
            "POST /api/v1/client-sessions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"Authorization: Bearer {access.credential.reveal()}\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n\r\n",
        )
        assert response.startswith("HTTP/1.1 201")
        assert access.credential.reveal() not in response
    finally:
        await boundary.stop()


@pytest.mark.asyncio
async def test_boundary_stop_closes_server_and_rejects_second_stop() -> None:
    boundary = LocalClientBoundary(port=0)
    access = await boundary.start()

    await boundary.stop()

    with pytest.raises(OSError):
        await asyncio.open_connection(LOCAL_API_HOST, access.port)
    with pytest.raises(RuntimeError, match="only stop"):
        await boundary.stop()


@pytest.mark.asyncio
async def test_boundary_port_conflict_does_not_return_access_or_fallback() -> None:
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind((LOCAL_API_HOST, 0))
    reserved.listen()
    port = int(reserved.getsockname()[1])
    boundary = LocalClientBoundary(port=port)
    try:
        with pytest.raises(LocalApiBindError):
            await boundary.start()

        replacement = LocalClientBoundary(port=0)
        access = await replacement.start()
        try:
            assert access.port != port
        finally:
            await replacement.stop()
    finally:
        reserved.close()


@pytest.mark.asyncio
async def test_boundary_streams_a_durable_conversation_over_real_loopback(
    tmp_path: Path,
) -> None:
    provider = _LoopbackStreamingProvider()
    runtime, engine = await _streaming_runtime_for(tmp_path, provider)
    boundary = LocalClientBoundary(
        port=0,
        app_factory=lambda authenticator, sessions: create_local_http_app(
            authenticator, sessions, conversation=runtime
        ),
    )
    try:
        access = await boundary.start()
        opened = await _request(
            access.port,
            "POST /api/v1/client-sessions HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            f"Authorization: Bearer {access.credential.reveal()}\r\n"
            "Content-Length: 0\r\nConnection: close\r\n\r\n",
        )
        _, _, opened_body = opened.partition("\r\n\r\n")
        session_id = json.loads(opened_body)["id"]
        headers = (
            f"Authorization: Bearer {access.credential.reveal()}\r\n"
            f"X-Sofia-Client-Session-ID: {session_id}\r\n"
        )
        created = await _request(
            access.port,
            "POST /api/v1/conversations HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"{headers}Content-Length: 0\r\nConnection: close\r\n\r\n",
        )
        _, _, created_body = created.partition("\r\n\r\n")
        conversation_id = json.loads(created_body)["id"]
        payload = json.dumps(
            {
                "text": "request",
                "locality": "local_only",
                "cloud_context_eligible": True,
            }
        )
        streamed = await _request(
            access.port,
            "POST /api/v1/conversations/"
            f"{conversation_id}/turns HTTP/1.1\r\nHost: 127.0.0.1\r\n{headers}"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(payload.encode('utf-8'))}\r\n"
            f"\r\n{payload}",
        )
        assert streamed.startswith("HTTP/1.1 200")
        assert "application/x-ndjson" in streamed
        assert '"turn_started"' in streamed
        assert '"text_delta"' in streamed
        assert '"turn_completed"' in streamed

        retrieved = await _request(
            access.port,
            "GET /api/v1/conversations/"
            f"{conversation_id} HTTP/1.1\r\nHost: 127.0.0.1\r\n{headers}Connection: close\r\n\r\n",
        )
        assert retrieved.startswith("HTTP/1.1 200")
        assert '"assistant_text":"hello"' in retrieved
    finally:
        await boundary.stop()
        await engine.dispose()
