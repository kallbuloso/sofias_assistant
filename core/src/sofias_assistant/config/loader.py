"""Runtime configuration resolution from an explicit environment mapping."""

import os
from collections.abc import Mapping
from pathlib import Path

from sofias_assistant.config.models import AppPaths, RuntimeConfig, SofiasMemoryConfig

DATA_DIR_ENVIRONMENT_VARIABLE = "SOFIAS_ASSISTANT_DATA_DIR"
LOCAL_APP_DATA_ENVIRONMENT_VARIABLE = "LOCALAPPDATA"
WINDOWS_PLATFORM_NAME = "nt"

MEMORY_BASE_URL_ENVIRONMENT_VARIABLE = "SOFIAS_ASSISTANT_MEMORY_BASE_URL"
MEMORY_TIMEOUT_SECONDS_ENVIRONMENT_VARIABLE = "SOFIAS_ASSISTANT_MEMORY_TIMEOUT_SECONDS"
MEMORY_RECALL_LIMIT_ENVIRONMENT_VARIABLE = "SOFIAS_ASSISTANT_MEMORY_RECALL_LIMIT"
_DEFAULT_MEMORY_TIMEOUT_SECONDS = 8.0
_DEFAULT_MEMORY_RECALL_LIMIT = 10


def load_runtime_config(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> RuntimeConfig:
    """Resolve pure runtime configuration without creating filesystem resources."""

    source_environment = os.environ if environment is None else environment
    source_platform_name = os.name if platform_name is None else platform_name
    data_dir = _resolve_data_dir(source_environment, source_platform_name)
    return RuntimeConfig(
        paths=AppPaths(data_dir=data_dir),
        memory=_resolve_memory_config(source_environment),
    )


def _resolve_memory_config(environment: Mapping[str, str]) -> SofiasMemoryConfig:
    base_url = environment.get(MEMORY_BASE_URL_ENVIRONMENT_VARIABLE)
    if base_url is not None and not base_url.strip():
        raise ValueError(
            f"{MEMORY_BASE_URL_ENVIRONMENT_VARIABLE} must not be blank when set"
        )
    timeout_text = environment.get(MEMORY_TIMEOUT_SECONDS_ENVIRONMENT_VARIABLE)
    timeout_seconds = _DEFAULT_MEMORY_TIMEOUT_SECONDS
    if timeout_text is not None:
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as error:
            raise ValueError(
                f"{MEMORY_TIMEOUT_SECONDS_ENVIRONMENT_VARIABLE} must be numeric"
            ) from error
    recall_limit_text = environment.get(MEMORY_RECALL_LIMIT_ENVIRONMENT_VARIABLE)
    recall_limit = _DEFAULT_MEMORY_RECALL_LIMIT
    if recall_limit_text is not None:
        try:
            recall_limit = int(recall_limit_text)
        except ValueError as error:
            raise ValueError(
                f"{MEMORY_RECALL_LIMIT_ENVIRONMENT_VARIABLE} must be an integer"
            ) from error
    return SofiasMemoryConfig(
        enabled=base_url is not None,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        recall_limit=recall_limit,
    )


def _resolve_data_dir(environment: Mapping[str, str], platform_name: str) -> Path:
    override = environment.get(DATA_DIR_ENVIRONMENT_VARIABLE)
    if override is not None:
        if not override.strip():
            raise ValueError(f"{DATA_DIR_ENVIRONMENT_VARIABLE} must not be blank")
        return Path(override).expanduser()

    if platform_name != WINDOWS_PLATFORM_NAME:
        raise RuntimeError(
            "The default Sofia's Assistant data directory is currently defined only "
            "for Windows; set SOFIAS_ASSISTANT_DATA_DIR explicitly."
        )

    local_app_data = environment.get(LOCAL_APP_DATA_ENVIRONMENT_VARIABLE)
    if local_app_data is None or not local_app_data.strip():
        raise ValueError(
            f"{LOCAL_APP_DATA_ENVIRONMENT_VARIABLE} must be set for the Windows "
            "default data directory"
        )
    return Path(local_app_data).expanduser() / "SofiasAssistant"
