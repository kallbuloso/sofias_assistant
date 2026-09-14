"""Unit tests for deterministic runtime configuration resolution."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sofias_assistant.config import (
    AppPaths,
    RuntimeConfig,
    load_runtime_config,
    resolve_environment,
)


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


def test_without_env_file_behavior_is_unchanged(tmp_path: Path) -> None:
    data_dir = tmp_path / "custom-data"

    config = load_runtime_config(
        environment={"SOFIAS_ASSISTANT_DATA_DIR": str(data_dir)},
        platform_name="nt",
    )

    assert config.paths.data_dir == data_dir
    assert not config.memory.enabled


def test_env_file_supplies_non_secret_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment line is ignored",
                "",
                "SOFIAS_ASSISTANT_MEMORY_BASE_URL=https://memory.example.test",
                "SOFIAS_ASSISTANT_MEMORY_TIMEOUT_SECONDS=15",
                "SOFIAS_ASSISTANT_MEMORY_RECALL_LIMIT=7",
                'SOFIAS_ASSISTANT_DATA_DIR="C:\\quoted\\data"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_runtime_config(environment={}, platform_name="nt", env_file=env_file)

    assert config.paths.data_dir == Path("C:\\quoted\\data")
    assert config.memory.enabled is True
    assert config.memory.base_url == "https://memory.example.test"
    assert config.memory.timeout_seconds == 15.0
    assert config.memory.recall_limit == 7


def test_real_environment_takes_precedence_over_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOFIAS_ASSISTANT_MEMORY_BASE_URL=https://from-file.example.test\n",
        encoding="utf-8",
    )

    config = load_runtime_config(
        environment={
            "SOFIAS_ASSISTANT_DATA_DIR": str(tmp_path / "data"),
            "SOFIAS_ASSISTANT_MEMORY_BASE_URL": "https://from-real-environment.test",
        },
        platform_name="nt",
        env_file=env_file,
    )

    assert config.memory.base_url == "https://from-real-environment.test"


def test_missing_env_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_runtime_config(
            environment={"SOFIAS_ASSISTANT_DATA_DIR": str(tmp_path / "data")},
            platform_name="nt",
            env_file=tmp_path / "does-not-exist.env",
        )


def test_invalid_env_file_line_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NOT_A_KEY_VALUE_LINE\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid env_file line"):
        load_runtime_config(
            environment={"SOFIAS_ASSISTANT_DATA_DIR": str(tmp_path / "data")},
            platform_name="nt",
            env_file=env_file,
        )


def test_resolve_environment_without_env_file_returns_given_mapping() -> None:
    environment = {"SOME_KEY": "some-value"}

    assert resolve_environment(environment=environment) is environment


def test_resolve_environment_merges_file_under_real_environment(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SOFIAS_ASSISTANT_RUN_MEMORY_INTEGRATION_TESTS=1",
                "OVERRIDDEN=from-file",
            ]
        ),
        encoding="utf-8",
    )

    merged = resolve_environment(
        environment={"OVERRIDDEN": "from-real-environment"}, env_file=env_file
    )

    assert merged["SOFIAS_ASSISTANT_RUN_MEMORY_INTEGRATION_TESTS"] == "1"
    assert merged["OVERRIDDEN"] == "from-real-environment"
