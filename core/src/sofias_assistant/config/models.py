"""Immutable runtime configuration value objects."""

from dataclasses import dataclass, field
from pathlib import Path


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
class RuntimeConfig:
    """Runtime configuration currently limited to local application paths."""

    paths: AppPaths
