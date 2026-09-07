"""Unit tests for pure runtime bootstrap helpers."""

from pathlib import Path

from sofias_assistant.runtime import operational_database_url


def test_operational_database_url_handles_spaces_and_unicode_paths() -> None:
    database_path = Path("data with spaces") / "Sof\u00eda" / "operational.sqlite"

    database_url = operational_database_url(database_path)

    assert database_url.startswith("sqlite+aiosqlite:///")
    assert database_url.endswith("data with spaces/Sof\u00eda/operational.sqlite")
