"""Deterministic real-loopback evidence for the pending Gate I2 audit."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from sofias_assistant.ai.contracts import (
    AIMessageRole,
    AIRequest,
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
from sofias_assistant.core import ConversationRuntimeDependencies, CoreState, SofiaCore
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService
from tests.support.ai import (
    FakeStreamCompleted,
    FakeStreamFailed,
    FakeStreamScript,
    FakeTextDelta,
    ScriptedFakeProvider,
)


class FakeSecretStore:
    """In-memory SecretStore used only by deterministic Core composition tests."""

    def __init__(self) -> None:
        self._values: dict[str, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref.identifier)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref.identifier] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref.identifier, None) is not None


class FakeOwnership:
    """Avoid the real Windows mutex while retaining SofiaCore lifecycle wiring."""

    def acquire(self) -> None:
        return None

    def release(self) -> None:
        return None


def _dependencies_factory(
    provider_a: ScriptedFakeProvider,
    provider_b: ScriptedFakeProvider,
) -> Callable[[SecretService], ConversationRuntimeDependencies]:
    def factory(_: SecretService) -> ConversationRuntimeDependencies:
        registry = ModelRegistry()
        for model_id, provider in (
            ("provider-a", provider_a),
            ("provider-b", provider_b),
        ):
            registry.register(
                ModelRegistration(
                    descriptor=ModelDescriptor(
                        identity=ModelIdentity("fake", model_id),
                        capabilities=frozenset({Capability.TEXT_STREAMING}),
                        execution_location=ExecutionLocation.LOCAL,
                        context_window=4096,
                    ),
                    binding=ProviderBinding(text_streaming=provider),
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
    provider_a: ScriptedFakeProvider,
    provider_b: ScriptedFakeProvider,
) -> SofiaCore:
    return SofiaCore(
        RuntimeConfig(paths=AppPaths(data_dir=data_dir)),
        application_version="0.1.0.dev0",
        secret_store_factory=FakeSecretStore,
        instance_ownership_factory=lambda _: FakeOwnership(),
        conversation_dependencies_factory=_dependencies_factory(provider_a, provider_b),
    )


async def _request(
    port: int,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    payload: object | None = None,
) -> tuple[int, bytes]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {
        "Host": "127.0.0.1",
        "Connection": "close",
        **(headers or {}),
    }
    if body:
        request_headers["Content-Type"] = "application/json"
        request_headers["Content-Length"] = str(len(body))
    else:
        request_headers["Content-Length"] = "0"
    head = "".join(f"{name}: {value}\r\n" for name, value in request_headers.items())

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(f"{method} {path} HTTP/1.1\r\n{head}\r\n".encode("ascii") + body)
        await writer.drain()
        response = await reader.read()
    finally:
        writer.close()
        await writer.wait_closed()

    raw_head, raw_body = response.split(b"\r\n\r\n", maxsplit=1)
    status = int(raw_head.split(maxsplit=2)[1])
    if b"transfer-encoding: chunked" in raw_head.lower():
        raw_body = _decode_chunked(raw_body)
    return status, raw_body


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


def _records(body: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


@pytest.mark.asyncio
async def test_gate_i2_deterministic_loopback_composes_reloads_and_switches_models(
    tmp_path: Path,
) -> None:
    provider_a = ScriptedFakeProvider(
        stream_scripts=[
            FakeStreamScript(
                items=(FakeTextDelta("first response"), FakeStreamCompleted())
            ),
            FakeStreamScript(
                items=(FakeTextDelta("third response"), FakeStreamCompleted())
            ),
        ]
    )
    provider_b = ScriptedFakeProvider(
        stream_scripts=[
            FakeStreamScript(
                items=(FakeTextDelta("second response"), FakeStreamCompleted())
            )
        ]
    )
    data_dir = tmp_path / "core-data"
    core = _core(data_dir, provider_a, provider_b)
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
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": json.loads(body)["id"],
        }
        status, body = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])

        status, body = await _request(
            access.port,
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=headers,
            payload={
                "text": "first request",
                "locality": "local_only",
                "cloud_context_eligible": True,
            },
        )
        assert status == 200
        assert [record["type"] for record in _records(body)] == [
            "turn_started",
            "text_delta",
            "turn_completed",
        ]

        status, body = await _request(
            access.port,
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=headers,
            payload={
                "text": "second request",
                "locality": "local_only",
                "cloud_context_eligible": True,
                "model_override": {"provider_id": "fake", "model_id": "provider-b"},
            },
        )
        assert status == 200
        assert [record["type"] for record in _records(body)] == [
            "turn_started",
            "text_delta",
            "turn_completed",
        ]

        status, body = await _request(
            access.port,
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=headers,
            payload={
                "text": "third request",
                "locality": "local_only",
                "cloud_context_eligible": True,
            },
        )
        assert status == 200
        assert [record["type"] for record in _records(body)] == [
            "turn_started",
            "text_delta",
            "turn_completed",
        ]

        status, body = await _request(
            access.port,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
            headers=headers,
        )
        assert status == 200
        state = json.loads(body)
        assert UUID(state["conversation"]["id"]) == conversation_id
        assert [turn["status"] for turn in state["turns"]] == [
            "COMPLETED",
            "COMPLETED",
            "COMPLETED",
        ]
        assert [(turn["provider_id"], turn["model_id"]) for turn in state["turns"]] == [
            ("fake", "provider-a"),
            ("fake", "provider-b"),
            ("fake", "provider-a"),
        ]

        first_request = provider_a.invocations()[0].request
        second_request = provider_b.invocations()[0].request
        third_request = provider_a.invocations()[1].request
        assert isinstance(first_request, AIRequest)
        assert not hasattr(first_request, "conversation")
        assert [(message.role, message.text) for message in first_request.messages] == [
            (AIMessageRole.SYSTEM, "Core system context"),
            (AIMessageRole.USER, "first request"),
        ]
        assert [
            (message.role, message.text) for message in second_request.messages
        ] == [
            (AIMessageRole.SYSTEM, "Core system context"),
            (AIMessageRole.USER, "first request"),
            (AIMessageRole.ASSISTANT, "first response"),
            (AIMessageRole.USER, "second request"),
        ]
        third_messages = [
            (message.role, message.text) for message in third_request.messages
        ]
        assert third_messages == [
            (AIMessageRole.SYSTEM, "Core system context"),
            (AIMessageRole.USER, "second request"),
            (AIMessageRole.ASSISTANT, "second response"),
            (AIMessageRole.USER, "third request"),
        ]
        assert (AIMessageRole.USER, "first request") not in third_messages
        assert (AIMessageRole.ASSISTANT, "first response") not in third_messages
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()

    reloaded_a = ScriptedFakeProvider()
    reloaded_b = ScriptedFakeProvider()
    reloaded_core = _core(data_dir, reloaded_a, reloaded_b)
    try:
        await reloaded_core.start()
        reloaded = await reloaded_core.conversation_runtime.get_conversation_state(
            conversation_id
        )
        assert reloaded.conversation.id == conversation_id
        assert [turn.status.value for turn in reloaded.turns] == [
            "COMPLETED",
            "COMPLETED",
            "COMPLETED",
        ]
        assert [turn.assistant_text for turn in reloaded.turns] == [
            "first response",
            "second response",
            "third response",
        ]
    finally:
        if reloaded_core.state is CoreState.RUNNING:
            await reloaded_core.stop()


@pytest.mark.asyncio
async def test_gate_i2_loopback_normalizes_provider_failure(tmp_path: Path) -> None:
    raw_provider_request_id = "raw-provider-request-sentinel"
    raw_provider_session_id = "raw-provider-session-sentinel"
    provider_a = ScriptedFakeProvider(
        stream_scripts=[
            FakeStreamScript(
                items=(
                    FakeStreamFailed(
                        ProviderError(
                            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                            "Provider unavailable",
                            retryable=False,
                        )
                    ),
                ),
                provider_request_id=raw_provider_request_id,
                provider_session_id=raw_provider_session_id,
            )
        ]
    )
    core = _core(tmp_path / "core-data", provider_a, ScriptedFakeProvider())
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
            ),
        )
        access = await boundary.start()
        credential = access.credential.reveal()
        status, body = await _request(
            access.port,
            "POST",
            "/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {credential}"},
        )
        assert status == 201
        headers = {
            "Authorization": f"Bearer {credential}",
            "X-Sofia-Client-Session-ID": json.loads(body)["id"],
        }
        status, body = await _request(
            access.port, "POST", "/api/v1/conversations", headers=headers
        )
        assert status == 201
        conversation_id = UUID(json.loads(body)["id"])

        status, stream_body = await _request(
            access.port,
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=headers,
            payload={
                "text": "fail safely",
                "locality": "local_only",
                "cloud_context_eligible": True,
            },
        )
        assert status == 200
        records = _records(stream_body)
        assert [record["type"] for record in records] == [
            "turn_started",
            "turn_failed",
        ]
        assert "turn_completed" not in stream_body.decode("utf-8")
        assert raw_provider_request_id not in stream_body.decode("utf-8")
        assert raw_provider_session_id not in stream_body.decode("utf-8")

        status, state_body = await _request(
            access.port,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
            headers=headers,
        )
        assert status == 200
        state = json.loads(state_body)
        assert state["conversation"]["id"] == str(conversation_id)
        assert state["turns"][0]["status"] == "FAILED"
        assert raw_provider_request_id not in state_body.decode("utf-8")
        assert raw_provider_session_id not in state_body.decode("utf-8")
    finally:
        if boundary is not None:
            await boundary.stop()
        if core.state is CoreState.RUNNING:
            await core.stop()
