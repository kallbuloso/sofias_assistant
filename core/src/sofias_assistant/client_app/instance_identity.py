"""Desktop-side instance identity resolution (Desktop/Core Interaction Contract v1 SS5).

Reuses the exact same data-directory resolution rule as the production Core
host (`host.config.resolve_core_data_dir`) and the exact same hashing rule as
Core single-instance ownership (`runtime.instance_ownership.instance_key_for_data_dir`)
so the Desktop and the Core agree on one identical `instance_key` without
duplicating either normalization rule.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from sofias_assistant.host.config import resolve_core_data_dir
from sofias_assistant.runtime.instance_ownership import instance_key_for_data_dir


def resolve_expected_instance_key(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> str:
    """Resolve the `instance_key` of the Core instance this Desktop expects."""

    real_environment = os.environ if environment is None else environment
    real_platform_name = os.name if platform_name is None else platform_name
    data_dir = resolve_core_data_dir(real_environment, real_platform_name)
    return instance_key_for_data_dir(data_dir)
