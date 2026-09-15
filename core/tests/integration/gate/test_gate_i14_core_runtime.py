"""Gate I14 - Production Core Runtime.

Vertical acceptance for SA-B035 (Runtime Configuration & Provider Bootstrap)
and SA-B036 (Production Core Host), against Architecture Review Amendment
0003 and the AI Runtime Configuration Contract v1.

Every scenario drives the real `sofias_assistant.host.runner.run` lifecycle
-- the same composition `sofia-core` uses in production -- with deterministic
fakes standing in only for the Windows platform secret store, instance
ownership, and the OpenAI SDK transport, so the suite proves the actual
Contract v1 wiring rather than a parallel test-only path.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sofias_assistant.client_app.api import CoreApiClient
from sofias_assistant.core.core import CoreState
from sofias_assistant.health.models import HealthStatus, RuntimeHealthSnapshot
from sofias_assistant.host import runner
from sofias_assistant.runtime.instance_ownership import CoreAlreadyRunningError
from tests.integration.core.test_core import FakeSecretStore, fake_ownership_factory

# ---------------------------------------------------------------------------
# Shared fakes and helpers
# ---------------------------------------------------------------------------


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _base_environment(
    tmp_path: Path, *, model: str = "gate-i14-model"
) -> dict[str, str]:
    return {
        "SOFIA_DATA_DIR": str(tmp_path / "core-data"),
        "SOFIA_CORE_PORT": str(_free_loopback_port()),
        "LLM_MODEL": model,
    }


def _component(snapshot: RuntimeHealthSnapshot, name: str) -> Any:
    return next(
        component for component in snapshot.components if component.name == name
    )


class _FakeStreamingResponse:
    """Minimal async-iterable stand-in for a streamed OpenAI Responses call."""

    def __init__(self, text: str) -> None:
        self._events = iter(
            [
                SimpleNamespace(type="response.output_text.delta", delta=text),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(status="completed", usage=None),
                ),
            ]
        )

    def __aiter__(self) -> _FakeStreamingResponse:
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None


class _FakeOpenAIResponses:
    """Minimal stand-in for `AsyncOpenAI().responses`."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict[str, Any]] = []

    async def create(
        self, *, stream: bool = False, **kwargs: Any
    ) -> SimpleNamespace | _FakeStreamingResponse:
        self.calls.append({"stream": stream, **kwargs})
        if stream:
            return _FakeStreamingResponse(self._text)
        return SimpleNamespace(
            status="completed",
            output_text=self._text,
            usage=None,
            output=(),
            _request_id=None,
        )


class _FakeOpenAIClient:
    def __init__(self, text: str) -> None:
        self.responses = _FakeOpenAIResponses(text)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _fake_client_factory(
    text: str, captured_api_keys: list[str]
) -> tuple[Any, list[_FakeOpenAIClient]]:
    clients: list[_FakeOpenAIClient] = []

    def factory(api_key: str) -> _FakeOpenAIClient:
        captured_api_keys.append(api_key)
        client = _FakeOpenAIClient(text)
        clients.append(client)
        return client

    return factory, clients


class _RunningHost:
    """A started `sofia-core` host under deterministic test control."""

    def __init__(
        self,
        task: asyncio.Task[int],
        shutdown_event: asyncio.Event,
        access: Any,
        core: Any,
    ) -> None:
        self.task = task
        self.shutdown_event = shutdown_event
        self.access = access
        self.core = core

    async def stop(self) -> int:
        self.shutdown_event.set()
        return await self.task


async def _start_host(
    environment: Mapping[str, str],
    *,
    env_file: Path | None = None,
    ownership_factory: Any = fake_ownership_factory,
    client_factory: Any = None,
) -> _RunningHost:
    """Start the real host lifecycle and block until READY or failure."""

    shutdown_event = asyncio.Event()
    ready: asyncio.Future[tuple[Any, Any]] = asyncio.get_running_loop().create_future()

    def on_ready(access: Any, core: Any) -> None:
        if not ready.done():
            ready.set_result((access, core))

    task = asyncio.create_task(
        runner.run(
            environment=environment,
            env_file=env_file,
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=ownership_factory,
            client_factory=client_factory,
            shutdown_event=shutdown_event,
            on_ready=on_ready,
            install_signal_handlers=False,
        )
    )
    waitable: set[asyncio.Future[Any]] = {task, ready}
    done, _pending = await asyncio.wait(waitable, return_when=asyncio.FIRST_COMPLETED)
    if task in done and not ready.done():
        exit_code = task.result()
        raise AssertionError(f"host failed to reach READY (exit code {exit_code})")
    access, core = await ready
    return _RunningHost(task, shutdown_event, access, core)


def _sync_core_snapshot(base_url: str, credential: str) -> dict[str, Any]:
    client = CoreApiClient(base_url, credential)
    try:
        payload = client.connect()
        return payload["core"]
    finally:
        client.close()


def _run_one_text_turn(
    base_url: str, credential: str, text: str
) -> list[dict[str, Any]]:
    """Post one Turn requesting `cloud_allowed` locality.

    `CoreApiClient.stream_text` hardcodes `local_only` for its Desktop
    convenience path (unrelated to Gate I14), which would never route to
    the canonical cloud OpenAI composition this Gate proves; this test
    talks to the same authenticated endpoint directly instead.
    """

    client = CoreApiClient(base_url, credential)
    try:
        client.connect()
        conversation_id = client.create_conversation()
        response = client._http.stream(
            "POST",
            f"/api/v1/conversations/{conversation_id}/turns",
            headers=client._headers(),
            json={
                "text": text,
                "locality": "cloud_allowed",
                "cloud_context_eligible": True,
            },
        )
        records: list[dict[str, Any]] = []
        with response as stream:
            for line in stream.iter_lines():
                if not line:
                    continue
                records.append(json.loads(line))
        return records
    finally:
        client.close()


async def _core_snapshot(host: _RunningHost) -> dict[str, Any]:
    base_url = f"http://{host.access.host}:{host.access.port}"
    return await asyncio.to_thread(
        _sync_core_snapshot, base_url, host.access.credential.reveal()
    )


async def _run_text_turn(host: _RunningHost, text: str) -> list[dict[str, Any]]:
    base_url = f"http://{host.access.host}:{host.access.port}"
    return await asyncio.to_thread(
        _run_one_text_turn, base_url, host.access.credential.reveal(), text
    )


# ---------------------------------------------------------------------------
# 1-3. Env precedence, explicit env-file loading, no implicit discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_env_file_and_process_environment_precedence(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                f"SOFIA_DATA_DIR={tmp_path / 'core-data'}",
                f"SOFIA_CORE_PORT={_free_loopback_port()}",
                "LLM_MODEL=model-from-file",
            ]
        ),
        encoding="utf-8",
    )
    environment = {"LLM_MODEL": "model-from-real-environment"}

    host = await _start_host(environment, env_file=env_file)
    try:
        component = _component(host.core.health, "llm-provider")
        # Process environment overrides the explicitly selected env file.
        assert "model=model-from-real-environment" in component.detail
        # Values only the file supplied (SOFIA_DATA_DIR/PORT) still applied.
        assert host.access.host == "127.0.0.1"
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_no_implicit_env_file_is_ever_discovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("LLM_MODEL=should-never-load\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    environment = _base_environment(tmp_path, model="explicit-model")

    host = await _start_host(environment)
    try:
        component = _component(host.core.health, "llm-provider")
        assert "model=explicit-model" in component.detail
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 4. Provider bootstrap + SecretService bridge, end to end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_bootstrap_and_secret_bridge_end_to_end(tmp_path: Path) -> None:
    captured_api_keys: list[str] = []
    client_factory, _clients = _fake_client_factory(
        "Ola! Sou a Sofia.", captured_api_keys
    )
    environment = {
        **_base_environment(tmp_path),
        "LLM_API_KEY": "sk-from-process-environment",
    }

    host = await _start_host(environment, client_factory=client_factory)
    try:
        records = await _run_text_turn(host, "Oi Sofia")
        completed = next(r for r in records if r["type"] == "turn_completed")
        assert completed["turn"]["status"] == "COMPLETED"
        assert completed["turn"]["assistant_text"] == "Ola! Sou a Sofia."
        assert completed["turn"]["provider_id"] == "openai"
        assert completed["turn"]["model_id"] == "gate-i14-model"
        # The adapter never read LLM_API_KEY itself: it received exactly the
        # value SecretService resolved through the environment bridge.
        assert captured_api_keys == ["sk-from-process-environment"]
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 5. Invalid configuration fails before any side effect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "override",
    [
        {"LLM_MODEL": ""},
        {"SOFIA_CORE_PORT": "0"},
        {"SOFIA_CORE_HOST": "0.0.0.0"},
        {"SOFIA_CORE_PORT": "not-a-number"},
        {"LLM_BASE_URL": "not-a-url"},
        {"SOFIAS_MEMORY_ENABLED": "sure"},
    ],
)
async def test_invalid_configuration_returns_nonzero_before_any_side_effect(
    tmp_path: Path, override: dict[str, str]
) -> None:
    environment = {**_base_environment(tmp_path), **override}
    ownership_calls: list[Path] = []

    def tracking_ownership_factory(data_dir: Path) -> Any:
        ownership_calls.append(data_dir)
        return fake_ownership_factory(data_dir)

    exit_code = await runner.run(
        environment=environment,
        platform_secret_store_factory=FakeSecretStore,
        instance_ownership_factory=tracking_ownership_factory,
        install_signal_handlers=False,
    )

    assert exit_code == 1
    assert ownership_calls == []


# ---------------------------------------------------------------------------
# 6-7. Sofias Memory: disabled vs. enabled-but-unreachable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_disabled_reports_not_configured(tmp_path: Path) -> None:
    host = await _start_host(_base_environment(tmp_path))
    try:
        component = _component(host.core.health, "sofias-memory")
        assert component.status is HealthStatus.UNKNOWN
        assert "not configured" in (component.detail or "").lower()
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_memory_enabled_but_unreachable_degrades_without_killing_core(
    tmp_path: Path,
) -> None:
    unused_port = _free_loopback_port()
    environment = {
        **_base_environment(tmp_path),
        "SOFIAS_MEMORY_ENABLED": "true",
        "SOFIAS_MEMORY_BASE_URL": f"http://127.0.0.1:{unused_port}",
    }

    host = await _start_host(environment)
    try:
        assert host.core.state is CoreState.RUNNING
        memory_component = _component(host.core.health, "sofias-memory")
        assert memory_component.status is HealthStatus.DEGRADED
        # Core lifecycle and the authenticated boundary remain fully usable.
        snapshot = await _core_snapshot(host)
        assert snapshot["state"] == "running"
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 8. Readiness distinguishes canonical provider / credential state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_reports_missing_canonical_credential(tmp_path: Path) -> None:
    host = await _start_host(_base_environment(tmp_path))
    try:
        component = _component(host.core.health, "llm-provider-credential")
        assert component.status is HealthStatus.DEGRADED
        assert "LLM_API_KEY" in (component.detail or "")
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


@pytest.mark.asyncio
async def test_readiness_reports_configured_canonical_credential(
    tmp_path: Path,
) -> None:
    environment = {**_base_environment(tmp_path), "LLM_API_KEY": "sk-configured"}

    host = await _start_host(environment)
    try:
        component = _component(host.core.health, "llm-provider-credential")
        assert component.status is HealthStatus.HEALTHY
        assert component.detail == "configured"
    finally:
        exit_code = await host.stop()
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 9-10. Graceful shutdown and loopback-only default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_shutdown_stops_boundary_and_core(tmp_path: Path) -> None:
    host = await _start_host(_base_environment(tmp_path))

    assert host.access.host == "127.0.0.1"
    assert host.core.state is CoreState.RUNNING

    exit_code = await host.stop()

    assert exit_code == 0
    assert host.core.state is CoreState.STOPPED


# ---------------------------------------------------------------------------
# 11. Failed-start cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_boundary_bind_releases_ownership_and_returns_nonzero(
    tmp_path: Path,
) -> None:
    occupied_port = _free_loopback_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", occupied_port))
    blocker.listen()
    try:
        environment = {
            **_base_environment(tmp_path),
            "SOFIA_CORE_PORT": str(occupied_port),
        }
        released: list[bool] = []

        class _TrackingOwnership:
            def acquire(self) -> None:
                pass

            def release(self) -> None:
                released.append(True)

        exit_code = await runner.run(
            environment=environment,
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=lambda _: _TrackingOwnership(),
            install_signal_handlers=False,
        )

        assert exit_code == 1
        assert released == [True]
    finally:
        blocker.close()


# ---------------------------------------------------------------------------
# 12. Duplicate instance is rejected clearly
# ---------------------------------------------------------------------------


class _RaisingSharedOwnership:
    def __init__(self) -> None:
        self._acquired = False

    def acquire(self) -> None:
        if self._acquired:
            raise CoreAlreadyRunningError()
        self._acquired = True

    def release(self) -> None:
        self._acquired = False


@pytest.mark.asyncio
async def test_duplicate_instance_is_rejected_clearly(tmp_path: Path) -> None:
    shared_ownership = _RaisingSharedOwnership()
    ownership_factory = lambda _: shared_ownership  # noqa: E731

    host = await _start_host(
        _base_environment(tmp_path), ownership_factory=ownership_factory
    )
    try:
        exit_code = await runner.run(
            environment=_base_environment(tmp_path, model="second-instance"),
            platform_secret_store_factory=FakeSecretStore,
            instance_ownership_factory=ownership_factory,
            install_signal_handlers=False,
        )

        assert exit_code == 1
        # The first instance is completely unaffected.
        assert host.core.state is CoreState.RUNNING
    finally:
        exit_code = await host.stop()
        assert exit_code == 0
