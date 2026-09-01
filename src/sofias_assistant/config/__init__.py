"""Runtime configuration boundary."""

from sofias_assistant.config.loader import load_runtime_config
from sofias_assistant.config.models import AppPaths, RuntimeConfig

__all__ = ["AppPaths", "RuntimeConfig", "load_runtime_config"]
