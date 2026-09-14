"""Unit tests for the local Secret CLI (`sofias_assistant.secrets.__main__`).

Uses an in-memory fake store; never touches the real Windows Credential
Manager, matching the pattern already used by `tests/unit/secrets/test_service.py`.
"""

from __future__ import annotations

import pytest

from sofias_assistant.secrets.__main__ import main
from sofias_assistant.secrets.models import SecretRef, SecretValue

_REF = "integrations/sofias-memory/api-key"


class InMemorySecretStore:
    """Test-only fake store; it is not a secure backend."""

    def __init__(self) -> None:
        self.values: dict[SecretRef, SecretValue] = {}

    def get(self, ref: SecretRef) -> SecretValue | None:
        return self.values.get(ref)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        self.values[ref] = value

    def delete(self, ref: SecretRef) -> bool:
        return self.values.pop(ref, None) is not None


def _prompt(value: str):
    def _fake_prompt(_label: str) -> str:
        return value

    return _fake_prompt


def test_set_stores_the_prompted_value_without_it_appearing_in_argv() -> None:
    store = InMemorySecretStore()

    exit_code = main(
        ["set", _REF],
        store_factory=lambda: store,
        prompt=_prompt("s3cr3t-value"),
    )

    assert exit_code == 0
    stored = store.get(SecretRef(_REF))
    assert stored is not None
    assert stored.reveal() == "s3cr3t-value"


def test_set_with_empty_prompted_value_aborts_without_storing() -> None:
    store = InMemorySecretStore()

    exit_code = main(["set", _REF], store_factory=lambda: store, prompt=_prompt(""))

    assert exit_code == 1
    assert store.get(SecretRef(_REF)) is None


def test_exists_reports_presence_without_revealing_capfd(capfd) -> None:
    store = InMemorySecretStore()
    store.set(SecretRef(_REF), SecretValue("s3cr3t-value"))

    exit_code = main(["exists", _REF], store_factory=lambda: store)

    out, _ = capfd.readouterr()
    assert exit_code == 0
    assert out.strip() == "yes"
    assert "s3cr3t-value" not in out


def test_exists_reports_absence() -> None:
    store = InMemorySecretStore()

    exit_code = main(["exists", _REF], store_factory=lambda: store)

    assert exit_code == 1


def test_delete_removes_a_stored_secret() -> None:
    store = InMemorySecretStore()
    store.set(SecretRef(_REF), SecretValue("s3cr3t-value"))

    exit_code = main(["delete", _REF], store_factory=lambda: store)

    assert exit_code == 0
    assert store.get(SecretRef(_REF)) is None


def test_delete_missing_secret_reports_not_found() -> None:
    store = InMemorySecretStore()

    exit_code = main(["delete", _REF], store_factory=lambda: store)

    assert exit_code == 1


@pytest.mark.parametrize("forbidden_command", ["show", "get", "reveal"])
def test_cli_exposes_no_command_that_reveals_a_secret(forbidden_command: str) -> None:
    with pytest.raises(SystemExit):
        main([forbidden_command, _REF])
