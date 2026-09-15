"""Unit tests for the known Contract v1 secret bridge mappings (Gate I14)."""

from sofias_assistant.host.secret_bridge import (
    LLM_API_KEY_ENVIRONMENT_VARIABLE,
    SOFIAS_MEMORY_API_KEY_ENVIRONMENT_VARIABLE,
    SOFIAS_MEMORY_API_KEY_REF,
    bootstrap_secret_mappings,
    describe_secret_source,
    provider_api_key_ref,
)
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService


class _FakeStore:
    def __init__(self, values: dict[SecretRef, SecretValue] | None = None) -> None:
        self._values = values or {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self._values.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self._values[ref] = value

    def delete(self, ref: SecretRef) -> bool:
        return self._values.pop(ref, None) is not None


def test_provider_api_key_ref_normalizes_provider_id() -> None:
    assert provider_api_key_ref("OpenAI") == SecretRef("providers/openai/api-key")
    assert provider_api_key_ref("  openai  ") == SecretRef("providers/openai/api-key")


def test_bootstrap_secret_mappings_are_exhaustive_and_known() -> None:
    mappings = bootstrap_secret_mappings(llm_provider_id="openai")

    assert mappings == {
        LLM_API_KEY_ENVIRONMENT_VARIABLE: SecretRef("providers/openai/api-key"),
        SOFIAS_MEMORY_API_KEY_ENVIRONMENT_VARIABLE: SOFIAS_MEMORY_API_KEY_REF,
    }


def test_describe_secret_source_prefers_real_environment() -> None:
    source = describe_secret_source(
        variable_name=LLM_API_KEY_ENVIRONMENT_VARIABLE,
        ref=SecretRef("providers/openai/api-key"),
        real_environment={LLM_API_KEY_ENVIRONMENT_VARIABLE: "sk-real"},
        env_file_environment={LLM_API_KEY_ENVIRONMENT_VARIABLE: "sk-file"},
        secret_service=SecretService(_FakeStore()),
    )

    assert source == "environment"


def test_describe_secret_source_falls_back_to_env_file() -> None:
    source = describe_secret_source(
        variable_name=LLM_API_KEY_ENVIRONMENT_VARIABLE,
        ref=SecretRef("providers/openai/api-key"),
        real_environment={},
        env_file_environment={LLM_API_KEY_ENVIRONMENT_VARIABLE: "sk-file"},
        secret_service=SecretService(_FakeStore()),
    )

    assert source == "env_file"


def test_describe_secret_source_falls_back_to_platform_store() -> None:
    ref = SecretRef("providers/openai/api-key")
    source = describe_secret_source(
        variable_name=LLM_API_KEY_ENVIRONMENT_VARIABLE,
        ref=ref,
        real_environment={},
        env_file_environment=None,
        secret_service=SecretService(_FakeStore({ref: SecretValue("stored")})),
    )

    assert source == "platform_store"


def test_describe_secret_source_reports_missing() -> None:
    source = describe_secret_source(
        variable_name=LLM_API_KEY_ENVIRONMENT_VARIABLE,
        ref=SecretRef("providers/openai/api-key"),
        real_environment={},
        env_file_environment=None,
        secret_service=SecretService(_FakeStore()),
    )

    assert source == "missing"
