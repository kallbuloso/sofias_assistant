"""Unit tests for the production Core host bootstrap configuration (Gate I14)."""

from pathlib import Path

import pytest

from sofias_assistant.host.config import (
    CoreHostConfig,
    LLMProviderConfig,
    load_production_runtime_config,
)

_MINIMAL_ENVIRONMENT = {
    "LLM_MODEL": "example-model",
    "SOFIA_DATA_DIR": "C:/sofia-core-test-data",
}


def test_defaults_apply_when_only_the_required_model_is_set() -> None:
    config = load_production_runtime_config(
        environment=_MINIMAL_ENVIRONMENT, platform_name="nt"
    )

    assert config.core_host == CoreHostConfig(host="127.0.0.1", port=8989)
    assert config.llm == LLMProviderConfig(
        provider_id="openai",
        base_url="https://api.openai.com/v1",
        model_id="example-model",
    )
    assert config.memory.enabled is False
    assert config.memory.base_url is None


def test_process_environment_overrides_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=from-file\nSOFIA_CORE_PORT=9000\n", encoding="utf-8")

    config = load_production_runtime_config(
        environment={
            "LLM_MODEL": "from-real-environment",
            "SOFIA_DATA_DIR": "C:/sofia-core-test-data",
        },
        env_file=env_file,
        platform_name="nt",
    )

    assert config.llm.model_id == "from-real-environment"
    # Untouched by the real environment: the env file value still applies.
    assert config.core_host.port == 9000


def test_explicit_env_file_values_apply_without_being_in_real_environment(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MODEL=from-file-only\nSOFIA_DATA_DIR=C:/sofia-core-test-data\n",
        encoding="utf-8",
    )

    config = load_production_runtime_config(
        environment={}, env_file=env_file, platform_name="nt"
    )

    assert config.llm.model_id == "from-file-only"


def test_no_implicit_env_file_is_ever_discovered(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("LLM_MODEL=should-never-load\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    config = load_production_runtime_config(
        environment=_MINIMAL_ENVIRONMENT, platform_name="nt"
    )

    assert config.llm.model_id == "example-model"


@pytest.mark.parametrize("port_value", ["0", "65536", "-1", "not-a-number"])
def test_invalid_port_is_rejected(port_value: str) -> None:
    with pytest.raises(ValueError, match="SOFIA_CORE_PORT"):
        load_production_runtime_config(
            environment={**_MINIMAL_ENVIRONMENT, "SOFIA_CORE_PORT": port_value},
            platform_name="nt",
        )


@pytest.mark.parametrize("host_value", ["0.0.0.0", "localhost", "10.0.0.5", ""])
def test_non_loopback_host_is_rejected(host_value: str) -> None:
    with pytest.raises(ValueError, match="SOFIA_CORE_HOST"):
        load_production_runtime_config(
            environment={**_MINIMAL_ENVIRONMENT, "SOFIA_CORE_HOST": host_value},
            platform_name="nt",
        )


@pytest.mark.parametrize(
    "base_url",
    ["not-a-url", "ftp://example.test", "https://", "https://u:p@example.test"],
)
def test_malformed_llm_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        load_production_runtime_config(
            environment={**_MINIMAL_ENVIRONMENT, "LLM_BASE_URL": base_url},
            platform_name="nt",
        )


def test_blank_llm_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_production_runtime_config(
            environment={**_MINIMAL_ENVIRONMENT, "LLM_PROVIDER": "  "},
            platform_name="nt",
        )


def test_blank_llm_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="LLM_MODEL"):
        load_production_runtime_config(
            environment={"SOFIA_DATA_DIR": "C:/sofia-core-test-data"},
            platform_name="nt",
        )


@pytest.mark.parametrize("enabled_value", ["true", "1", "yes", "on", "TRUE"])
def test_memory_enabled_true_requires_and_accepts_base_url(enabled_value: str) -> None:
    config = load_production_runtime_config(
        environment={
            **_MINIMAL_ENVIRONMENT,
            "SOFIAS_MEMORY_ENABLED": enabled_value,
            "SOFIAS_MEMORY_BASE_URL": "https://memory.example.test",
        },
        platform_name="nt",
    )

    assert config.memory.enabled is True
    assert config.memory.base_url == "https://memory.example.test"


@pytest.mark.parametrize("enabled_value", ["false", "0", "no", "off", "FALSE"])
def test_memory_enabled_false_variants_disable_memory(enabled_value: str) -> None:
    config = load_production_runtime_config(
        environment={**_MINIMAL_ENVIRONMENT, "SOFIAS_MEMORY_ENABLED": enabled_value},
        platform_name="nt",
    )

    assert config.memory.enabled is False


def test_memory_unset_defaults_to_disabled() -> None:
    config = load_production_runtime_config(
        environment=_MINIMAL_ENVIRONMENT, platform_name="nt"
    )

    assert config.memory.enabled is False


def test_invalid_memory_enabled_value_fails_closed() -> None:
    with pytest.raises(ValueError, match="SOFIAS_MEMORY_ENABLED"):
        load_production_runtime_config(
            environment={**_MINIMAL_ENVIRONMENT, "SOFIAS_MEMORY_ENABLED": "sure"},
            platform_name="nt",
        )


def test_memory_enabled_without_base_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="base_url"):
        load_production_runtime_config(
            environment={**_MINIMAL_ENVIRONMENT, "SOFIAS_MEMORY_ENABLED": "true"},
            platform_name="nt",
        )


def test_blank_data_dir_resolves_to_platform_default(tmp_path: Path) -> None:
    config = load_production_runtime_config(
        environment={
            **_MINIMAL_ENVIRONMENT,
            "SOFIA_DATA_DIR": "  ",
            "LOCALAPPDATA": str(tmp_path),
        },
        platform_name="nt",
    )

    assert config.data_dir == tmp_path / "SofiasAssistant"


def test_explicit_data_dir_overrides_platform_default(tmp_path: Path) -> None:
    custom = tmp_path / "custom-data"

    config = load_production_runtime_config(
        environment={**_MINIMAL_ENVIRONMENT, "SOFIA_DATA_DIR": str(custom)},
        platform_name="nt",
    )

    assert config.data_dir == custom


def test_non_windows_without_data_dir_override_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="SOFIA_DATA_DIR"):
        load_production_runtime_config(
            environment={"LLM_MODEL": "example-model"}, platform_name="posix"
        )
