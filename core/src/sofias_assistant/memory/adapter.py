"""HTTP boundary to Sofias Memory v0.7 Cognitive Memory, and a fake for tests.

No Sofias Memory Python package is imported anywhere in this module; the only
contract is the public HTTP API described in the immutable v0.7.0 release.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx2

from sofias_assistant.memory.models import (
    CreateMemoryRequest,
    MemoryCapabilities,
    MemoryError,
    MemoryErrorCategory,
    MemoryInvocationError,
    MemoryItem,
    MemoryItemProvenance,
    MemoryLifecycle,
    MemoryOriginKind,
    MemoryProvenance,
    MemoryRecallItem,
    MemoryRecallResult,
    MemorySupersedeResult,
    MemoryType,
    RecallRequest,
    SupersedeMemoryRequest,
)
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService

_ClientFactory = Callable[..., Any]

_KNOWN_ERROR_CODES: dict[str, tuple[MemoryErrorCategory, bool]] = {
    "MISSING_API_KEY": (MemoryErrorCategory.AUTHENTICATION_ERROR, False),
    "INVALID_API_KEY": (MemoryErrorCategory.AUTHENTICATION_ERROR, False),
    "MEMORY_NOT_FOUND": (MemoryErrorCategory.NOT_FOUND, False),
    "IDEMPOTENCY_CONFLICT": (MemoryErrorCategory.IDEMPOTENCY_CONFLICT, False),
    "MEMORY_STATE_CONFLICT": (MemoryErrorCategory.STATE_CONFLICT, False),
    "INVALID_REQUEST": (MemoryErrorCategory.VALIDATION_ERROR, False),
    "RESERVED_IDEMPOTENCY_KEY_NAMESPACE": (MemoryErrorCategory.VALIDATION_ERROR, False),
    "DEPENDENCY_UNAVAILABLE": (MemoryErrorCategory.UNAVAILABLE, True),
}

_STATUS_FALLBACK: dict[int, tuple[MemoryErrorCategory, bool]] = {
    401: (MemoryErrorCategory.AUTHENTICATION_ERROR, False),
    403: (MemoryErrorCategory.AUTHENTICATION_ERROR, False),
    404: (MemoryErrorCategory.NOT_FOUND, False),
    409: (MemoryErrorCategory.STATE_CONFLICT, False),
    422: (MemoryErrorCategory.VALIDATION_ERROR, False),
    503: (MemoryErrorCategory.UNAVAILABLE, True),
}


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


class SofiasMemoryAdapter:
    """Stateless Cognitive Memory adapter; credentials held only at call scope."""

    def __init__(
        self,
        *,
        base_url: str,
        secret_service: SecretService,
        api_key_ref: SecretRef,
        timeout_seconds: float = 8.0,
        client_factory: _ClientFactory | None = None,
    ) -> None:
        _require_non_blank(base_url, "base_url")
        self._base_url = base_url
        self._secret_service = secret_service
        self._api_key_ref = api_key_ref
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory or _create_client

    async def probe_contract(self) -> MemoryCapabilities:
        data = await self._call("GET", "/api/v1/info")
        if not isinstance(data, dict):
            raise _protocol_error("Sofias Memory /info response is malformed")
        contracts = data.get("contracts")
        cognitive_version = (
            contracts.get("cognitive_memory") if isinstance(contracts, dict) else None
        )
        capabilities = data.get("capabilities")
        return MemoryCapabilities(
            api_contract_version=data.get("api_contract_version"),
            cognitive_memory_contract_version=cognitive_version,
            capabilities=(
                frozenset(capabilities)
                if isinstance(capabilities, list)
                else frozenset()
            ),
        )

    async def create_memory(
        self, request: CreateMemoryRequest, *, idempotency_key: str
    ) -> MemoryItem:
        _require_non_blank(idempotency_key, "idempotency_key")
        data = await self._call(
            "POST",
            "/api/v1/memories",
            json_body=_create_request_body(request),
            headers={"Idempotency-Key": idempotency_key},
        )
        return _parse_memory_item(data)

    async def get_memory(self, memory_id: UUID) -> MemoryItem | None:
        try:
            data = await self._call("GET", f"/api/v1/memories/{memory_id}")
        except MemoryInvocationError as error:
            if error.error.category is MemoryErrorCategory.NOT_FOUND:
                return None
            raise
        return _parse_memory_item(data)

    async def recall_memories(self, request: RecallRequest) -> MemoryRecallResult:
        data = await self._call(
            "POST", "/api/v1/memories/recall", json_body=_recall_request_body(request)
        )
        if not isinstance(data, dict):
            raise _protocol_error("Sofias Memory recall response is malformed")
        items_raw = data.get("items")
        if not isinstance(items_raw, list):
            raise _protocol_error("Sofias Memory recall response is malformed")
        try:
            items = tuple(
                MemoryRecallItem(
                    memory=_parse_memory_item(item["memory"]),
                    relevance=float(item["relevance"]),
                    is_current_truth=bool(item["is_current_truth"]),
                )
                for item in items_raw
            )
        except (KeyError, TypeError, ValueError) as error:
            raise _protocol_error(
                "Sofias Memory recall response is malformed"
            ) from error
        return MemoryRecallResult(items=items)

    async def supersede_memory(
        self,
        memory_id: UUID,
        request: SupersedeMemoryRequest,
        *,
        idempotency_key: str,
    ) -> MemorySupersedeResult:
        _require_non_blank(idempotency_key, "idempotency_key")
        data = await self._call(
            "POST",
            f"/api/v1/memories/{memory_id}/supersede",
            json_body=_supersede_request_body(request),
            headers={"Idempotency-Key": idempotency_key},
        )
        if not isinstance(data, dict):
            raise _protocol_error("Sofias Memory supersede response is malformed")
        try:
            return MemorySupersedeResult(
                old=_parse_memory_item(data["old"]),
                replacement=_parse_memory_item(data["replacement"]),
            )
        except KeyError as error:
            raise _protocol_error(
                "Sofias Memory supersede response is malformed"
            ) from error

    async def forget_memory(
        self, memory_id: UUID, *, idempotency_key: str
    ) -> MemoryItem:
        _require_non_blank(idempotency_key, "idempotency_key")
        data = await self._call(
            "POST",
            f"/api/v1/memories/{memory_id}/forget",
            json_body=None,
            headers={"Idempotency-Key": idempotency_key},
        )
        return _parse_memory_item(data)

    def _client(self) -> Any:
        secret = self._secret_service.get(self._api_key_ref)
        if secret is None:
            raise MemoryInvocationError(
                MemoryError(
                    MemoryErrorCategory.AUTHENTICATION_ERROR,
                    "Sofias Memory credential is not configured",
                    False,
                )
            )
        return self._client_factory(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            api_key=secret.reveal(),
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        try:
            async with self._client() as client:
                response = await client.request(
                    method, path, json=json_body, headers=headers
                )
        except httpx2.RequestError as error:
            raise MemoryInvocationError(
                MemoryError(
                    MemoryErrorCategory.UNAVAILABLE,
                    "Sofias Memory is unreachable",
                    True,
                )
            ) from error
        try:
            body = response.json()
        except ValueError as error:
            raise _protocol_error(
                "Sofias Memory returned a non-JSON response"
            ) from error
        if response.status_code >= 400:
            code = None
            if isinstance(body, dict):
                error_body = body.get("error")
                if isinstance(error_body, dict):
                    code = error_body.get("code")
            raise _error_for(response.status_code, code)
        if not isinstance(body, dict) or "data" not in body:
            raise _protocol_error("Sofias Memory response is missing data")
        return body["data"]


def _create_client(*, base_url: str, timeout: float, api_key: str) -> Any:
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=httpx2.Timeout(timeout),
        headers={"X-API-Key": api_key},
    )


def _protocol_error(message: str) -> MemoryInvocationError:
    return MemoryInvocationError(
        MemoryError(MemoryErrorCategory.PROTOCOL_ERROR, message, False)
    )


def _error_for(status_code: int, code: str | None) -> MemoryInvocationError:
    category, retryable = (
        _KNOWN_ERROR_CODES.get(code) if code is not None else None
    ) or _STATUS_FALLBACK.get(status_code, (MemoryErrorCategory.PROTOCOL_ERROR, False))
    safe_code = code or f"HTTP_{status_code}"
    return MemoryInvocationError(
        MemoryError(category, f"Sofias Memory request failed ({safe_code})", retryable)
    )


def _create_request_body(request: CreateMemoryRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "memory_type": request.memory_type.value,
        "scope": request.scope,
        "content": request.content,
        "provenance": _provenance_body(request.provenance),
    }
    _add_optional_fields(
        body, request.confidence, request.valid_from, request.valid_until
    )
    return body


def _supersede_request_body(request: SupersedeMemoryRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "content": request.content,
        "provenance": _provenance_body(request.provenance),
    }
    _add_optional_fields(
        body, request.confidence, request.valid_from, request.valid_until
    )
    return body


def _add_optional_fields(
    body: dict[str, Any],
    confidence: float | None,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> None:
    if confidence is not None:
        body["confidence"] = confidence
    if valid_from is not None:
        body["valid_from"] = valid_from.isoformat()
    if valid_until is not None:
        body["valid_until"] = valid_until.isoformat()


def _provenance_body(provenance: MemoryProvenance) -> dict[str, Any]:
    body: dict[str, Any] = {
        "origin_kind": provenance.origin_kind.value,
        "source_system": provenance.source_system,
    }
    if provenance.conversation_uuid is not None:
        body["conversation_uuid"] = str(provenance.conversation_uuid)
    if provenance.turn_uuid is not None:
        body["turn_uuid"] = str(provenance.turn_uuid)
    if provenance.task_uuid is not None:
        body["task_uuid"] = str(provenance.task_uuid)
    if provenance.source_ref is not None:
        body["source_ref"] = provenance.source_ref
    if provenance.confirmation_ref is not None:
        body["confirmation_ref"] = provenance.confirmation_ref
    if provenance.observed_at is not None:
        body["observed_at"] = provenance.observed_at.isoformat()
    return body


def _recall_request_body(request: RecallRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "query": request.query,
        "scopes": list(request.scopes),
        "memory_types": [memory_type.value for memory_type in request.memory_types],
        "top_k": request.top_k,
        "include_superseded": request.include_superseded,
    }
    if request.as_of is not None:
        body["as_of"] = request.as_of.isoformat()
    if request.min_relevance is not None:
        body["min_relevance"] = request.min_relevance
    return body


def _parse_memory_item(data: Any) -> MemoryItem:
    if not isinstance(data, dict):
        raise _protocol_error("Sofias Memory item payload is malformed")
    try:
        provenance_data = data["provenance"]
        provenance = MemoryItemProvenance(
            origin_kind=MemoryOriginKind(provenance_data["origin_kind"]),
            source_system=provenance_data["source_system"],
            conversation_uuid=_parse_uuid(provenance_data.get("conversation_uuid")),
            turn_uuid=_parse_uuid(provenance_data.get("turn_uuid")),
            task_uuid=_parse_uuid(provenance_data.get("task_uuid")),
            source_ref=provenance_data.get("source_ref"),
            confirmation_ref=provenance_data.get("confirmation_ref"),
            observed_at=_parse_datetime(provenance_data.get("observed_at")),
        )
        created_at = _parse_datetime(data["created_at"])
        if created_at is None:
            raise ValueError("created_at must not be null")
        return MemoryItem(
            memory_id=UUID(data["memory_id"]),
            memory_type=MemoryType(data["memory_type"]),
            lifecycle=MemoryLifecycle(data["lifecycle"]),
            created_at=created_at,
            provenance=provenance,
            scope=data.get("scope"),
            content=data.get("content"),
            confidence=data.get("confidence"),
            valid_from=_parse_datetime(data.get("valid_from")),
            valid_until=_parse_datetime(data.get("valid_until")),
            superseded_at=_parse_datetime(data.get("superseded_at")),
            superseded_by=_parse_uuid(data.get("superseded_by")),
            forgotten_at=_parse_datetime(data.get("forgotten_at")),
        )
    except (KeyError, ValueError, TypeError) as error:
        raise _protocol_error(
            "Sofias Memory returned a malformed MemoryItem"
        ) from error


def _parse_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    return UUID(value)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class FakeMemoryProvider:
    """Deterministic in-memory Cognitive Memory double for offline tests.

    Reproduces the v0.7 contract semantics that Gate I6 depends on: an
    idempotency ledger with same-key/same-request replay and same-key/
    different-request conflict, atomic Supersede with same-operation replay
    taking precedence over lifecycle conflict, destructive-but-idempotent
    Forget, and current-truth-at-`as_of` recall filtering.
    """

    def __init__(
        self,
        *,
        capabilities: MemoryCapabilities | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._capabilities = capabilities or _full_capabilities()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or uuid4
        self._items: dict[UUID, MemoryItem] = {}
        self._idempotency: dict[str, tuple[str, Any, Any]] = {}
        self.next_error: MemoryError | None = None

    async def probe_contract(self) -> MemoryCapabilities:
        self._maybe_raise()
        return self._capabilities

    async def create_memory(
        self, request: CreateMemoryRequest, *, idempotency_key: str
    ) -> MemoryItem:
        self._maybe_raise()
        canonical = _canonical_create(request)
        replay = self._check_idempotency("create", idempotency_key, canonical)
        if replay is not None:
            return replay
        item = MemoryItem(
            memory_id=self._id_factory(),
            memory_type=request.memory_type,
            lifecycle=MemoryLifecycle.ACTIVE,
            created_at=self._clock(),
            provenance=_full_provenance(request.provenance),
            scope=request.scope,
            content=request.content,
            confidence=request.confidence,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
        )
        self._items[item.memory_id] = item
        self._idempotency[idempotency_key] = ("create", canonical, item)
        return item

    async def get_memory(self, memory_id: UUID) -> MemoryItem | None:
        self._maybe_raise()
        return self._items.get(memory_id)

    async def recall_memories(self, request: RecallRequest) -> MemoryRecallResult:
        self._maybe_raise()
        as_of = request.as_of or self._clock()
        scored: list[tuple[MemoryItem, float, bool]] = []
        for item in self._items.values():
            if item.lifecycle is MemoryLifecycle.FORGOTTEN:
                continue
            if item.scope not in request.scopes:
                continue
            if item.memory_type not in request.memory_types:
                continue
            if item.created_at > as_of:
                continue
            if item.valid_from is not None and item.valid_from > as_of:
                continue
            if item.valid_until is not None and item.valid_until <= as_of:
                continue
            is_current_truth = item.superseded_at is None or as_of < item.superseded_at
            if not request.include_superseded and not is_current_truth:
                continue
            relevance = _fake_relevance(request.query, item)
            if request.min_relevance is not None and relevance < request.min_relevance:
                continue
            scored.append((item, relevance, is_current_truth))
        scored.sort(
            key=lambda entry: (
                -entry[1],
                -entry[0].created_at.timestamp(),
                entry[0].memory_id,
            )
        )
        limited = scored[: request.top_k]
        return MemoryRecallResult(
            items=tuple(
                MemoryRecallItem(
                    memory=item, relevance=relevance, is_current_truth=truth
                )
                for item, relevance, truth in limited
            )
        )

    async def supersede_memory(
        self,
        memory_id: UUID,
        request: SupersedeMemoryRequest,
        *,
        idempotency_key: str,
    ) -> MemorySupersedeResult:
        self._maybe_raise()
        canonical = _canonical_supersede(memory_id, request)
        replay = self._check_idempotency("supersede", idempotency_key, canonical)
        if replay is not None:
            return replay
        target = self._items.get(memory_id)
        if target is None:
            raise MemoryInvocationError(
                MemoryError(MemoryErrorCategory.NOT_FOUND, "Memory not found", False)
            )
        if target.lifecycle is not MemoryLifecycle.ACTIVE:
            raise MemoryInvocationError(
                MemoryError(
                    MemoryErrorCategory.STATE_CONFLICT,
                    "Only an ACTIVE memory can be superseded",
                    False,
                )
            )
        now = self._clock()
        replacement = MemoryItem(
            memory_id=self._id_factory(),
            memory_type=target.memory_type,
            lifecycle=MemoryLifecycle.ACTIVE,
            created_at=now,
            provenance=_full_provenance(request.provenance),
            scope=target.scope,
            content=request.content,
            confidence=request.confidence,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
        )
        superseded_old = _replace_memory_item(
            target,
            lifecycle=MemoryLifecycle.SUPERSEDED,
            superseded_at=now,
            superseded_by=replacement.memory_id,
        )
        self._items[memory_id] = superseded_old
        self._items[replacement.memory_id] = replacement
        result = MemorySupersedeResult(old=superseded_old, replacement=replacement)
        self._idempotency[idempotency_key] = ("supersede", canonical, result)
        return result

    async def forget_memory(
        self, memory_id: UUID, *, idempotency_key: str
    ) -> MemoryItem:
        self._maybe_raise()
        canonical = memory_id
        replay = self._check_idempotency("forget", idempotency_key, canonical)
        if replay is not None:
            return replay
        target = self._items.get(memory_id)
        if target is None:
            raise MemoryInvocationError(
                MemoryError(MemoryErrorCategory.NOT_FOUND, "Memory not found", False)
            )
        if target.lifecycle is MemoryLifecycle.FORGOTTEN:
            self._idempotency[idempotency_key] = ("forget", canonical, target)
            return target
        tombstone = MemoryItem(
            memory_id=target.memory_id,
            memory_type=target.memory_type,
            lifecycle=MemoryLifecycle.FORGOTTEN,
            created_at=target.created_at,
            provenance=MemoryItemProvenance(
                origin_kind=target.provenance.origin_kind,
                source_system=target.provenance.source_system,
            ),
            superseded_at=target.superseded_at,
            superseded_by=target.superseded_by,
            forgotten_at=self._clock(),
        )
        self._items[memory_id] = tombstone
        self._idempotency[idempotency_key] = ("forget", canonical, tombstone)
        return tombstone

    def _check_idempotency(
        self, kind: str, idempotency_key: str, canonical: Any
    ) -> Any | None:
        existing = self._idempotency.get(idempotency_key)
        if existing is None:
            return None
        existing_kind, existing_canonical, result = existing
        if existing_kind != kind or existing_canonical != canonical:
            raise MemoryInvocationError(
                MemoryError(
                    MemoryErrorCategory.IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key already used for a different request",
                    False,
                )
            )
        return result

    def _maybe_raise(self) -> None:
        if self.next_error is not None:
            error, self.next_error = self.next_error, None
            raise MemoryInvocationError(error)


def _full_capabilities() -> MemoryCapabilities:
    return MemoryCapabilities(
        api_contract_version="1",
        cognitive_memory_contract_version="1",
        capabilities=frozenset(
            {
                "cognitive_memory.write",
                "cognitive_memory.get",
                "cognitive_memory.recall",
                "cognitive_memory.supersede",
                "cognitive_memory.forget",
            }
        ),
    )


def _full_provenance(provenance: MemoryProvenance) -> MemoryItemProvenance:
    return MemoryItemProvenance(
        origin_kind=provenance.origin_kind,
        source_system=provenance.source_system,
        conversation_uuid=provenance.conversation_uuid,
        turn_uuid=provenance.turn_uuid,
        task_uuid=provenance.task_uuid,
        source_ref=provenance.source_ref,
        confirmation_ref=provenance.confirmation_ref,
        observed_at=provenance.observed_at,
    )


def _replace_memory_item(item: MemoryItem, **changes: Any) -> MemoryItem:
    return replace(item, **changes)


def _canonical_create(request: CreateMemoryRequest) -> Any:
    return (
        request.memory_type,
        request.scope,
        request.content,
        _canonical_provenance(request.provenance),
        request.confidence,
        request.valid_from,
        request.valid_until,
    )


def _canonical_supersede(memory_id: UUID, request: SupersedeMemoryRequest) -> Any:
    return (
        memory_id,
        request.content,
        _canonical_provenance(request.provenance),
        request.confidence,
        request.valid_from,
        request.valid_until,
    )


def _canonical_provenance(provenance: MemoryProvenance) -> Any:
    return (
        provenance.origin_kind,
        provenance.conversation_uuid,
        provenance.turn_uuid,
        provenance.task_uuid,
        provenance.source_ref,
        provenance.confirmation_ref,
        provenance.observed_at,
        provenance.source_system,
    )


def _fake_relevance(query: str, item: MemoryItem) -> float:
    if item.content and query.strip().lower() in item.content.lower():
        return 1.0
    return 0.5
