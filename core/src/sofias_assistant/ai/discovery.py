"""Provider-neutral model discovery boundary (Amendment 0003 SS11, Contract v1 SS20).

A provider listing a model proves only that the provider advertised that
model identity; it never proves capability semantics. Discovery adapters
therefore return only identity + safe display metadata, never capabilities.
Capability claims always require separate provenance (BUILTIN_METADATA,
PROBED, USER_OVERRIDE) handled by the AI Configuration Service, never by a
discovery adapter itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

_DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 10.0
_MAX_DISCOVERED_MODELS = 200


@dataclass(frozen=True, slots=True)
class DiscoveredModel:
    """One provider-advertised model identity; never a capability claim."""

    model_id: str
    display_name: str

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id must not be blank")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name must not be blank")


class ModelDiscoveryError(RuntimeError):
    """Raised when a bounded discovery attempt fails or times out."""


class ModelDiscoveryAdapter(Protocol):
    """Provider-neutral boundary that lists model identities for one provider."""

    async def discover_models(self) -> Sequence[DiscoveredModel]: ...


class OpenAIModelDiscoveryAdapter:
    """Bounded `GET /v1/models` discovery for OpenAI/OpenAI-compatible endpoints."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], Any],
        timeout_seconds: float = _DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    ) -> None:
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    async def discover_models(self) -> Sequence[DiscoveredModel]:
        client = self._client_factory()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                page = await client.models.list()
        except TimeoutError as error:
            raise ModelDiscoveryError(
                "Model discovery timed out before the provider responded"
            ) from error
        except Exception as error:
            raise ModelDiscoveryError(
                "Model discovery failed against the provider endpoint"
            ) from error
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                await close()
        discovered: list[DiscoveredModel] = []
        for entry in getattr(page, "data", []) or []:
            model_id = getattr(entry, "id", None)
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            discovered.append(DiscoveredModel(model_id=model_id, display_name=model_id))
            if len(discovered) >= _MAX_DISCOVERED_MODELS:
                break
        return tuple(discovered)


class FakeModelDiscoveryAdapter:
    """Deterministic discovery adapter for tests: returns a fixed identity set."""

    def __init__(self, models: Sequence[DiscoveredModel]) -> None:
        self._models = tuple(models)

    async def discover_models(self) -> Sequence[DiscoveredModel]:
        return self._models
