"""Bounded provider-neutral model discovery (Gate I15)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from sofias_assistant.ai.discovery import (
    DiscoveredModel,
    FakeModelDiscoveryAdapter,
    ModelDiscoveryError,
    OpenAIModelDiscoveryAdapter,
)


def test_discovered_model_rejects_blank_fields() -> None:
    with pytest.raises(ValueError, match="model_id"):
        DiscoveredModel(model_id="", display_name="x")
    with pytest.raises(ValueError, match="display_name"):
        DiscoveredModel(model_id="gpt-x", display_name="")


@pytest.mark.asyncio
async def test_fake_discovery_adapter_returns_fixed_deterministic_set() -> None:
    models = (
        DiscoveredModel(model_id="model-a", display_name="model-a"),
        DiscoveredModel(model_id="model-b", display_name="model-b"),
    )
    adapter = FakeModelDiscoveryAdapter(models)

    result = await adapter.discover_models()

    assert result == models


@dataclass
class _FakeModelEntry:
    id: str


@dataclass
class _FakePage:
    data: list[_FakeModelEntry] = field(default_factory=list)


class _FakeModelsNamespace:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    async def list(self) -> _FakePage:
        return self._page


class _FakeOpenAIClient:
    def __init__(self, page: _FakePage, *, closed: list[bool] | None = None) -> None:
        self.models = _FakeModelsNamespace(page)
        self._closed = closed if closed is not None else []

    async def close(self) -> None:
        self._closed.append(True)


class _HangingModelsNamespace:
    async def list(self) -> _FakePage:
        await asyncio.sleep(10)
        return _FakePage()


class _HangingClient:
    def __init__(self) -> None:
        self.models = _HangingModelsNamespace()

    async def close(self) -> None:
        return None


class _FailingModelsNamespace:
    async def list(self) -> _FakePage:
        raise RuntimeError("boom")


class _FailingClient:
    def __init__(self) -> None:
        self.models = _FailingModelsNamespace()

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_openai_discovery_normalizes_identities_and_closes_client() -> None:
    closed: list[bool] = []
    page = _FakePage(
        data=[_FakeModelEntry(id="gpt-example"), _FakeModelEntry(id="gpt-other")]
    )
    adapter = OpenAIModelDiscoveryAdapter(
        client_factory=lambda: _FakeOpenAIClient(page, closed=closed)
    )

    discovered = await adapter.discover_models()

    assert [model.model_id for model in discovered] == ["gpt-example", "gpt-other"]
    assert closed == [True]


@pytest.mark.asyncio
async def test_openai_discovery_ignores_entries_without_a_valid_id() -> None:
    page = _FakePage(data=[_FakeModelEntry(id=""), _FakeModelEntry(id="gpt-valid")])
    adapter = OpenAIModelDiscoveryAdapter(
        client_factory=lambda: _FakeOpenAIClient(page)
    )

    discovered = await adapter.discover_models()

    assert [model.model_id for model in discovered] == ["gpt-valid"]


@pytest.mark.asyncio
async def test_openai_discovery_times_out_without_hanging_forever() -> None:
    adapter = OpenAIModelDiscoveryAdapter(
        client_factory=_HangingClient, timeout_seconds=0.01
    )

    with pytest.raises(ModelDiscoveryError, match="timed out"):
        await adapter.discover_models()


@pytest.mark.asyncio
async def test_openai_discovery_normalizes_provider_failures() -> None:
    adapter = OpenAIModelDiscoveryAdapter(client_factory=_FailingClient)

    with pytest.raises(ModelDiscoveryError, match="failed"):
        await adapter.discover_models()
