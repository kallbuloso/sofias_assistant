"""Unit tests for deterministic runtime configuration resolution."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sofias_assistant.config import AppPaths, RuntimeConfig, load_runtime_config


def test_explicit_data_directory_override_derives_runtime_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "custom-data"

    config = load_runtime_config(
        environment={"SOFIAS_ASSISTANT_DATA_DIR": str(data_dir)},
        platform_name="nt",
    )

    assert config.paths.data_dir == data_dir
    assert config.paths.operational_database == data_dir / "operational.sqlite"
    assert config.paths.logs_dir == data_dir / "logs"


def test_explicit_data_directory_override_takes_precedence(tmp_path: Path) -> None:
    override = tmp_path / "override"
    local_app_data = tmp_path / "local-app-data"

    config = load_runtime_config(
        environment={
            "SOFIAS_ASSISTANT_DATA_DIR": str(override),
            "LOCALAPPDATA": str(local_app_data),
        },
        platform_name="nt",
    )

    assert config.paths.data_dir == override


def test_windows_default_uses_local_app_data(tmp_path: Path) -> None:
    local_app_data = tmp_path / "local-app-data"

    config = load_runtime_config(
        environment={"LOCALAPPDATA": str(local_app_data)},
        platform_name="nt",
    )

    assert config.paths.data_dir == local_app_data / "SofiasAssistant"


@pytest.mark.parametrize("override", ["", "   "])
def test_blank_data_directory_override_is_rejected(override: str) -> None:
    with pytest.raises(ValueError, match="SOFIAS_ASSISTANT_DATA_DIR.*blank"):
        load_runtime_config(
            environment={"SOFIAS_ASSISTANT_DATA_DIR": override},
            platform_name="nt",
        )


def test_missing_local_app_data_on_windows_is_rejected() -> None:
    with pytest.raises(ValueError, match="LOCALAPPDATA.*must be set"):
        load_runtime_config(environment={}, platform_name="nt")


def test_explicit_override_works_on_non_windows(tmp_path: Path) -> None:
    data_dir = tmp_path / "portable-data"

    config = load_runtime_config(
        environment={"SOFIAS_ASSISTANT_DATA_DIR": str(data_dir)},
        platform_name="posix",
    )

    assert config.paths.data_dir == data_dir


def test_non_windows_without_override_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="only for Windows"):
        load_runtime_config(environment={}, platform_name="posix")


def test_loading_configuration_has_no_filesystem_side_effects(tmp_path: Path) -> None:
    data_dir = tmp_path / "not-created"

    config = load_runtime_config(
        environment={"SOFIAS_ASSISTANT_DATA_DIR": str(data_dir)},
        platform_name="nt",
    )

    assert not config.paths.data_dir.exists()
    assert not config.paths.logs_dir.exists()
    assert not config.paths.operational_database.exists()


def test_runtime_configuration_values_are_immutable(tmp_path: Path) -> None:
    paths = AppPaths(data_dir=tmp_path / "data")
    config = RuntimeConfig(paths=paths)

    with pytest.raises(FrozenInstanceError):
        setattr(paths, "data_dir", tmp_path / "other-data")
    with pytest.raises(FrozenInstanceError):
        setattr(config, "paths", AppPaths(data_dir=tmp_path / "other-data"))
