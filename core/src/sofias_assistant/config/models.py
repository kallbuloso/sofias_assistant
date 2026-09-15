"""Immutable runtime configuration value objects."""

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Local runtime paths derived from a single application data directory."""

    data_dir: Path
    operational_database: Path = field(init=False)
    logs_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "operational_database", self.data_dir / "operational.sqlite"
        )
        object.__setattr__(self, "logs_dir", self.data_dir / "logs")


@dataclass(frozen=True, slots=True)
class SofiasMemoryConfig:
    """Non-secret configuration for the Sofias Memory Cognitive Memory boundary.

    The API key never lives here; it is resolved exclusively through
    SecretService at call scope.
    """

    enabled: bool
    base_url: str | None
    timeout_seconds: float
    recall_limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if self.enabled and not self.base_url:
            raise ValueError("base_url is required when memory is enabled")
        if self.base_url is not None:
            _require_safe_memory_url(self.base_url)
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")
        if isinstance(self.recall_limit, bool) or not isinstance(
            self.recall_limit, int
        ):
            raise ValueError("recall_limit must be an integer")
        if not 1 <= self.recall_limit <= 50:
            raise ValueError("recall_limit must be between 1 and 50")


def require_safe_http_url(url: str, *, field_name: str) -> None:
    """Reject anything but a plain, credential-free http(s) URL with a host."""

    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{field_name} must use http or https")
    if not parsed.netloc:
        raise ValueError(f"{field_name} must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not embed credentials")
    if parsed.fragment:
        raise ValueError(f"{field_name} must not include a fragment")


def _require_safe_memory_url(base_url: str) -> None:
    require_safe_http_url(base_url, field_name="Memory base_url")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration for local application paths and integrations."""

    paths: AppPaths
    memory: SofiasMemoryConfig = field(
        default_factory=lambda: SofiasMemoryConfig(
            enabled=False, base_url=None, timeout_seconds=8.0, recall_limit=10
        )
    )
