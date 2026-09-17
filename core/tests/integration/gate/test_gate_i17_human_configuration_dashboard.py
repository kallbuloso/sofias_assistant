"""Gate I17 — Human Configuration Dashboard (SA-B039).

Proves the Desktop/Core Interaction Contract v1 SS25-SS44 vertical for the
Dashboard: purpose-specific provider/Sofias-Memory credential write-only
surfaces, safe effective-source/shadowing status, non-secret provider
config, model catalog + discovery refresh, capability provenance, profile
binding reorder as a single atomic Core operation, invalid-binding
rejection, fallback policy update, routing preview, Memory integration
health/config, Core-side validation of every write, and no secret leakage
-- driven end to end through the real production host (`runner.run`) and
the real, blocking `CoreApiClient`, exactly like the Gate I15/I16 human
smoke pattern. No live provider is used; only deterministic fakes.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sofias_assistant.ai.contracts import (
    Capability,
    CapabilityProvenance,
    ExecutionLocation,
)
from sofias_assistant.ai.registry import ModelAvailability
from sofias_assistant.ai_config.models import (
    CapabilityClaim,
    DiscoverySource,
    ModelCatalogEntry,
)
from sofias_assistant.client_app.api import CoreApiClient, CoreValidationError
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.host import runner
from tests.integration.core.test_core import FakeSecretStore, fake_ownership_factory


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _FakeModel:
    def __init__(self, model_id: str) -> None:
        self.id = model_id


class _FakeModelPage:
    def __init__(self, model_ids: list[str]) -> None:
        self.data = [_FakeModel(model_id) for model_id in model_ids]


class _FakeModels:
    def __init__(self, model_ids: list[str]) -> None:
        self._page = _FakeModelPage(model_ids)

    async def list(self) -> _FakeModelPage:
        return self._page


class _FakeResponses:
    async def create(self, *, stream: bool = False, **kwargs: Any) -> Any:
        return SimpleNamespace(
            status="completed",
            output_text="ok",
            usage=None,
            output=(),
            _request_id=None,
        )


class _FakeOpenAIClient:
    """Fake OpenAI SDK transport: text generation + `models.list()` discovery."""

    def __init__(self, discovered_model_ids: list[str] | None = None) -> None:
        self.responses = _FakeResponses()
        self.models = _FakeModels(discovered_model_ids or ["gate-i17-discovered"])

    async def close(self) -> None:
        return None


@asynccontextmanager
async def _running_host(
    tmp_path: Path,
    *,
    extra_environment: dict[str, str] | None = None,
    discovered_model_ids: list[str] | None = None,
) -> AsyncIterator[tuple[CoreApiClient, SofiaCore, str]]:
    """Start the real production host, hand back a connected `CoreApiClient`."""

    environment = {
        "SOFIA_DATA_DIR": str(tmp_path / "core-data"),
        "SOFIA_CORE_PORT": str(_free_loopback_port()),
        "LLM_MODEL": "gate-i17-canonical-model",
        "LLM_API_KEY": "sk-smoke",
        **(extra_environment or {}),
    }
    shutdown_event = asyncio.Event()
    ready: asyncio.Future[tuple[Any, SofiaCore]] = (
        asyncio.get_running_loop().create_future()
    )

    def on_ready(access: Any, core: SofiaCore) -> None:
        if not ready.done():
            ready.set_result((access, core))

    task = asyncio.create_task(
        runner.run(
            environment=environment,
            env_file=None,
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=fake_ownership_factory,
            client_factory=lambda api_key: _FakeOpenAIClient(discovered_model_ids),
            shutdown_event=shutdown_event,
            on_ready=on_ready,
            install_signal_handlers=False,
        )
    )
    waitable: set[asyncio.Future[Any]] = {task, ready}
    done, _pending = await asyncio.wait(waitable, return_when=asyncio.FIRST_COMPLETED)
    if task in done and not ready.done():
        raise AssertionError(f"host failed to reach READY (exit code {task.result()})")
    access, core = await ready
    credential = access.credential.reveal()
    client = CoreApiClient(f"http://127.0.0.1:{access.port}", credential)
    try:
        await asyncio.to_thread(client.connect)
        yield client, core, credential
    finally:
        await asyncio.to_thread(client.close)
        shutdown_event.set()
        await task


async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)


# -- 1-3: attach, Home readiness inputs, providers load ----------------------


@pytest.mark.asyncio
async def test_desktop_attaches_and_loads_the_home_readiness_inputs(
    tmp_path: Path,
) -> None:
    """Authenticated attach (I16 flow) plus the two Home-readiness reads."""

    async with _running_host(tmp_path) as (client, _core, _credential):
        providers = await _call(client.list_ai_providers)
        memory = await _call(client.get_memory_integration)

    assert providers[0]["id"] == "openai"
    assert providers[0]["credential"]["configured"] is True
    assert memory["enabled"] is False
    assert memory["health"]["status"] == "unknown"


# -- 4: non-secret provider update persists ----------------------------------


@pytest.mark.asyncio
async def test_provider_non_secret_update_persists(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        updated = await _call(
            client.update_ai_provider,
            "openai",
            {"enabled": False, "base_url": "https://api.openai.com/v2"},
        )
        assert updated["enabled"] is False
        assert updated["base_url"] == "https://api.openai.com/v2"

        reloaded = await _call(client.list_ai_providers)
        assert reloaded[0]["enabled"] is False
        assert reloaded[0]["base_url"] == "https://api.openai.com/v2"


@pytest.mark.asyncio
async def test_provider_update_unknown_id_is_rejected(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        with pytest.raises(CoreValidationError, match="Provider not found"):
            await _call(client.update_ai_provider, "does-not-exist", {"enabled": False})


# -- 5-8: provider credential write/replace/delete, never echoed ------------


@pytest.mark.asyncio
async def test_provider_credential_write_replace_delete_lifecycle(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path, extra_environment={"LLM_API_KEY": ""}) as (
        client,
        _core,
        _credential,
    ):
        # The canonical bootstrap secret was seeded from LLM_API_KEY at
        # startup; clearing it here means the platform store starts empty
        # for this scenario, isolating the write-path assertions below.
        status = await _call(client.set_ai_provider_credential, "openai", "sk-first")
        assert status["configured"] is True
        assert status["effective_source"] == "platform_store"
        assert status["shadowed"] is False
        assert "sk-first" not in str(status)

        replaced = await _call(client.set_ai_provider_credential, "openai", "sk-second")
        assert replaced["configured"] is True
        assert "sk-second" not in str(replaced)
        assert "sk-first" not in str(replaced)

        deleted = await _call(client.delete_ai_provider_credential, "openai")
        assert deleted["configured"] is False
        assert deleted["effective_source"] == "missing"


@pytest.mark.asyncio
async def test_provider_credential_write_unknown_provider_is_rejected(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        with pytest.raises(CoreValidationError, match="Provider not found"):
            await _call(client.set_ai_provider_credential, "does-not-exist", "sk-x")


# -- 9: environment secret shadowing shown safely ----------------------------


@pytest.mark.asyncio
async def test_environment_secret_shadows_a_newly_written_platform_credential(
    tmp_path: Path,
) -> None:
    """Amendment 0004 SS22: writing the platform store never mutates or

    displaces a higher-priority environment-backed secret; the response
    must say so without ever exposing either value.
    """

    async with _running_host(tmp_path) as (client, _core, _credential):
        # LLM_API_KEY="sk-smoke" is already present in the process
        # environment for this host (Amendment 0003 SS5 highest-priority
        # source); a Dashboard write still succeeds durably but is shadowed.
        status = await _call(
            client.set_ai_provider_credential, "openai", "sk-dashboard"
        )

        assert status["configured"] is True
        assert status["effective_source"] == "environment"
        assert status["shadowed"] is True
        assert "sk-smoke" not in str(status)
        assert "sk-dashboard" not in str(status)


# -- 10-12: models list, discovery refresh, capability provenance -----------


@pytest.mark.asyncio
async def test_model_catalog_lists_the_seeded_canonical_model(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        models = await _call(client.list_ai_models)

    assert any(model["model_id"] == "gate-i17-canonical-model" for model in models)


@pytest.mark.asyncio
async def test_model_discovery_refresh_adds_discovered_models_without_proven_capabilities(
    tmp_path: Path,
) -> None:
    async with _running_host(
        tmp_path, discovered_model_ids=["gate-i17-canonical-model", "brand-new-model"]
    ) as (client, _core, _credential):
        refreshed = await _call(client.refresh_ai_models, "openai")

    discovered = next(m for m in refreshed if m["model_id"] == "brand-new-model")
    assert discovered["discovery_source"] == "discovered"
    # DISCOVERED alone must never be emitted as a proven capability
    # (Amendment 0003 SS11 / Contract v1 SS19).
    assert discovered["capabilities"] == []
    assert discovered["enabled"] is False


@pytest.mark.asyncio
async def test_model_refresh_unknown_provider_is_rejected(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        with pytest.raises(CoreValidationError):
            await _call(client.refresh_ai_models, "does-not-exist")


# -- 13-17: profiles, binding reorder, invalid binding, fallback policy -----


@pytest.mark.asyncio
async def test_profiles_list_and_detail_are_available(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        profiles = await _call(client.list_ai_profiles)
        detail = await _call(client.get_ai_profile, "chat.general")

    assert {profile["key"] for profile in profiles} == {
        "chat.general",
        "coding",
        "research",
        "vision",
        "realtime",
    }
    assert detail["key"] == "chat.general"
    assert len(detail["bindings"]) == 1
    assert detail["bindings"][0]["model_id"] == "gate-i17-canonical-model"


async def _seed_user_override_model(core: SofiaCore, model_id: str) -> None:
    """Add a second real, chat.general-eligible model (Contract v1 SS19:

    `DISCOVERED` alone never proves a capability, so a binding-reorder
    fixture needs a `USER_OVERRIDE` claim instead of relying on discovery).
    """

    service = core.ai_configuration_service
    assert service is not None
    now = datetime.now(UTC)
    async with service._uow_factory() as uow:  # noqa: SLF001
        uow.model_catalog_entries.add(
            ModelCatalogEntry(
                provider_id="openai",
                model_id=model_id,
                display_name=model_id,
                context_window=None,
                execution_location=ExecutionLocation.CLOUD,
                availability=ModelAvailability.AVAILABLE,
                enabled=True,
                discovery_source=DiscoverySource.MANUAL,
                capabilities=frozenset(
                    {
                        CapabilityClaim(
                            Capability.TEXT_GENERATION,
                            CapabilityProvenance.USER_OVERRIDE,
                        )
                    }
                ),
                metadata={},
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await uow.commit()
    await service._rebuild_and_publish()  # noqa: SLF001


@pytest.mark.asyncio
async def test_binding_reorder_is_a_single_atomic_profile_update(
    tmp_path: Path,
) -> None:
    """Reorder must never be emulated as a sequence of single-priority writes

    that could leave an invalid intermediate profile state: the Dashboard
    sends the full ordered binding list in one `PATCH` call
    (`replace_for_profile` inside `AIConfigurationService.update_profile`).
    """

    async with _running_host(tmp_path) as (client, core, _credential):
        await _seed_user_override_model(core, "second-model")
        await _call(
            client.update_ai_profile,
            "chat.general",
            {
                "bindings": [
                    {
                        "provider_id": "openai",
                        "model_id": "gate-i17-canonical-model",
                        "priority": 1,
                        "enabled": True,
                    },
                    {
                        "provider_id": "openai",
                        "model_id": "second-model",
                        "priority": 2,
                        "enabled": True,
                    },
                ]
            },
        )
        detail = await _call(client.get_ai_profile, "chat.general")
        assert [b["model_id"] for b in detail["bindings"]] == [
            "gate-i17-canonical-model",
            "second-model",
        ]

        reordered = await _call(
            client.update_ai_profile,
            "chat.general",
            {
                "bindings": [
                    {
                        "provider_id": "openai",
                        "model_id": "second-model",
                        "priority": 1,
                        "enabled": True,
                    },
                    {
                        "provider_id": "openai",
                        "model_id": "gate-i17-canonical-model",
                        "priority": 2,
                        "enabled": True,
                    },
                ]
            },
        )

    assert [b["model_id"] for b in reordered["bindings"]] == [
        "second-model",
        "gate-i17-canonical-model",
    ]


@pytest.mark.asyncio
async def test_invalid_binding_is_rejected_by_core_with_a_safe_reason(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        with pytest.raises(CoreValidationError, match="unknown model"):
            await _call(
                client.update_ai_profile,
                "chat.general",
                {
                    "bindings": [
                        {
                            "provider_id": "openai",
                            "model_id": "does-not-exist",
                            "priority": 1,
                            "enabled": True,
                        }
                    ]
                },
            )


@pytest.mark.asyncio
async def test_fallback_policy_update_persists(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        updated = await _call(
            client.update_ai_profile, "coding", {"fallback_policy": "ordered_only"}
        )

    assert updated["fallback_policy"] == "ordered_only"


@pytest.mark.asyncio
async def test_profile_update_unknown_key_is_rejected(tmp_path: Path) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        with pytest.raises(CoreValidationError, match="Profile not found"):
            await _call(client.update_ai_profile, "does-not-exist", {"enabled": False})


# -- 18: routing preview uses Core -------------------------------------------


@pytest.mark.asyncio
async def test_routing_preview_uses_the_real_core_routing_policy(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        preview = await _call(
            client.preview_ai_routing,
            {
                "profile": "chat.general",
                "required_capabilities": ["text_generation"],
                "locality": "cloud_allowed",
            },
        )

    assert preview["selected"] == {
        "provider_id": "openai",
        "model_id": "gate-i17-canonical-model",
    }
    assert preview["reason_code"] == "profile_binding_selected"
    assert preview["fallback"] is False


# -- 19-20: Memory health/config, credential lifecycle -----------------------


@pytest.mark.asyncio
async def test_memory_credential_write_replace_delete_lifecycle(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, _core, _credential):
        written = await _call(client.set_memory_credential, "sk-memory-first")
        assert written["configured"] is True
        assert written["effective_source"] == "platform_store"
        assert "sk-memory-first" not in str(written)

        integration = await _call(client.get_memory_integration)
        assert integration["credential"]["configured"] is True

        deleted = await _call(client.delete_memory_credential)
        assert deleted["configured"] is False


@pytest.mark.asyncio
async def test_memory_credential_environment_shadowing_is_shown_safely(
    tmp_path: Path,
) -> None:
    async with _running_host(
        tmp_path, extra_environment={"SOFIAS_MEMORY_API_KEY": "sk-memory-env"}
    ) as (client, _core, _credential):
        status = await _call(client.set_memory_credential, "sk-memory-platform")

    assert status["configured"] is True
    assert status["effective_source"] == "environment"
    assert status["shadowed"] is True
    assert "sk-memory-env" not in str(status)
    assert "sk-memory-platform" not in str(status)


# -- 21: Core reconnect reloads authoritative state --------------------------


@pytest.mark.asyncio
async def test_a_second_authenticated_session_sees_the_same_authoritative_state(
    tmp_path: Path,
) -> None:
    """Stands in for 'Desktop reattaches and reloads Core-authoritative

    state': a brand-new authenticated session (as a fresh attach would
    open) must observe exactly the config a prior session wrote -- nothing
    is cached client-side as truth.
    """

    async with _running_host(tmp_path) as (client, _core, credential):
        await _call(client.update_ai_provider, "openai", {"enabled": False})
        await _call(client.set_ai_provider_credential, "openai", "sk-reattach")

        # A brand-new CoreApiClient/session, exactly as a fresh Desktop
        # attach would open, must observe the same Core-authoritative state
        # -- nothing about it is cached client-side as truth.
        second = CoreApiClient(client.base_url, credential)
        await _call(second.connect)
        try:
            providers = await _call(second.list_ai_providers)
        finally:
            await _call(second.close)

    assert providers[0]["enabled"] is False
    assert providers[0]["credential"]["configured"] is True


# -- 22-24: no secret leakage in Audit --------------------------------------


@pytest.mark.asyncio
async def test_no_secret_appears_in_audit_for_any_credential_write(
    tmp_path: Path,
) -> None:
    async with _running_host(tmp_path) as (client, core, _credential):
        await _call(client.set_ai_provider_credential, "openai", "sk-audit-secret")
        await _call(client.delete_ai_provider_credential, "openai")
        await _call(client.set_memory_credential, "sk-memory-audit-secret")
        await _call(client.delete_memory_credential)

        entries = await core.execution_runtime.audit.query()

    event_types = {entry.event_type for entry in entries}
    assert "PROVIDER_CREDENTIAL_UPDATED" in event_types
    assert "PROVIDER_CREDENTIAL_DELETED" in event_types
    for entry in entries:
        assert "sk-audit-secret" not in str(entry.metadata)
        assert "sk-memory-audit-secret" not in str(entry.metadata)
        assert "sk-audit-secret" not in str(entry.authority_context)
        assert "sk-memory-audit-secret" not in str(entry.authority_context)
