"""Unit tests for the known Contract v1 secret bridge mappings (Gate I14)."""

from sofias_assistant.host.secret_bridge import (
    LLM_API_KEY_ENVIRONMENT_VARIABLE,
    SOFIAS_MEMORY_API_KEY_ENVIRONMENT_VARIABLE,
    SOFIAS_MEMORY_API_KEY_REF,
    bootstrap_secret_mappings,
    credential_write_status,
    describe_secret_source,
    provider_api_key_ref,
)
from sofias_assistant.secrets.environment_store import (
    EnvironmentSecretStore,
    LayeredSecretStore,
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


def test_credential_write_status_reports_fresh_platform_write() -> None:
    ref = SecretRef("providers/openai/api-key")
    service = SecretService(_FakeStore({ref: SecretValue("stored")}))

    source, configured, shadowed = credential_write_status(ref, service)

    assert (source, configured, shadowed) == ("platform_store", True, False)


def test_credential_write_status_reports_shadowing_by_environment() -> None:
    ref = SecretRef("providers/openai/api-key")
    fallback = _FakeStore({ref: SecretValue("stored")})
    environment = EnvironmentSecretStore(
        {"LLM_API_KEY": "sk-real"}, {"LLM_API_KEY": ref}
    )
    service = SecretService(LayeredSecretStore(environment, fallback))

    source, configured, shadowed = credential_write_status(ref, service)

    assert (source, configured, shadowed) == ("environment", True, True)


def test_credential_write_status_reports_missing_after_delete() -> None:
    ref = SecretRef("providers/openai/api-key")
    service = SecretService(_FakeStore())

    source, configured, shadowed = credential_write_status(ref, service)

    assert (source, configured, shadowed) == ("missing", False, False)
