"""Deterministic offscreen checks for the Gate I17 Human Configuration Dashboard."""

from __future__ import annotations

import os
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from sofias_assistant.client_app.dashboard import (
    AIModelsTab,
    HomeTab,
    MemoryIntegrationsTab,
)


@pytest.fixture(scope="session")
def qapplication() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


def _bundle(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "providers": [
            {
                "id": "openai",
                "display_name": "OpenAI",
                "adapter_type": "openai",
                "base_url": "https://api.openai.com/v1",
                "enabled": True,
                "execution_location": "cloud",
                "credential": {
                    "ref": "providers/openai/api-key",
                    "configured": True,
                    "effective_source": "platform_store",
                    "shadowed": False,
                },
            }
        ],
        "models": [
            {
                "provider_id": "openai",
                "model_id": "gpt-x",
                "display_name": "gpt-x",
                "execution_location": "cloud",
                "availability": "available",
                "enabled": True,
                "capabilities": [
                    {"capability": "text_generation", "provenance": "builtin_metadata"}
                ],
            }
        ],
        "profiles": [
            {
                "key": "coding",
                "display_name": "coding",
                "required_capabilities": ["text_generation", "tool_calling"],
                "preferred_capabilities": [],
                "locality": "cloud_allowed",
                "enabled": True,
                "fallback_policy": "ordered_then_canonical",
                "bindings": [
                    {
                        "provider_id": "openai",
                        "model_id": "gpt-x",
                        "priority": 1,
                        "enabled": True,
                        "source": "user",
                    },
                    {
                        "provider_id": "openai",
                        "model_id": "gpt-y",
                        "priority": 2,
                        "enabled": True,
                        "source": "user",
                    },
                ],
            }
        ],
        "memory": {
            "enabled": True,
            "base_url": "https://memory.invalid",
            "credential": {
                "credential_ref": "integrations/sofias-memory/api-key",
                "configured": True,
                "effective_source": "platform_store",
                "writable_source": "platform_store",
                "shadowed": False,
            },
            "health": {"status": "healthy", "detail": None},
        },
    }
    base.update(overrides)
    return base


# -- HomeTab --------------------------------------------------------------


def test_home_tab_shows_ready_when_connected_and_configured(
    qapplication: QApplication,
) -> None:
    home = HomeTab()
    home.update_connection("CONNECTED")
    home.update_ai_dashboard(_bundle())

    assert home._headline.text() == "Sofia ready"


def test_home_tab_flags_missing_provider_credential(
    qapplication: QApplication,
) -> None:
    home = HomeTab()
    home.update_connection("CONNECTED")
    bundle = _bundle()
    bundle["providers"][0]["credential"]["configured"] = False  # type: ignore[index]
    home.update_ai_dashboard(bundle)

    assert home._headline.text() == "AI needs configuration"


def test_home_tab_flags_degraded_memory(qapplication: QApplication) -> None:
    home = HomeTab()
    home.update_connection("CONNECTED")
    bundle = _bundle()
    bundle["memory"]["health"] = {"status": "degraded", "detail": "unreachable"}  # type: ignore[index]
    home.update_ai_dashboard(bundle)

    assert home._headline.text() == "Memory degraded"


def test_home_tab_shows_reconnecting_before_configuration_matters(
    qapplication: QApplication,
) -> None:
    home = HomeTab()
    home.update_connection("DISCONNECTED")

    assert home._headline.text() == "Core reconnecting"


# -- AIModelsTab ------------------------------------------------------------


def test_provider_selection_renders_base_url_and_credential_status(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())

    assert tab._provider_base_url.text() == "https://api.openai.com/v1"
    assert "saved in Sofia" in tab._provider_credential_status.text()
    assert tab._model_list.count() == 1


def test_shadowed_credential_status_is_explained_in_human_terms(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    bundle = _bundle()
    bundle["providers"][0]["credential"]["effective_source"] = "environment"  # type: ignore[index]
    bundle["providers"][0]["credential"]["shadowed"] = True  # type: ignore[index]
    tab.update_ai_dashboard(bundle)

    status = tab._provider_credential_status.text()
    assert "environment" in status
    assert "overridden" in status


def test_saving_provider_credential_emits_value_and_clears_the_field(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())
    received: list[tuple[str, str]] = []
    tab.provider_credential_set_requested.connect(
        lambda provider_id, value: received.append((provider_id, value))
    )

    tab._provider_credential_input.setText("sk-super-secret")
    tab._save_provider_credential()

    assert received == [("openai", "sk-super-secret")]
    assert tab._provider_credential_input.text() == ""


def test_provider_enabled_toggle_emits_a_sparse_patch(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())
    received: list[tuple[str, dict[str, object]]] = []
    tab.provider_update_requested.connect(
        lambda provider_id, patch: received.append((provider_id, patch))
    )

    tab._provider_enabled.setCurrentIndex(1)  # "Disabled"

    assert received == [("openai", {"enabled": False})]


def test_selecting_a_profile_shows_its_current_fallback_policy(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())

    assert tab._fallback_policy.currentData() == "ordered_then_canonical"


def test_changing_fallback_policy_emits_a_sparse_patch(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())
    received: list[tuple[str, dict[str, object]]] = []
    tab.profile_update_requested.connect(
        lambda key, patch: received.append((key, patch))
    )

    tab._fallback_policy.setCurrentIndex(0)

    assert received == [("coding", {"fallback_policy": "ordered_only"})]


def test_binding_reorder_produces_a_single_ordered_payload(
    qapplication: QApplication,
) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())
    received: list[tuple[str, dict[str, object]]] = []
    tab.profile_update_requested.connect(
        lambda key, patch: received.append((key, patch))
    )

    tab._binding_list.setCurrentRow(1)
    tab._move_binding(-1)
    tab._save_bindings()

    assert len(received) == 1
    key, patch = received[0]
    assert key == "coding"
    bindings = cast("list[dict[str, object]]", patch["bindings"])
    assert [b["model_id"] for b in bindings] == ["gpt-y", "gpt-x"]
    assert [b["priority"] for b in bindings] == [1, 2]


def test_routing_preview_render_shows_selected_model() -> None:
    tab = AIModelsTab()
    tab.show_routing_preview(
        {
            "profile": "coding",
            "selected": {"provider_id": "openai", "model_id": "gpt-x"},
            "fallback": False,
            "reason_code": "PROFILE_BINDING_SELECTED",
            "reason": "Highest-priority eligible profile binding selected.",
        }
    )

    assert "openai/gpt-x" in tab._preview_result.text()


def test_writes_disabled_when_disconnected(qapplication: QApplication) -> None:
    tab = AIModelsTab()
    tab.update_ai_dashboard(_bundle())

    tab.set_writes_enabled(False)

    assert tab._provider_enabled.isEnabled() is False
    assert tab._provider_credential_input.isEnabled() is False


# -- MemoryIntegrationsTab ---------------------------------------------------


def test_memory_tab_renders_status_from_dashboard_bundle(
    qapplication: QApplication,
) -> None:
    tab = MemoryIntegrationsTab()
    tab.update_ai_dashboard(_bundle())

    assert tab._enabled_label.text() == "Yes"
    assert tab._health_label.text() == "healthy"
    assert "saved in Sofia" in tab._credential_status.text()


def test_memory_credential_save_never_retains_the_value_in_the_widget(
    qapplication: QApplication,
) -> None:
    tab = MemoryIntegrationsTab()
    received: list[str] = []
    tab.credential_set_requested.connect(received.append)

    tab._credential_input.setText("sk-memory-secret")
    tab._save_credential()

    assert received == ["sk-memory-secret"]
    assert tab._credential_input.text() == ""
