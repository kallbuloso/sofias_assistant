"""Opt-in live tests for Windows Credential Manager."""

import os
from uuid import uuid4

import pytest

from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

pytestmark = pytest.mark.skipif(
    os.name != "nt"
    or os.getenv("SOFIAS_ASSISTANT_RUN_WINDOWS_CREDENTIAL_TESTS") != "1",
    reason="requires explicit Windows Credential Manager test opt-in",
)


def test_live_roundtrip() -> None:
    store = WindowsCredentialStore()
    ref = SecretRef(f"test/{uuid4()}")

    try:
        assert store.get(ref) is None
        store.set(ref, SecretValue("first"))
        first = store.get(ref)
        assert first is not None
        assert first.reveal() == "first"
        store.set(ref, SecretValue("second"))
        second = store.get(ref)
        assert second is not None
        assert second.reveal() == "second"
        assert store.delete(ref) is True
        assert store.get(ref) is None
    finally:
        store.delete(ref)
