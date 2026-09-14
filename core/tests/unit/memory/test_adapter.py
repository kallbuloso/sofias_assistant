"""Deterministic no-network tests for the Sofias Memory HTTP adapter (SA-B018)."""

from uuid import uuid4

import httpx2
import pytest

from sofias_assistant.memory.adapter import SofiasMemoryAdapter
from sofias_assistant.memory.models import (
    CreateMemoryRequest,
    MemoryErrorCategory,
    MemoryInvocationError,
    MemoryOriginKind,
    MemoryProvenance,
    MemoryType,
    RecallRequest,
    SupersedeMemoryRequest,
)
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService


class _Store:
    def __init__(self, value: SecretValue | None = SecretValue("sf-test-key")) -> None:
        self.value = value

    def get(self, _: SecretRef) -> SecretValue | None:
        return self.value

    def set(self, _: SecretRef, value: SecretValue) -> None:
        self.value = value

    def delete(self, _: SecretRef) -> bool:
        self.value = None
        return True


def _adapter(
    handler,
    *,
    secret: SecretValue | None = SecretValue("sf-test-key"),
) -> SofiasMemoryAdapter:
    def client_factory(
        *, base_url: str, timeout: float, api_key: str
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url=base_url,
            transport=httpx2.MockTransport(handler),
            headers={"X-API-Key": api_key},
        )

    return SofiasMemoryAdapter(
        base_url="https://memory.test",
        secret_service=SecretService(_Store(secret)),
        api_key_ref=SecretRef("integrations/sofias-memory/api-key"),
        client_factory=client_factory,
    )


def _envelope(data: object) -> httpx2.Response:
    return httpx2.Response(200, json={"data": data})


def _memory_item_json(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "memory_id": str(uuid4()),
        "memory_type": "profile",
        "lifecycle": "active",
        "created_at": "2026-09-14T00:00:00+00:00",
        "provenance": {
            "origin_kind": "user_asserted",
            "source_system": "sofias-assistant",
            "turn_uuid": str(uuid4()),
        },
        "scope": "global",
        "content": "Prefers dark mode.",
        "confidence": None,
        "valid_from": None,
        "valid_until": None,
        "superseded_at": None,
        "superseded_by": None,
        "forgotten_at": None,
    }
    base.update(overrides)
    return base


def _create_request() -> CreateMemoryRequest:
    return CreateMemoryRequest(
        memory_type=MemoryType.PROFILE,
        scope="global",
        content="Prefers dark mode.",
        provenance=MemoryProvenance(
            origin_kind=MemoryOriginKind.USER_ASSERTED, turn_uuid=uuid4()
        ),
    )


@pytest.mark.asyncio
async def test_probe_contract_sends_api_key_and_reports_full_compatibility() -> None:
    captured_headers: list[httpx2.Headers] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_headers.append(request.headers)
        assert request.url.path == "/api/v1/info"
        return _envelope(
            {
                "api_contract_version": "1",
                "contracts": {"cognitive_memory": "1"},
                "capabilities": [
                    "cognitive_memory.write",
                    "cognitive_memory.get",
                    "cognitive_memory.recall",
                    "cognitive_memory.supersede",
                    "cognitive_memory.forget",
                ],
            }
        )

    adapter = _adapter(handler)
    capabilities = await adapter.probe_contract()
    assert capabilities.supports_cognitive_memory is True
    assert captured_headers[0]["X-API-Key"] == "sf-test-key"


@pytest.mark.asyncio
async def test_probe_contract_reports_incompatible_when_capability_missing() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return _envelope(
            {
                "api_contract_version": "1",
                "contracts": {"cognitive_memory": "1"},
                "capabilities": ["cognitive_memory.write"],
            }
        )

    adapter = _adapter(handler)
    capabilities = await adapter.probe_contract()
    assert capabilities.supports_cognitive_memory is False


@pytest.mark.asyncio
async def test_missing_secret_fails_closed_without_network_call() -> None:
    called = False

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal called
        called = True
        return _envelope({})

    adapter = _adapter(handler, secret=None)
    with pytest.raises(MemoryInvocationError) as excinfo:
        await adapter.probe_contract()
    assert excinfo.value.error.category is MemoryErrorCategory.AUTHENTICATION_ERROR
    assert called is False


@pytest.mark.asyncio
async def test_create_memory_sends_idempotency_key_and_parses_item() -> None:
    captured_headers: list[httpx2.Headers] = []
    captured_body: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_headers.append(request.headers)
        captured_body.append(request.content)
        return httpx2.Response(201, json={"data": _memory_item_json()})

    adapter = _adapter(handler)
    item = await adapter.create_memory(_create_request(), idempotency_key="fixed-key")
    assert item.memory_type is MemoryType.PROFILE
    assert item.content == "Prefers dark mode."
    assert captured_headers[0]["Idempotency-Key"] == "fixed-key"
    assert (
        b'"memory_type":"profile"' in captured_body[0]
        or b'"memory_type": "profile"' in (captured_body[0])
    )


@pytest.mark.asyncio
async def test_get_memory_returns_none_on_404() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            404, json={"error": {"code": "MEMORY_NOT_FOUND", "message": "not found"}}
        )

    adapter = _adapter(handler)
    assert await adapter.get_memory(uuid4()) is None


@pytest.mark.asyncio
async def test_get_memory_returns_item_on_200() -> None:
    memory_id = uuid4()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return _envelope(_memory_item_json(memory_id=str(memory_id)))

    adapter = _adapter(handler)
    item = await adapter.get_memory(memory_id)
    assert item is not None
    assert item.memory_id == memory_id


@pytest.mark.asyncio
async def test_recall_memories_parses_ranked_items() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/memories/recall"
        return _envelope(
            {
                "items": [
                    {
                        "memory": _memory_item_json(),
                        "relevance": 0.83,
                        "is_current_truth": True,
                    }
                ]
            }
        )

    adapter = _adapter(handler)
    result = await adapter.recall_memories(
        RecallRequest(query="dark mode", scopes=("global",))
    )
    assert len(result.items) == 1
    assert result.items[0].relevance == 0.83
    assert result.items[0].is_current_truth is True


@pytest.mark.asyncio
async def test_supersede_memory_parses_old_and_replacement() -> None:
    old_id = uuid4()
    new_id = uuid4()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return _envelope(
            {
                "old": _memory_item_json(memory_id=str(old_id), lifecycle="superseded"),
                "replacement": _memory_item_json(memory_id=str(new_id)),
            }
        )

    adapter = _adapter(handler)
    result = await adapter.supersede_memory(
        old_id,
        SupersedeMemoryRequest(
            content="Prefers light mode now.",
            provenance=MemoryProvenance(
                origin_kind=MemoryOriginKind.USER_ASSERTED, turn_uuid=uuid4()
            ),
        ),
        idempotency_key="supersede-key",
    )
    assert result.old.memory_id == old_id
    assert result.replacement.memory_id == new_id


@pytest.mark.asyncio
async def test_forget_memory_returns_tombstone() -> None:
    memory_id = uuid4()

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == f"/api/v1/memories/{memory_id}/forget"
        return _envelope(
            _memory_item_json(
                memory_id=str(memory_id),
                lifecycle="forgotten",
                content=None,
                scope=None,
                forgotten_at="2026-09-14T01:00:00+00:00",
            )
        )

    adapter = _adapter(handler)
    tombstone = await adapter.forget_memory(memory_id, idempotency_key="forget-key")
    assert tombstone.content is None
    assert tombstone.forgotten_at is not None


@pytest.mark.parametrize(
    ("status_code", "code", "expected_category", "expected_retryable"),
    [
        (401, "MISSING_API_KEY", MemoryErrorCategory.AUTHENTICATION_ERROR, False),
        (403, "INVALID_API_KEY", MemoryErrorCategory.AUTHENTICATION_ERROR, False),
        (404, "MEMORY_NOT_FOUND", MemoryErrorCategory.NOT_FOUND, False),
        (409, "IDEMPOTENCY_CONFLICT", MemoryErrorCategory.IDEMPOTENCY_CONFLICT, False),
        (409, "MEMORY_STATE_CONFLICT", MemoryErrorCategory.STATE_CONFLICT, False),
        (422, "INVALID_REQUEST", MemoryErrorCategory.VALIDATION_ERROR, False),
        (503, "DEPENDENCY_UNAVAILABLE", MemoryErrorCategory.UNAVAILABLE, True),
    ],
)
@pytest.mark.asyncio
async def test_error_envelope_maps_to_expected_category(
    status_code: int,
    code: str,
    expected_category: MemoryErrorCategory,
    expected_retryable: bool,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status_code, json={"error": {"code": code, "message": "mapped"}}
        )

    adapter = _adapter(handler)
    with pytest.raises(MemoryInvocationError) as excinfo:
        await adapter.probe_contract()
    assert excinfo.value.error.category is expected_category
    assert excinfo.value.error.retryable is expected_retryable


@pytest.mark.asyncio
async def test_transport_timeout_maps_to_unavailable_and_retryable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.TimeoutException("timed out", request=request)

    adapter = _adapter(handler)
    with pytest.raises(MemoryInvocationError) as excinfo:
        await adapter.probe_contract()
    assert excinfo.value.error.category is MemoryErrorCategory.UNAVAILABLE
    assert excinfo.value.error.retryable is True


@pytest.mark.asyncio
async def test_malformed_json_response_is_a_protocol_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not json")

    adapter = _adapter(handler)
    with pytest.raises(MemoryInvocationError) as excinfo:
        await adapter.probe_contract()
    assert excinfo.value.error.category is MemoryErrorCategory.PROTOCOL_ERROR


@pytest.mark.asyncio
async def test_malformed_memory_item_payload_is_a_protocol_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return _envelope({"memory_id": "not-a-uuid"})

    adapter = _adapter(handler)
    with pytest.raises(MemoryInvocationError) as excinfo:
        await adapter.get_memory(uuid4())
    assert excinfo.value.error.category is MemoryErrorCategory.PROTOCOL_ERROR
