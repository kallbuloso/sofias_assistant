"""Runtime configuration boundary."""

from sofias_assistant.config.loader import load_runtime_config
from sofias_assistant.config.models import AppPaths, RuntimeConfig, SofiasMemoryConfig

__all__ = [
    "AppPaths",
    "RuntimeConfig",
    "SofiasMemoryConfig",
    "load_runtime_config",
]
