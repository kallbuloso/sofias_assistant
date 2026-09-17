"""Gate I17 Human Configuration Dashboard: Home, AI & Models, Memory pages.

Every widget here is presentation + user-intent only. It renders whatever
`ClientWorker.ai_dashboard_ready`/`routing_preview_ready` last published and
emits `DesktopController.request_*` signals for writes; it never talks to
`CoreApiClient` directly, never decides routing, and never persists
provider/model/profile/secret state locally (Desktop/Core Interaction
Contract v1 SS20/SS43-SS44). QSettings is not touched here: nothing on this
page is a Desktop-local preference.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

_LOCALITY_LABELS = {
    "local_only": "Local only",
    "cloud_allowed": "Allow cloud",
    "cloud_preferred": "Prefer cloud",
}

_FALLBACK_POLICY_LABELS = {
    "ordered_only": "Ordered bindings only",
    "ordered_then_canonical": "Ordered bindings, then canonical fallback",
}


def _credential_line(credential: dict[str, Any]) -> str:
    configured = bool(credential.get("configured"))
    source = str(credential.get("effective_source", "missing"))
    if not configured:
        return "Not configured"
    label = {
        "environment": "Configured — source: environment/deployment",
        "platform_store": "Configured — source: saved in Sofia",
        "missing": "Not configured",
    }.get(source, f"Configured — source: {source}")
    if credential.get("shadowed"):
        label += " (a saved credential exists but is currently overridden)"
    return label


class HomeTab(QWidget):
    """Human readiness summary: Sofia ready / needs configuration / degraded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._headline = QLabel("Checking Sofia's status…")
        self._headline.setAccessibleName("Sofia readiness")
        font = self._headline.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self._headline.setFont(font)
        layout.addWidget(self._headline)
        self._details = QListWidget()
        self._details.setAccessibleName("Readiness details")
        layout.addWidget(self._details, 1)
        self._connection_state = "DISCONNECTED"
        self._bundle: dict[str, Any] | None = None

    def update_connection(self, state: str) -> None:
        self._connection_state = state
        self._render()

    def update_ai_dashboard(self, bundle: dict[str, Any]) -> None:
        self._bundle = bundle
        self._render()

    def _render(self) -> None:
        details: list[str] = []
        headline = "Sofia ready"
        state = self._connection_state.rsplit(".", 1)[-1]
        if state in {"DISCONNECTED", "CONNECTING"}:
            headline = "Core reconnecting"
            details.append("Core connection: " + state.title())
        elif state == "DEGRADED":
            headline = "Sofia is degraded"
            details.append("Core connection: Degraded")
        else:
            details.append("Core connection: Connected")

        bundle = self._bundle
        if bundle is not None:
            providers = bundle.get("providers", [])
            missing_credential = [
                provider
                for provider in providers
                if provider.get("enabled")
                and not provider.get("credential", {}).get("configured")
            ]
            if missing_credential and headline == "Sofia ready":
                headline = "AI needs configuration"
            for provider in missing_credential:
                details.append(
                    f"AI provider '{provider.get('display_name')}' has no credential"
                )
            memory = bundle.get("memory")
            if memory is not None and memory.get("enabled"):
                health = memory.get("health", {})
                status = str(health.get("status", "unknown")).lower()
                if status not in {"healthy"} and headline == "Sofia ready":
                    headline = "Memory degraded"
                details.append(
                    f"Memory: {status}"
                    + (f" — {health.get('detail')}" if health.get("detail") else "")
                )
        else:
            details.append("AI configuration: loading…")

        self._headline.setText(headline)
        self._details.clear()
        for line in details:
            QListWidgetItem(line, self._details)


class AIModelsTab(QWidget):
    """Provider / model catalog / inference profile & binding editor."""

    provider_update_requested = Signal(str, object)
    provider_credential_set_requested = Signal(str, str)
    provider_credential_deleted_requested = Signal(str)
    model_refresh_requested = Signal(str)
    profile_update_requested = Signal(str, object)
    routing_preview_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bundle: dict[str, Any] | None = None
        self._selected_provider_id: str | None = None
        self._selected_profile_key: str | None = None
        self._pending_bindings: list[dict[str, Any]] = []

        outer = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Providers"))
        self._provider_list = QListWidget()
        self._provider_list.currentRowChanged.connect(self._on_provider_selected)
        left_layout.addWidget(self._provider_list)
        left_layout.addWidget(QLabel("Models"))
        self._model_list = QListWidget()
        left_layout.addWidget(self._model_list, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self._provider_panel())
        right_layout.addWidget(self._profile_panel())
        right_layout.addWidget(self._routing_preview_panel())
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

    def _provider_panel(self) -> QWidget:
        box = QGroupBox("Provider configuration")
        form = QFormLayout(box)
        self._provider_enabled = QComboBox()
        self._provider_enabled.addItems(["Enabled", "Disabled"])
        self._provider_enabled.currentIndexChanged.connect(self._save_provider_enabled)
        form.addRow("Status", self._provider_enabled)
        self._provider_base_url = QLineEdit()
        save_url = QPushButton("Save base URL")
        save_url.clicked.connect(self._save_provider_base_url)
        url_row = QHBoxLayout()
        url_row.addWidget(self._provider_base_url, 1)
        url_row.addWidget(save_url)
        form.addRow("Base URL", url_row)
        self._provider_credential_status = QLabel("Not configured")
        form.addRow("Credential", self._provider_credential_status)
        self._provider_credential_input = QLineEdit()
        self._provider_credential_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._provider_credential_input.setPlaceholderText("New API key")
        save_credential = QPushButton("Save credential")
        save_credential.clicked.connect(self._save_provider_credential)
        delete_credential = QPushButton("Remove")
        delete_credential.clicked.connect(self._delete_provider_credential)
        credential_row = QHBoxLayout()
        credential_row.addWidget(self._provider_credential_input, 1)
        credential_row.addWidget(save_credential)
        credential_row.addWidget(delete_credential)
        form.addRow("New credential", credential_row)
        refresh_models = QPushButton("Refresh models from provider")
        refresh_models.clicked.connect(self._refresh_models)
        form.addRow(refresh_models)
        self._provider_widgets = [
            self._provider_enabled,
            self._provider_base_url,
            save_url,
            self._provider_credential_input,
            save_credential,
            delete_credential,
            refresh_models,
        ]
        return box

    def _profile_panel(self) -> QWidget:
        box = QGroupBox("Inference profile bindings")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Profile"))
        self._profile_selector = QComboBox()
        self._profile_selector.currentTextChanged.connect(self._on_profile_selected)
        row.addWidget(self._profile_selector, 1)
        layout.addLayout(row)
        self._profile_summary = QLabel("")
        self._profile_summary.setWordWrap(True)
        layout.addWidget(self._profile_summary)
        fallback_row = QHBoxLayout()
        fallback_row.addWidget(QLabel("Fallback policy"))
        self._fallback_policy = QComboBox()
        for value, label in _FALLBACK_POLICY_LABELS.items():
            self._fallback_policy.addItem(label, value)
        self._fallback_policy.currentIndexChanged.connect(self._save_fallback_policy)
        fallback_row.addWidget(self._fallback_policy, 1)
        layout.addLayout(fallback_row)
        self._binding_list = QListWidget()
        layout.addWidget(self._binding_list)
        controls = QHBoxLayout()
        up = QPushButton("Move up")
        up.clicked.connect(lambda: self._move_binding(-1))
        down = QPushButton("Move down")
        down.clicked.connect(lambda: self._move_binding(1))
        save = QPushButton("Save order")
        save.clicked.connect(self._save_bindings)
        controls.addWidget(up)
        controls.addWidget(down)
        controls.addWidget(save)
        layout.addLayout(controls)
        self._profile_widgets = [
            self._profile_selector,
            self._fallback_policy,
            up,
            down,
            save,
        ]
        return box

    def _routing_preview_panel(self) -> QWidget:
        box = QGroupBox("Routing preview")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Locality"))
        self._preview_locality = QComboBox()
        for value, label in _LOCALITY_LABELS.items():
            self._preview_locality.addItem(label, value)
        self._preview_locality.setCurrentIndex(1)
        row.addWidget(self._preview_locality)
        preview_button = QPushButton("Preview")
        preview_button.clicked.connect(self._request_preview)
        row.addWidget(preview_button)
        layout.addLayout(row)
        self._preview_result = QLabel("")
        self._preview_result.setWordWrap(True)
        layout.addWidget(self._preview_result)
        self._preview_widgets = [self._preview_locality, preview_button]
        return box

    def set_writes_enabled(self, enabled: bool) -> None:
        for widget in (
            self._provider_widgets + self._profile_widgets + self._preview_widgets
        ):
            widget.setEnabled(enabled)

    def update_ai_dashboard(self, bundle: dict[str, Any]) -> None:
        self._bundle = bundle
        providers = bundle.get("providers", [])
        previous_provider = self._selected_provider_id
        self._provider_list.blockSignals(True)
        self._provider_list.clear()
        for provider in providers:
            configured = provider.get("credential", {}).get("configured")
            label = (
                f"{provider.get('display_name')} "
                f"({'enabled' if provider.get('enabled') else 'disabled'}, "
                f"{'credential set' if configured else 'no credential'})"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, provider.get("id"))
            self._provider_list.addItem(item)
        self._provider_list.blockSignals(False)
        restored = self._select_by_data(self._provider_list, previous_provider)
        if not restored and providers:
            self._provider_list.setCurrentRow(0)
        elif not providers:
            self._selected_provider_id = None
            self._render_provider(None)

        previous_profile = self._selected_profile_key
        self._profile_selector.blockSignals(True)
        self._profile_selector.clear()
        for profile in bundle.get("profiles", []):
            self._profile_selector.addItem(str(profile.get("key")))
        self._profile_selector.blockSignals(False)
        if previous_profile is not None:
            index = self._profile_selector.findText(previous_profile)
            if index >= 0:
                self._profile_selector.setCurrentIndex(index)
                self._on_profile_selected(previous_profile)
        elif self._profile_selector.count():
            self._profile_selector.setCurrentIndex(0)
            self._on_profile_selected(self._profile_selector.currentText())

    @staticmethod
    def _select_by_data(widget: QListWidget, value: str | None) -> bool:
        if value is None:
            return False
        for row in range(widget.count()):
            if widget.item(row).data(Qt.ItemDataRole.UserRole) == value:
                widget.setCurrentRow(row)
                return True
        return False

    def _on_provider_selected(self, row: int) -> None:
        if row < 0:
            self._selected_provider_id = None
            self._render_provider(None)
            return
        provider_id = self._provider_list.item(row).data(Qt.ItemDataRole.UserRole)
        self._selected_provider_id = provider_id
        self._render_provider(provider_id)

    def _render_provider(self, provider_id: str | None) -> None:
        provider = self._find_provider(provider_id)
        self._model_list.clear()
        if provider is None:
            self._provider_credential_status.setText("Not configured")
            return
        self._provider_enabled.blockSignals(True)
        self._provider_enabled.setCurrentIndex(0 if provider.get("enabled") else 1)
        self._provider_enabled.blockSignals(False)
        self._provider_base_url.setText(str(provider.get("base_url", "")))
        self._provider_credential_status.setText(
            _credential_line(provider.get("credential", {}))
        )
        bundle = self._bundle or {}
        for model in bundle.get("models", []):
            if model.get("provider_id") != provider_id:
                continue
            capabilities = ", ".join(
                f"{c['capability']}[{c['provenance']}]"
                for c in model.get("capabilities", [])
            )
            QListWidgetItem(
                f"{model.get('display_name')} — {model.get('availability')} "
                f"({'enabled' if model.get('enabled') else 'disabled'}) {capabilities}",
                self._model_list,
            )

    def _find_provider(self, provider_id: str | None) -> dict[str, Any] | None:
        if self._bundle is None or provider_id is None:
            return None
        for provider in self._bundle.get("providers", []):
            if provider.get("id") == provider_id:
                return provider
        return None

    def _save_provider_enabled(self, index: int) -> None:
        if self._selected_provider_id is None:
            return
        self.provider_update_requested.emit(
            self._selected_provider_id, {"enabled": index == 0}
        )

    def _save_provider_base_url(self) -> None:
        if self._selected_provider_id is None:
            return
        value = self._provider_base_url.text().strip()
        if not value:
            return
        self.provider_update_requested.emit(
            self._selected_provider_id, {"base_url": value}
        )

    def _save_provider_credential(self) -> None:
        if self._selected_provider_id is None:
            return
        value = self._provider_credential_input.text()
        if not value.strip():
            return
        self.provider_credential_set_requested.emit(self._selected_provider_id, value)
        self._provider_credential_input.clear()

    def _delete_provider_credential(self) -> None:
        if self._selected_provider_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove credential",
            "Remove the saved credential for this provider?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.provider_credential_deleted_requested.emit(self._selected_provider_id)

    def _refresh_models(self) -> None:
        if self._selected_provider_id is None:
            return
        self.model_refresh_requested.emit(self._selected_provider_id)

    def _on_profile_selected(self, key: str) -> None:
        self._selected_profile_key = key or None
        profile = self._find_profile(key)
        self._binding_list.clear()
        self._pending_bindings = []
        if profile is None:
            self._profile_summary.setText("")
            return
        required = ", ".join(profile.get("required_capabilities", []))
        locality = _LOCALITY_LABELS.get(
            profile.get("locality", ""), profile.get("locality")
        )
        self._profile_summary.setText(
            f"Required: {required or '—'} · Locality: {locality}"
        )
        self._fallback_policy.blockSignals(True)
        index = self._fallback_policy.findData(profile.get("fallback_policy"))
        self._fallback_policy.setCurrentIndex(max(index, 0))
        self._fallback_policy.blockSignals(False)
        self._pending_bindings = [
            dict(binding) for binding in profile.get("bindings", [])
        ]
        self._render_bindings()

    def _save_fallback_policy(self, _index: int) -> None:
        if self._selected_profile_key is None:
            return
        value = self._fallback_policy.currentData()
        if value is None:
            return
        self.profile_update_requested.emit(
            self._selected_profile_key, {"fallback_policy": value}
        )

    def _find_profile(self, key: str) -> dict[str, Any] | None:
        if self._bundle is None:
            return None
        for profile in self._bundle.get("profiles", []):
            if profile.get("key") == key:
                return profile
        return None

    def _render_bindings(self) -> None:
        self._binding_list.clear()
        for binding in self._pending_bindings:
            state = "enabled" if binding.get("enabled") else "disabled"
            QListWidgetItem(
                f"{binding.get('provider_id')}/{binding.get('model_id')} ({state})",
                self._binding_list,
            )

    def _move_binding(self, offset: int) -> None:
        row = self._binding_list.currentRow()
        target = row + offset
        if row < 0 or not (0 <= target < len(self._pending_bindings)):
            return
        self._pending_bindings[row], self._pending_bindings[target] = (
            self._pending_bindings[target],
            self._pending_bindings[row],
        )
        self._render_bindings()
        self._binding_list.setCurrentRow(target)

    def _save_bindings(self) -> None:
        if self._selected_profile_key is None:
            return
        ordered = [
            {
                "provider_id": binding["provider_id"],
                "model_id": binding["model_id"],
                "priority": index + 1,
                "enabled": binding.get("enabled", True),
            }
            for index, binding in enumerate(self._pending_bindings)
        ]
        self.profile_update_requested.emit(
            self._selected_profile_key, {"bindings": ordered}
        )

    def _request_preview(self) -> None:
        if self._selected_profile_key is None:
            return
        locality = self._preview_locality.currentData()
        self.routing_preview_requested.emit(
            {"profile": self._selected_profile_key, "locality": locality}
        )

    def show_routing_preview(self, result: dict[str, Any]) -> None:
        selected = result.get("selected")
        if selected is None:
            self._preview_result.setText(f"No eligible model — {result.get('reason')}")
            return
        fallback = " (fallback)" if result.get("fallback") else ""
        self._preview_result.setText(
            f"{selected.get('provider_id')}/{selected.get('model_id')}{fallback} — "
            f"{result.get('reason')}"
        )


class MemoryIntegrationsTab(QWidget):
    """Sofias Memory integration status and credential lifecycle."""

    credential_set_requested = Signal(str)
    credential_deleted_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._enabled_label = QLabel("Unknown")
        form.addRow("Enabled", self._enabled_label)
        self._base_url_label = QLabel("")
        self._base_url_label.setWordWrap(True)
        form.addRow("Base URL", self._base_url_label)
        self._health_label = QLabel("Unknown")
        form.addRow("Health", self._health_label)
        self._credential_status = QLabel("Not configured")
        form.addRow("Credential", self._credential_status)
        layout.addLayout(form)

        self._credential_input = QLineEdit()
        self._credential_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._credential_input.setPlaceholderText("New Sofias Memory API key")
        save = QPushButton("Save credential")
        save.clicked.connect(self._save_credential)
        delete = QPushButton("Remove")
        delete.clicked.connect(self._delete_credential)
        row = QHBoxLayout()
        row.addWidget(self._credential_input, 1)
        row.addWidget(save)
        row.addWidget(delete)
        layout.addLayout(row)
        layout.addStretch(1)
        self._writable_widgets = [self._credential_input, save, delete]

    def set_writes_enabled(self, enabled: bool) -> None:
        for widget in self._writable_widgets:
            widget.setEnabled(enabled)

    def update_ai_dashboard(self, bundle: dict[str, Any]) -> None:
        memory = bundle.get("memory")
        if memory is None:
            return
        self._enabled_label.setText("Yes" if memory.get("enabled") else "No")
        self._base_url_label.setText(memory.get("base_url") or "Not configured")
        health = memory.get("health", {})
        detail = f" — {health.get('detail')}" if health.get("detail") else ""
        self._health_label.setText(f"{health.get('status', 'unknown')}{detail}")
        self._credential_status.setText(_credential_line(memory.get("credential", {})))

    def _save_credential(self) -> None:
        value = self._credential_input.text()
        if not value.strip():
            return
        self.credential_set_requested.emit(value)
        self._credential_input.clear()

    def _delete_credential(self) -> None:
        answer = QMessageBox.question(
            self,
            "Remove credential",
            "Remove the saved Sofias Memory credential?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.credential_deleted_requested.emit()
