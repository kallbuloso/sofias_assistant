"""Native Desktop application services for SAS-03C.

These services expose the existing Core-owned capabilities to the PySide
Desktop without routing ordinary Desktop work through localhost HTTP. They
preserve the same bounded, safe projections used by the former client
boundary while keeping policy, persistence, secrets, routing and task
authority inside their existing Core services.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sofias_assistant.ai.contracts import (
    AIRequestRequirements,
    Capability,
    DataLocality,
    ModelIdentity,
)
from sofias_assistant.ai.routing_policy import FallbackPolicy
from sofias_assistant.ai_config.service import (
    AIConfigurationError,
    ProfileBindingInput,
    ProfileNotFoundError,
    ProfilePatch,
    ProviderNotFoundError,
    ProviderPatch,
    SnapshotPublicationError,
)
from sofias_assistant.core.core import SofiaCore
from sofias_assistant.execution.models import GrantLifetime
from sofias_assistant.host.secret_bridge import (
    SOFIAS_MEMORY_API_KEY_REF,
    credential_write_status,
)
from sofias_assistant.secrets.models import SecretValue


class ApplicationValidationError(RuntimeError):
    """Safe application-layer validation failure suitable for Desktop display."""


class DesktopServices:
    """Direct application-facing services used by the Desktop worker."""

    def __init__(self, core: SofiaCore, *, session_id: UUID) -> None:
        self._core = core
        self._session_id = session_id

    @property
    def session_id(self) -> UUID:
        return self._session_id

    @property
    def subject(self) -> str:
        return f"client:{self._session_id}"

    async def sync(self) -> dict[str, Any]:
        health = self._core.health
        notifications = await self._core.proactivity.notifications.pending(
            limit=100, offset=0
        )
        tasks = await self._core.task_runtime.list_tasks(self.subject, limit=50)
        return {
            "core": {
                "state": self._core.state.value,
                "runtime_session_id": (
                    str(self._core.runtime_session_id)
                    if self._core.runtime_session_id is not None
                    else None
                ),
                "health": {
                    "status": health.status.value,
                    "components": [
                        {
                            "name": item.name,
                            "status": item.status.value,
                            "detail": item.detail,
                        }
                        for item in health.components
                    ],
                },
            },
            "notifications": [_notification_dict(item) for item in notifications],
            "tasks": [self._task_dict(task) for task in tasks],
        }

    async def list_conversations(
        self, *, limit: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        history = self._history()
        try:
            page = await history.list_conversations(limit=limit, cursor=cursor)
        except Exception as error:
            raise ApplicationValidationError(str(error)) from error
        return {
            "items": [
                {
                    "conversation_id": str(item.conversation_id),
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                    "preview": item.preview,
                    "last_turn_status": item.last_turn_status,
                    "last_turn_sequence": item.last_turn_sequence,
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
        }

    async def list_conversation_turns(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
        before_sequence: int | None = None,
    ) -> dict[str, Any]:
        history = self._history()
        try:
            page = await history.list_turns(
                conversation_id,
                limit=limit,
                before_sequence=before_sequence,
            )
        except Exception as error:
            raise ApplicationValidationError(str(error)) from error
        return {
            "turns": [_turn_dict(turn) for turn in page.turns],
            "has_older": page.has_older,
        }

    async def acknowledge(self, notification_id: UUID) -> bool:
        notifications = self._core.proactivity.notifications
        if await notifications.get(notification_id) is None:
            raise ApplicationValidationError("Notification not found")
        return await notifications.acknowledge(notification_id)

    async def get_confirmation(self, confirmation_id: UUID) -> dict[str, Any]:
        confirmation = await self._core.execution_runtime.store.get_confirmation(
            confirmation_id
        )
        if confirmation is None or confirmation.subject != self.subject:
            raise ApplicationValidationError("Confirmation not found")
        return {
            "id": str(confirmation.id),
            "subject": confirmation.subject,
            "capability": confirmation.capability,
            "operation": confirmation.operation,
            "resource": confirmation.resource,
            "requested_lifetime": confirmation.requested_lifetime.value,
            "status": confirmation.status.value,
            "tool_call_id": str(confirmation.tool_call_id),
        }

    async def approve_confirmation(
        self, confirmation_id: UUID, *, lifetime: str
    ) -> dict[str, Any]:
        confirmation = await self._core.execution_runtime.store.get_confirmation(
            confirmation_id
        )
        if confirmation is None or confirmation.subject != self.subject:
            raise ApplicationValidationError("Confirmation not found")
        try:
            result = await self._core.execution_runtime.approve_confirmation(
                confirmation_id, lifetime=GrantLifetime(lifetime)
            )
        except (KeyError, ValueError) as error:
            raise ApplicationValidationError("Confirmation not found") from error
        return _tool_result_dict(result)

    async def deny_confirmation(self, confirmation_id: UUID) -> None:
        confirmation = await self._core.execution_runtime.store.get_confirmation(
            confirmation_id
        )
        if confirmation is None or confirmation.subject != self.subject:
            raise ApplicationValidationError("Confirmation not found")
        try:
            await self._core.execution_runtime.deny_confirmation(confirmation_id)
        except (KeyError, ValueError) as error:
            raise ApplicationValidationError("Confirmation not found") from error

    async def cancel_task(self, task_id: UUID) -> dict[str, Any]:
        task = await self._core.task_runtime.get_task(task_id)
        if task is None or task.subject != self.subject:
            raise ApplicationValidationError("Task not found")
        try:
            cancelled = await self._core.task_runtime.cancel_task(task_id)
        except KeyError as error:
            raise ApplicationValidationError("Task not found") from error
        return {"id": str(cancelled.id), "status": cancelled.status.value}

    async def list_ai_providers(self) -> list[dict[str, Any]]:
        service = self._ai()
        providers = await service.list_providers()
        return [_provider_dict(provider, service) for provider in providers]

    async def list_ai_models(self) -> list[dict[str, Any]]:
        service = self._ai()
        return [_model_dict(entry) for entry in await service.list_models()]

    async def update_ai_provider(
        self, provider_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        service = self._ai()
        try:
            await service.update_provider(
                provider_id,
                ProviderPatch(
                    display_name=patch.get("display_name"),
                    base_url=patch.get("base_url"),
                    enabled=patch.get("enabled"),
                ),
            )
        except ProviderNotFoundError as error:
            raise ApplicationValidationError("Provider not found") from error
        except (AIConfigurationError, SnapshotPublicationError) as error:
            raise ApplicationValidationError(str(error)) from error
        providers = await service.list_providers()
        updated = next(
            (provider for provider in providers if provider.id == provider_id), None
        )
        if updated is None:
            raise ApplicationValidationError("Provider not found")
        return _provider_dict(updated, service)

    async def refresh_ai_models(self, provider_id: str) -> list[dict[str, Any]]:
        service = self._ai()
        try:
            refreshed = await service.refresh_models(provider_id)
        except AIConfigurationError as error:
            raise ApplicationValidationError(str(error)) from error
        return [_model_dict(entry) for entry in refreshed]

    async def list_ai_profiles(self) -> list[dict[str, Any]]:
        service = self._ai()
        profiles = await service.list_profiles()
        result: list[dict[str, Any]] = []
        for profile in profiles:
            item = await _profile_dict(service, profile.key)
            if item is not None:
                result.append(item)
        return result

    async def get_ai_profile(self, key: str) -> dict[str, Any]:
        service = self._ai()
        result = await _profile_dict(service, key)
        if result is None:
            raise ApplicationValidationError("Profile not found")
        return result

    async def update_ai_profile(
        self, key: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        service = self._ai()
        try:
            profile_patch = ProfilePatch(
                enabled=patch.get("enabled"),
                preferred_capabilities=(
                    frozenset(
                        Capability(value)
                        for value in patch["preferred_capabilities"]
                    )
                    if patch.get("preferred_capabilities") is not None
                    else None
                ),
                locality=(
                    DataLocality(str(patch["locality"]))
                    if patch.get("locality") is not None
                    else None
                ),
                fallback_policy=(
                    FallbackPolicy(str(patch["fallback_policy"]))
                    if patch.get("fallback_policy") is not None
                    else None
                ),
                bindings=(
                    tuple(
                        ProfileBindingInput(
                            provider_id=str(item["provider_id"]),
                            model_id=str(item["model_id"]),
                            priority=int(item["priority"]),
                            enabled=bool(item.get("enabled", True)),
                        )
                        for item in patch["bindings"]
                    )
                    if patch.get("bindings") is not None
                    else None
                ),
            )
            await service.update_profile(key, profile_patch)
        except ProfileNotFoundError as error:
            raise ApplicationValidationError("Profile not found") from error
        except (
            AIConfigurationError,
            SnapshotPublicationError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ApplicationValidationError(str(error)) from error
        result = await _profile_dict(service, key)
        if result is None:
            raise ApplicationValidationError("Profile not found")
        return result

    async def preview_ai_routing(self, request: dict[str, Any]) -> dict[str, Any]:
        service = self._ai()
        try:
            required = frozenset(
                Capability(value) for value in request.get("required_capabilities", [])
            )
            preferred = frozenset(
                Capability(value)
                for value in request.get("preferred_capabilities", [])
            )
            requirements = AIRequestRequirements(
                required_capabilities=required,
                preferred_capabilities=preferred - required,
                locality=DataLocality(
                    str(request.get("locality", DataLocality.CLOUD_ALLOWED.value))
                ),
            )
            override_value = request.get("override")
            override = (
                ModelIdentity(
                    str(override_value["provider_id"]),
                    str(override_value["model_id"]),
                )
                if isinstance(override_value, dict)
                else None
            )
            decision = service.preview_routing(
                str(request["profile"]),
                requirements,
                model_override=override,
            )
        except (KeyError, TypeError, ValueError, AIConfigurationError) as error:
            raise ApplicationValidationError(str(error)) from error
        return {
            "profile": decision.profile_key,
            "selected": (
                {
                    "provider_id": decision.route.descriptor.identity.provider_id,
                    "model_id": decision.route.descriptor.identity.model_id,
                }
                if decision.route is not None
                else None
            ),
            "fallback": decision.fallback,
            "reason_code": decision.reason_code.value,
            "reason": decision.reason,
        }

    async def set_ai_provider_credential(
        self, provider_id: str, value: str
    ) -> dict[str, Any]:
        service = self._ai()
        try:
            status = await service.set_provider_credential(
                provider_id, SecretValue(value)
            )
        except ProviderNotFoundError as error:
            raise ApplicationValidationError("Provider not found") from error
        return _credential_status_dict(status)

    async def delete_ai_provider_credential(
        self, provider_id: str
    ) -> dict[str, Any]:
        service = self._ai()
        try:
            status = await service.delete_provider_credential(provider_id)
        except ProviderNotFoundError as error:
            raise ApplicationValidationError("Provider not found") from error
        return _credential_status_dict(status)

    async def get_memory_integration(self) -> dict[str, Any]:
        source, configured, shadowed = credential_write_status(
            SOFIAS_MEMORY_API_KEY_REF, self._core.secret_service
        )
        health = next(
            (
                item
                for item in self._core.health.components
                if item.name == "sofias-memory"
            ),
            None,
        )
        config = self._core.memory_config
        return {
            "enabled": config.enabled,
            "base_url": config.base_url,
            "credential": {
                "credential_ref": SOFIAS_MEMORY_API_KEY_REF.identifier,
                "configured": configured,
                "effective_source": source,
                "writable_source": "platform_store",
                "shadowed": shadowed,
            },
            "health": {
                "status": health.status.value if health is not None else "unknown",
                "detail": health.detail if health is not None else None,
            },
        }

    async def set_memory_credential(self, value: str) -> dict[str, Any]:
        self._core.secret_service.set(
            SOFIAS_MEMORY_API_KEY_REF, SecretValue(value)
        )
        await self._audit_memory_credential("UPDATED")
        return (await self.get_memory_integration())["credential"]

    async def delete_memory_credential(self) -> dict[str, Any]:
        self._core.secret_service.delete(SOFIAS_MEMORY_API_KEY_REF)
        await self._audit_memory_credential("DELETED")
        return (await self.get_memory_integration())["credential"]

    async def _audit_memory_credential(self, action: str) -> None:
        response = (await self.get_memory_integration())["credential"]
        await self._core.execution_runtime.audit.record(
            event_type=f"INTEGRATION_CREDENTIAL_{action}",
            actor=f"client-session:{self._session_id}",
            subject="sofias-memory",
            action=(
                "integration.credential.update"
                if action == "UPDATED"
                else "integration.credential.delete"
            ),
            resource=f"integration/{SOFIAS_MEMORY_API_KEY_REF.identifier}",
            outcome="SUCCEEDED",
            origin="client",
            correlation_id=uuid4(),
            metadata={
                "configured": bool(response["configured"]),
                "effective_source": str(response["effective_source"]),
            },
        )

    def _history(self):
        service = self._core.conversation_history_service
        if service is None:
            raise RuntimeError("Conversation History Service is not configured")
        return service

    def _ai(self):
        service = self._core.ai_configuration_service
        if service is None:
            raise RuntimeError("AI Configuration Service is not configured")
        return service

    def _task_dict(self, task: Any) -> dict[str, Any]:
        return {
            "id": str(task.id),
            "objective": task.objective,
            "status": task.status.value,
            "result": task.result,
            "error_code": task.error.code if task.error is not None else None,
            "error_message": task.error.message if task.error is not None else None,
            "cancellation_requested": task.cancellation_requested,
            "confirmation_id": (
                str(self._core.task_runtime.pending_confirmation(task.id))
                if self._core.task_runtime.pending_confirmation(task.id) is not None
                else None
            ),
        }


def _notification_dict(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "event_id": str(item.event_id),
        "type": item.type,
        "severity": item.severity,
        "title": item.title,
        "summary": item.summary,
        "source": item.source,
        "created_at": item.created_at.isoformat(),
        "correlation_id": str(item.correlation_id),
        "action_reference": (
            str(item.action_reference) if item.action_reference is not None else None
        ),
        "state": item.state,
    }


def _turn_dict(turn: Any) -> dict[str, Any]:
    return {
        "id": str(turn.id),
        "conversation_id": str(turn.conversation_id),
        "sequence": turn.sequence,
        "status": turn.status.value,
        "input_modality": turn.input_modality.value,
        "cloud_context_eligible": turn.cloud_context_eligible,
        "user_text": turn.user_text,
        "assistant_text": turn.assistant_text,
        "provider_id": turn.provider_id,
        "model_id": turn.model_id,
        "error_category": turn.error_category,
        "error_message": turn.error_message,
        "created_at": turn.created_at.isoformat(),
        "updated_at": turn.updated_at.isoformat(),
        "finished_at": (
            turn.finished_at.isoformat() if turn.finished_at is not None else None
        ),
    }


def _tool_result_dict(result: Any) -> dict[str, Any]:
    return {
        "status": result.status,
        "call_id": str(result.call_id),
        "value": result.value,
        "error_code": result.error.code if result.error is not None else None,
        "error_message": result.error.message if result.error is not None else None,
        "confirmation_id": (
            str(result.confirmation_id)
            if result.confirmation_id is not None
            else None
        ),
        "artifact_refs": [str(ref.id) for ref in result.artifact_refs],
    }


def _provider_dict(provider: Any, service: Any) -> dict[str, Any]:
    return {
        "id": provider.id,
        "display_name": provider.display_name,
        "adapter_type": provider.adapter_type,
        "base_url": provider.base_url,
        "enabled": provider.enabled,
        "execution_location": provider.execution_location.value,
        "credential": {
            "ref": (
                provider.credential_ref.identifier
                if provider.credential_ref is not None
                else None
            ),
            "configured": service.is_credential_configured(provider.credential_ref),
        },
    }


def _model_dict(entry: Any) -> dict[str, Any]:
    return {
        "provider_id": entry.provider_id,
        "model_id": entry.model_id,
        "display_name": entry.display_name,
        "context_window": entry.context_window,
        "execution_location": entry.execution_location.value,
        "availability": entry.availability.value,
        "enabled": entry.enabled,
        "discovery_source": entry.discovery_source.value,
        "capabilities": [
            {
                "capability": claim.capability.value,
                "provenance": claim.provenance.value,
            }
            for claim in entry.capabilities
        ],
        "last_seen_at": (
            entry.last_seen_at.isoformat()
            if entry.last_seen_at is not None
            else None
        ),
    }


async def _profile_dict(service: Any, key: str) -> dict[str, Any] | None:
    profile = await service.get_profile(key)
    if profile is None:
        return None
    bindings = await service.list_bindings(key)
    return {
        "key": profile.key,
        "display_name": profile.display_name,
        "description": profile.description,
        "required_capabilities": sorted(
            capability.value for capability in profile.required_capabilities
        ),
        "preferred_capabilities": sorted(
            capability.value for capability in profile.preferred_capabilities
        ),
        "locality": profile.locality.value,
        "enabled": profile.enabled,
        "fallback_policy": profile.fallback_policy.value,
        "bindings": [
            {
                "provider_id": binding.provider_id,
                "model_id": binding.model_id,
                "priority": binding.priority,
                "enabled": binding.enabled,
                "source": binding.source,
            }
            for binding in sorted(bindings, key=lambda value: value.priority)
        ],
    }


def _credential_status_dict(status: Any) -> dict[str, Any]:
    return {
        "credential_ref": status.credential_ref,
        "configured": status.configured,
        "effective_source": status.effective_source,
        "writable_source": status.writable_source,
        "shadowed": status.shadowed,
    }
