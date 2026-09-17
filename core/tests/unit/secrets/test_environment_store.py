"""Unit tests for the environment-backed and layered SecretStore (Gate I14)."""

from sofias_assistant.secrets.environment_store import (
    EnvironmentSecretStore,
    LayeredSecretStore,
)
from sofias_assistant.secrets.models import SecretRef, SecretValue

_LLM_REF = SecretRef("providers/openai/api-key")
_MEMORY_REF = SecretRef("integrations/sofias-memory/api-key")
_MAPPINGS = {"LLM_API_KEY": _LLM_REF, "SOFIAS_MEMORY_API_KEY": _MEMORY_REF}


class FakeSecretStore:
    def __init__(self) -> None:
        self.values: dict[SecretRef, SecretValue] = {}
        self.set_calls: list[SecretRef] = []
        self.delete_calls: list[SecretRef] = []

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self.values.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self.set_calls.append(ref)
        self.values[ref] = value

    def delete(self, ref: SecretRef) -> bool:
        self.delete_calls.append(ref)
        return self.values.pop(ref, None) is not None


def test_known_mapped_variable_is_bridged() -> None:
    store = EnvironmentSecretStore({"LLM_API_KEY": "sk-test"}, _MAPPINGS)

    value = store.get(_LLM_REF)

    assert value is not None
    assert value.reveal() == "sk-test"


def test_unmapped_ref_is_never_present() -> None:
    store = EnvironmentSecretStore({"LLM_API_KEY": "sk-test"}, _MAPPINGS)

    assert store.get(SecretRef("providers/other/api-key")) is None


def test_blank_environment_value_is_treated_as_absent() -> None:
    store = EnvironmentSecretStore({"LLM_API_KEY": ""}, _MAPPINGS)

    assert store.get(_LLM_REF) is None


def test_arbitrary_environment_variables_are_never_enumerated() -> None:
    store = EnvironmentSecretStore(
        {"LLM_API_KEY": "sk-test", "SOME_OTHER_SECRET": "leaked?"}, _MAPPINGS
    )

    # Only explicitly mapped keys are ever bridged; there is no API to reach
    # anything else even accidentally.
    assert store.get(SecretRef("SOME_OTHER_SECRET")) is None


def test_environment_secret_store_rejects_writes() -> None:
    store = EnvironmentSecretStore({}, _MAPPINGS)

    try:
        store.set(_LLM_REF, SecretValue("nope"))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass

    try:
        store.delete(_LLM_REF)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_layered_store_prefers_environment_over_platform_store() -> None:
    fallback = FakeSecretStore()
    fallback.values[_LLM_REF] = SecretValue("from-platform-store")
    environment_store = EnvironmentSecretStore(
        {"LLM_API_KEY": "from-environment"}, _MAPPINGS
    )
    layered = LayeredSecretStore(environment_store, fallback)

    value = layered.get(_LLM_REF)
    assert value is not None
    assert value.reveal() == "from-environment"


def test_layered_store_falls_through_to_platform_store_when_missing() -> None:
    fallback = FakeSecretStore()
    fallback.values[_MEMORY_REF] = SecretValue("from-platform-store")
    environment_store = EnvironmentSecretStore({}, _MAPPINGS)
    layered = LayeredSecretStore(environment_store, fallback)

    value = layered.get(_MEMORY_REF)

    assert value is not None
    assert value.reveal() == "from-platform-store"


def test_layered_store_returns_none_when_absent_everywhere() -> None:
    layered = LayeredSecretStore(
        EnvironmentSecretStore({}, _MAPPINGS), FakeSecretStore()
    )

    assert layered.get(_LLM_REF) is None


def test_layered_store_writes_target_the_platform_store() -> None:
    fallback = FakeSecretStore()
    layered = LayeredSecretStore(EnvironmentSecretStore({}, _MAPPINGS), fallback)

    layered.set(_LLM_REF, SecretValue("durable-value"))
    assert fallback.set_calls == [_LLM_REF]

    assert layered.delete(_LLM_REF) is True
    assert fallback.delete_calls == [_LLM_REF]


def test_layered_store_describe_reports_environment_when_present() -> None:
    fallback = FakeSecretStore()
    fallback.values[_LLM_REF] = SecretValue("from-platform-store")
    environment_store = EnvironmentSecretStore(
        {"LLM_API_KEY": "from-environment"}, _MAPPINGS
    )
    layered = LayeredSecretStore(environment_store, fallback)

    assert layered.describe(_LLM_REF) == "environment"


def test_layered_store_describe_reports_platform_store_when_only_durable() -> None:
    fallback = FakeSecretStore()
    fallback.values[_MEMORY_REF] = SecretValue("from-platform-store")
    layered = LayeredSecretStore(EnvironmentSecretStore({}, _MAPPINGS), fallback)

    assert layered.describe(_MEMORY_REF) == "platform_store"


def test_layered_store_describe_reports_missing() -> None:
    layered = LayeredSecretStore(
        EnvironmentSecretStore({}, _MAPPINGS), FakeSecretStore()
    )

    assert layered.describe(_LLM_REF) == "missing"


def test_secret_value_repr_never_leaks() -> None:
    store = EnvironmentSecretStore({"LLM_API_KEY": "sk-super-secret"}, _MAPPINGS)

    value = store.get(_LLM_REF)

    assert value is not None
    assert "sk-super-secret" not in repr(value)
    assert "sk-super-secret" not in str(value)
