"""Process lifecycle for the standalone `sofia-core` production Core host.

Implements the Contract v1 SS12 lifecycle exactly:

    parse bootstrap inputs
    load explicit env file, if selected
    overlay process environment
    validate RuntimeConfig
    construct SecretService
    construct canonical AI composition
    construct Memory composition
    construct SofiaCore
    Core.start()
    LocalClientBoundary.start()
    READY
    wait for shutdown
    LocalClientBoundary.stop()
    Core.stop()
    exit

This module contains only composition, signal handling, lifecycle
coordination and safe startup diagnostics -- no Conversation, Tool, Agent,
routing or Memory domain logic (Contract v1 SS12).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from collections.abc import Callable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sofias_assistant.client_boundary.boundary import (
    LocalClientAccess,
    LocalClientBoundary,
)
from sofias_assistant.config.loader import resolve_environment
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.health.models import ComponentHealth, HealthStatus
from sofias_assistant.host.composition import (
    build_conversation_dependencies_factory,
    build_runtime_config,
    build_secret_store_factory,
    create_app_factory,
)
from sofias_assistant.host.config import (
    ProductionRuntimeConfig,
    load_production_runtime_config,
)
from sofias_assistant.host.secret_bridge import (
    LLM_API_KEY_ENVIRONMENT_VARIABLE,
    provider_api_key_ref,
)
from sofias_assistant.runtime.instance_ownership import (
    CoreInstanceOwnership,
    InstanceOwnership,
)
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.store import SecretStore
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

_PROGRAM_NAME = "sofia-core"


def _application_version() -> str:
    try:
        return version("sofias-assistant")
    except Exception:  # pragma: no cover - defensive fallback, not expected in practice
        return "0.0.0"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_PROGRAM_NAME,
        description="Sofia's Assistant standalone production Core host.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help=(
            "Explicit .env file to load. Nothing is loaded automatically: "
            "omit this flag to configure entirely through the process "
            "environment."
        ),
    )
    return parser


async def run(
    *,
    env_file: Path | None = None,
    environment: Mapping[str, str] | None = None,
    application_version: str | None = None,
    platform_secret_store_factory: Callable[[], SecretStore] = WindowsCredentialStore,
    instance_ownership_factory: Callable[
        [Path], InstanceOwnership
    ] = CoreInstanceOwnership,
    client_factory: Callable[[str], Any] | None = None,
    shutdown_event: asyncio.Event | None = None,
    on_ready: Callable[[LocalClientAccess, SofiaCore], None] | None = None,
    install_signal_handlers: bool = True,
) -> int:
    """Run one full Core host lifecycle; return a process-coherent exit code.

    Fully testable without touching real signals or sleeping: pass an
    explicit `shutdown_event` and set it to request a deterministic,
    graceful shutdown instead of waiting for Ctrl+C/SIGINT/SIGTERM.
    """

    real_environment = os.environ if environment is None else environment
    try:
        config = load_production_runtime_config(
            environment=real_environment, env_file=env_file
        )
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        print(f"{_PROGRAM_NAME}: configuration error: {error}", file=sys.stderr)
        return 1

    resolved_environment = resolve_environment(
        environment=real_environment, env_file=env_file
    )
    secret_store_factory = build_secret_store_factory(
        environment=resolved_environment,
        llm_provider_id=config.llm.provider_id,
        platform_secret_store_factory=platform_secret_store_factory,
    )

    core = SofiaCore(
        build_runtime_config(config),
        application_version=application_version or _application_version(),
        secret_store_factory=secret_store_factory,
        instance_ownership_factory=instance_ownership_factory,
        conversation_dependencies_factory=build_conversation_dependencies_factory(
            config.llm, client_factory=client_factory
        ),
    )

    try:
        await core.start()
    except Exception as error:
        print(f"{_PROGRAM_NAME}: failed to start Core: {error}", file=sys.stderr)
        return 1

    boundary = LocalClientBoundary(
        port=config.core_host.port, app_factory=create_app_factory(core)
    )
    try:
        await _report_ai_readiness(core, config, core.secret_service)
        access = await boundary.start()
    except Exception as error:
        print(
            f"{_PROGRAM_NAME}: failed to start Local Client Boundary: {error}",
            file=sys.stderr,
        )
        await core.stop()
        return 1

    print(f"{_PROGRAM_NAME}: READY on {access.host}:{access.port}", flush=True)
    if on_ready is not None:
        on_ready(access, core)

    await _wait_for_shutdown(
        shutdown_event=shutdown_event,
        install_signal_handlers=install_signal_handlers,
    )

    try:
        await boundary.stop()
    finally:
        await core.stop()
    print(f"{_PROGRAM_NAME}: stopped", flush=True)
    return 0


async def _report_ai_readiness(
    core: SofiaCore, config: ProductionRuntimeConfig, secret_service: SecretService
) -> None:
    """Publish safe, value-free canonical AI health facts (Contract v1 SS40).

    A missing provider credential degrades AI readiness; it never fails
    Core startup, mirroring Memory's existing degrade-not-die semantics.
    """

    await core.update_health(
        ComponentHealth(
            "llm-provider",
            HealthStatus.HEALTHY,
            f"canonical provider={config.llm.provider_id} model={config.llm.model_id}",
        )
    )
    secret_configured = (
        secret_service.get(provider_api_key_ref(config.llm.provider_id)) is not None
    )
    await core.update_health(
        ComponentHealth(
            "llm-provider-credential",
            HealthStatus.HEALTHY if secret_configured else HealthStatus.DEGRADED,
            "configured"
            if secret_configured
            else f"{LLM_API_KEY_ENVIRONMENT_VARIABLE} missing",
        )
    )


async def _wait_for_shutdown(
    *, shutdown_event: asyncio.Event | None, install_signal_handlers: bool
) -> None:
    event = shutdown_event if shutdown_event is not None else asyncio.Event()
    handlers_installed: list[signal.Signals] = []
    if install_signal_handlers:
        loop = asyncio.get_running_loop()
        for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, event.set)
                handlers_installed.append(sig)
            except NotImplementedError:
                # Not supported on Windows' default event loop; Ctrl+C still
                # raises KeyboardInterrupt, handled below.
                pass
    try:
        await event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if install_signal_handlers:
            loop = asyncio.get_running_loop()
            for sig in handlers_installed:
                loop.remove_signal_handler(sig)


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point for `sofia-core`."""

    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(run(env_file=args.env_file))
    except KeyboardInterrupt:  # pragma: no cover - real Ctrl+C before READY
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
