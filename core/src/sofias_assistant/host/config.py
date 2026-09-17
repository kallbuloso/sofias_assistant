"""Production Core host bootstrap configuration (Runtime Configuration Contract v1).

Precedence is exactly three layers, never an implicit `.env` search:

    process environment
        overrides
    explicitly selected env file
        overrides
    code defaults

`resolve_environment` (config/loader.py) already implements that merge; this
module only interprets the merged mapping through the v1 bootstrap key set
and fails closed on structurally invalid values. No secret value is ever
held on `ProductionRuntimeConfig`: `LLM_API_KEY` and `SOFIAS_MEMORY_API_KEY`
are resolved exclusively through the secret bridge in
`sofias_assistant.host.secret_bridge`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sofias_assistant.config.loader import (
    resolve_environment,
    resolve_windows_default_data_dir,
)
from sofias_assistant.config.models import SofiasMemoryConfig, require_safe_http_url

CORE_HOST_ENVIRONMENT_VARIABLE = "SOFIA_CORE_HOST"
CORE_PORT_ENVIRONMENT_VARIABLE = "SOFIA_CORE_PORT"
DATA_DIR_ENVIRONMENT_VARIABLE = "SOFIA_DATA_DIR"
LLM_PROVIDER_ENVIRONMENT_VARIABLE = "LLM_PROVIDER"
LLM_BASE_URL_ENVIRONMENT_VARIABLE = "LLM_BASE_URL"
LLM_MODEL_ENVIRONMENT_VARIABLE = "LLM_MODEL"
MEMORY_ENABLED_ENVIRONMENT_VARIABLE = "SOFIAS_MEMORY_ENABLED"
MEMORY_BASE_URL_ENVIRONMENT_VARIABLE = "SOFIAS_MEMORY_BASE_URL"

_LOOPBACK_HOST = "127.0.0.1"
_DEFAULT_CORE_PORT = 8989
_DEFAULT_LLM_PROVIDER = "openai"
_DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MEMORY_TIMEOUT_SECONDS = 8.0
_DEFAULT_MEMORY_RECALL_LIMIT = 10
_WINDOWS_PLATFORM_NAME = "nt"

_TRUE_VALUES = {"true", "1", "yes", "on"}
_FALSE_VALUES = {"false", "0", "no", "off"}


@dataclass(frozen=True, slots=True)
class CoreHostConfig:
    """Validated loopback-only bind target for the production Core host."""

    host: str
    port: int

    def __post_init__(self) -> None:
        if self.host != _LOOPBACK_HOST:
            raise ValueError(
                f"{CORE_HOST_ENVIRONMENT_VARIABLE} must be {_LOOPBACK_HOST}; "
                "non-loopback binding is not supported by this Contract"
            )
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError(
                f"{CORE_PORT_ENVIRONMENT_VARIABLE} must be an integer between "
                "1 and 65535"
            )


@dataclass(frozen=True, slots=True)
class LLMProviderConfig:
    """Non-secret canonical/default AI provider bootstrap configuration."""

    provider_id: str
    base_url: str
    model_id: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError(f"{LLM_PROVIDER_ENVIRONMENT_VARIABLE} must not be blank")
        require_safe_http_url(
            self.base_url, field_name=LLM_BASE_URL_ENVIRONMENT_VARIABLE
        )
        if not self.model_id.strip():
            raise ValueError(f"{LLM_MODEL_ENVIRONMENT_VARIABLE} must not be blank")


@dataclass(frozen=True, slots=True)
class ProductionRuntimeConfig:
    """Validated production bootstrap configuration for the `sofia-core` host."""

    core_host: CoreHostConfig
    data_dir: Path
    llm: LLMProviderConfig
    memory: SofiasMemoryConfig


def load_production_runtime_config(
    *,
    environment: Mapping[str, str] | None = None,
    env_file: Path | None = None,
    platform_name: str | None = None,
) -> ProductionRuntimeConfig:
    """Resolve and validate the full v1 bootstrap key set; no filesystem I/O.

    `env_file` is opt-in and explicit, exactly like `resolve_environment`:
    nothing here ever discovers a `.env` file on its own.
    """

    resolved = resolve_environment(environment=environment, env_file=env_file)
    resolved_platform_name = os.name if platform_name is None else platform_name
    return ProductionRuntimeConfig(
        core_host=_resolve_core_host(resolved),
        data_dir=resolve_core_data_dir(resolved, resolved_platform_name),
        llm=_resolve_llm(resolved),
        memory=_resolve_memory(resolved),
    )


def _resolve_core_host(environment: Mapping[str, str]) -> CoreHostConfig:
    host = environment.get(CORE_HOST_ENVIRONMENT_VARIABLE, _LOOPBACK_HOST).strip()
    port_text = environment.get(CORE_PORT_ENVIRONMENT_VARIABLE)
    if port_text is None:
        port = _DEFAULT_CORE_PORT
    else:
        try:
            port = int(port_text.strip())
        except ValueError as error:
            raise ValueError(
                f"{CORE_PORT_ENVIRONMENT_VARIABLE} must be an integer"
            ) from error
    return CoreHostConfig(host=host, port=port)


def resolve_core_data_dir(environment: Mapping[str, str], platform_name: str) -> Path:
    """Resolve the production Core's canonical data directory.

    Public and reused by the Desktop Client (Architecture Review Amendment
    0004 SS8, Desktop/Core Interaction Contract v1 SS5) so both processes
    derive the identical `instance_key` from the identical data directory
    input instead of duplicating this precedence rule.
    """

    raw = environment.get(DATA_DIR_ENVIRONMENT_VARIABLE)
    override = raw.strip() if raw is not None else ""
    if override:
        return Path(override).expanduser()
    if platform_name != _WINDOWS_PLATFORM_NAME:
        raise RuntimeError(
            "The default Sofia's Assistant data directory is currently defined "
            "only for Windows; set SOFIA_DATA_DIR explicitly."
        )
    return resolve_windows_default_data_dir(environment)


def _resolve_llm(environment: Mapping[str, str]) -> LLMProviderConfig:
    provider_id = environment.get(
        LLM_PROVIDER_ENVIRONMENT_VARIABLE, _DEFAULT_LLM_PROVIDER
    ).strip()
    base_url = environment.get(
        LLM_BASE_URL_ENVIRONMENT_VARIABLE, _DEFAULT_LLM_BASE_URL
    ).strip()
    model_id = environment.get(LLM_MODEL_ENVIRONMENT_VARIABLE, "").strip()
    return LLMProviderConfig(
        provider_id=provider_id, base_url=base_url, model_id=model_id
    )


def _resolve_memory(environment: Mapping[str, str]) -> SofiasMemoryConfig:
    enabled_text = environment.get(MEMORY_ENABLED_ENVIRONMENT_VARIABLE)
    enabled = False if enabled_text is None else _parse_strict_bool(enabled_text)
    raw_base_url = environment.get(MEMORY_BASE_URL_ENVIRONMENT_VARIABLE)
    base_url = raw_base_url.strip() if raw_base_url and raw_base_url.strip() else None
    return SofiasMemoryConfig(
        enabled=enabled,
        base_url=base_url,
        timeout_seconds=_DEFAULT_MEMORY_TIMEOUT_SECONDS,
        recall_limit=_DEFAULT_MEMORY_RECALL_LIMIT,
    )


def _parse_strict_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{MEMORY_ENABLED_ENVIRONMENT_VARIABLE} must be a boolean value "
        "(true/false/1/0/yes/no/on/off)"
    )
