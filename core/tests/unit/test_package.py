"""Foundation tests for the installed package."""

import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import sofias_assistant
from sofias_assistant.__main__ import main

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
DISTRIBUTION_NAME = "sofias-assistant"


def declared_project_version() -> str:
    """Return the project version declared in pyproject.toml."""
    with PYPROJECT_PATH.open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]

    return str(project["version"])


def test_package_is_importable() -> None:
    assert sofias_assistant.__name__ == "sofias_assistant"


def test_installed_distribution_metadata_matches_declared_version() -> None:
    distribution = metadata.distribution(DISTRIBUTION_NAME)

    assert distribution.metadata["Name"] == DISTRIBUTION_NAME
    assert distribution.version == declared_project_version()


def test_main_prints_installed_identity_and_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    installed_version = metadata.version(DISTRIBUTION_NAME)

    assert main() == 0

    captured = capsys.readouterr()
    assert "Sofia's Assistant" in captured.out
    assert installed_version in captured.out
