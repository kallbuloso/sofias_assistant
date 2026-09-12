"""Vertical authorized Tool execution runtime for Gate I4."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.execution.artifacts import ArtifactService
from sofias_assistant.execution.audit import AuditService
from sofias_assistant.execution.dispatcher import ExecutionDispatcher
from sofias_assistant.execution.models import (
    AuthorityContext,
    ConfirmationRequest,
    ConfirmationStatus,
    DecisionOutcome,
    Delegation,
    GrantLifetime,
    PermissionGrant,
    PolicyDecision,
    PolicyRequest,
    ToolCall,
    ToolError,
    ToolResult,
    ToolSideEffect,
    ToolSpec,
)
from sofias_assistant.execution.policy import PolicyEngine
from sofias_assistant.execution.registry import ToolRegistry
from sofias_assistant.execution.store import ExecutionStore


class ExecutionRuntime:
    """Own registry, Policy, authority, Tool dispatch and artifacts for one Core."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        artifact_root: Path,
    ) -> None:
        self.store = ExecutionStore(session_factory)
        self.audit = AuditService(session_factory)
        self.registry = ToolRegistry()
        self.policy = PolicyEngine(self.store.get_grant)
        self.artifacts = ArtifactService(artifact_root, self.store)
        self.dispatcher = ExecutionDispatcher()
        self._lock = asyncio.Lock()

    def register_tool(self, spec: ToolSpec) -> None:
        self.registry.register(spec)

    def list_tools(self) -> tuple[ToolSpec, ...]:
        return self.registry.list()

    async def create_grant(
        self,
        *,
        subject: str,
        capability: str,
        resource_scope: str,
        lifetime: GrantLifetime,
        session_id: UUID | None = None,
        constraints: Mapping[str, Any] | None = None,
        issuing_context: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> PermissionGrant:
        grant = PermissionGrant(
            subject=subject,
            capability=capability,
            resource_scope=resource_scope,
            lifetime=lifetime,
            session_id=session_id,
            constraints=constraints or {},
            issuing_context=issuing_context or {},
            expires_at=expires_at,
            remaining_uses=1 if lifetime is GrantLifetime.ONE_SHOT else None,
        )
        await self.store.save_grant(grant)
        await self.audit.record(
            event_type="GRANT_CREATED",
            actor=grant.subject,
            subject=grant.subject,
            action="grant.create",
            resource=grant.resource_scope,
            outcome="SUCCEEDED",
            origin="SYSTEM_RUNTIME",
            correlation_id=grant.id,
            grant_id=grant.id,
            authority_context={"capability": grant.capability},
            metadata={"lifetime": grant.lifetime.value},
        )
        return grant

    async def create_delegation(
        self,
        *,
        subject: str,
        objective: str,
        resource_scope: str,
        authority_scope: str,
        constraints: Mapping[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> Delegation:
        delegation = Delegation(
            subject=subject,
            objective=objective,
            resource_scope=resource_scope,
            authority_scope=authority_scope,
            constraints=constraints or {},
            expires_at=expires_at,
        )
        await self.store.save_delegation(delegation)
        await self.audit.record(
            event_type="DELEGATION_CREATED",
            actor=delegation.subject,
            subject=delegation.subject,
            action="delegation.create",
            resource=delegation.resource_scope,
            outcome="SUCCEEDED",
            origin="SYSTEM_RUNTIME",
            correlation_id=delegation.id,
            delegation_id=delegation.id,
            metadata={"authority_scope": delegation.authority_scope},
        )
        return delegation

    async def revoke_grant(self, grant_id: UUID) -> bool:
        revoked = await self.store.revoke_grant(grant_id, datetime.now(UTC))
        if revoked:
            await self.audit.record(
                event_type="GRANT_REVOKED",
                actor="Sofia/root",
                subject="Sofia/root",
                action="grant.revoke",
                resource=str(grant_id),
                outcome="SUCCEEDED",
                origin="SYSTEM_RUNTIME",
                correlation_id=grant_id,
                grant_id=grant_id,
            )
        return revoked

    async def invoke(
        self,
        call: ToolCall,
        *,
        grant_id: UUID | None = None,
    ) -> ToolResult:
        async with self._lock:
            await self.audit.record(
                event_type="TOOL_CALL_REQUESTED",
                actor=call.subject,
                subject=call.subject,
                action=call.name,
                resource=call.name,
                outcome="REQUESTED",
                origin="DIRECT_INVOCATION",
                correlation_id=call.correlation_id,
                causation_id=call.causation_id,
                tool_call_id=call.id,
                metadata={"argument_keys": sorted(call.arguments)},
            )
            existing = await self.store.get_tool_call(call.id)
            if existing is not None:
                _, prior, status = existing
                if prior is not None and status in {"SUCCEEDED", "FAILED", "DENIED"}:
                    return prior
                if status == "WAITING_CONFIRMATION" and grant_id is None:
                    return prior or ToolResult(
                        status="CONFIRMATION_REQUIRED", call_id=call.id
                    )
                if status == "RUNNING":
                    return ToolResult(
                        status="DUPLICATE_IN_FLIGHT",
                        call_id=call.id,
                        error=ToolError(
                            "DUPLICATE_CALL", "ToolCall is already executing"
                        ),
                    )
            try:
                spec = self.registry.resolve(call.name)
            except KeyError:
                result = self._error(
                    call, "UNREGISTERED_TOOL", "Tool is not registered"
                )
                await self.store.save_tool_call(call, status="DENIED", result=result)
                await self._audit_result(call, result, None, call.name, None)
                return result
            if not spec.enabled:
                result = self._error(call, "TOOL_DISABLED", "Tool is disabled")
                await self.store.save_tool_call(call, status="DENIED", result=result)
                await self._audit_result(call, result, None, call.name, None)
                return result
            try:
                arguments = dict(call.arguments)
                if spec.input_validator is not None:
                    arguments = dict(spec.input_validator(arguments))
                resource = spec.resource_resolver(arguments)
                if not resource.strip():
                    raise ValueError("resource resolver returned a blank resource")
            except (TypeError, ValueError, KeyError):
                result = self._error(
                    call, "INVALID_ARGUMENTS", "Tool arguments are invalid"
                )
                await self.store.save_tool_call(call, status="DENIED", result=result)
                await self._audit_result(call, result, None, call.name, None)
                return result
            request = PolicyRequest(
                subject=call.subject,
                capability=spec.capability,
                operation=spec.name,
                resource=resource,
                authority=AuthorityContext(call.subject, call.session_id),
                requires_confirmation=spec.confirmation_required
                or spec.side_effect is ToolSideEffect.MUTATING,
                requires_elevation=spec.elevation_required,
                grant_id=grant_id,
                tool_call_id=call.id,
                correlation_id=call.correlation_id,
            )
            decision = await self.policy.evaluate(request)
            await self.store.save_decision(decision)
            await self.audit.record(
                event_type="POLICY_DECISION",
                actor=call.subject,
                subject=call.subject,
                action=call.name,
                resource=resource,
                outcome=decision.outcome.value,
                origin="DIRECT_INVOCATION",
                correlation_id=call.correlation_id,
                causation_id=call.id,
                tool_call_id=call.id,
                policy_decision_id=decision.id,
                grant_id=decision.grant_id,
                authority_context={"capability": spec.capability},
                metadata={
                    "reason": decision.reason,
                    "policy_version": decision.policy_version,
                },
            )
            if decision.outcome is DecisionOutcome.REQUIRE_CONFIRMATION:
                confirmation = ConfirmationRequest(
                    subject=call.subject,
                    capability=spec.capability,
                    operation=spec.name,
                    resource=resource,
                    tool_call_id=call.id,
                    session_id=call.session_id,
                    requested_lifetime=spec.confirmation_lifetime,
                )
                await self.store.save_confirmation(confirmation)
                result = ToolResult(
                    status="CONFIRMATION_REQUIRED",
                    call_id=call.id,
                    decision=decision,
                    confirmation_id=confirmation.id,
                )
                await self.store.save_tool_call(
                    call,
                    status="WAITING_CONFIRMATION",
                    result=result,
                    decision_id=decision.id,
                    confirmation_id=confirmation.id,
                )
                await self.audit.record(
                    event_type="CONFIRMATION_REQUESTED",
                    actor=call.subject,
                    subject=call.subject,
                    action=call.name,
                    resource=resource,
                    outcome="WAITING_CONFIRMATION",
                    origin="DIRECT_INVOCATION",
                    correlation_id=call.correlation_id,
                    causation_id=decision.id,
                    tool_call_id=call.id,
                    policy_decision_id=decision.id,
                    confirmation_id=confirmation.id,
                )
                return result
            if decision.outcome is not DecisionOutcome.ALLOW:
                result = ToolResult(
                    status=decision.outcome.value,
                    call_id=call.id,
                    error=ToolError("POLICY_DENIED", decision.reason),
                    decision=decision,
                )
                await self.store.save_tool_call(
                    call, status="DENIED", result=result, decision_id=decision.id
                )
                await self._audit_result(call, result, decision, resource, None)
                return result
            if grant_id is not None:
                grant = await self.store.get_grant(grant_id)
                if grant is not None and grant.lifetime is GrantLifetime.ONE_SHOT:
                    if not await self.store.consume_one_shot(grant_id):
                        result = self._error(
                            call, "GRANT_CONSUMED", "Grant was already consumed"
                        )
                        await self.store.save_tool_call(
                            call, status="DENIED", result=result
                        )
                        await self._audit_result(call, result, decision, resource, None)
                        return result
                    await self.audit.record(
                        event_type="GRANT_CONSUMED",
                        actor=call.subject,
                        subject=call.subject,
                        action=call.name,
                        resource=resource,
                        outcome="CONSUMED",
                        origin="DIRECT_INVOCATION",
                        correlation_id=call.correlation_id,
                        causation_id=decision.id,
                        tool_call_id=call.id,
                        policy_decision_id=decision.id,
                        grant_id=grant_id,
                    )
            await self.store.save_tool_call(
                call, status="RUNNING", decision_id=decision.id
            )
            await self.audit.record(
                event_type="TOOL_EXECUTION_STARTED",
                actor=call.subject,
                subject=call.subject,
                action=call.name,
                resource=resource,
                outcome="RUNNING",
                origin="DIRECT_INVOCATION",
                correlation_id=call.correlation_id,
                causation_id=decision.id,
                tool_call_id=call.id,
                policy_decision_id=decision.id,
                grant_id=decision.grant_id,
                execution_context={"mode": spec.execution_mode.value},
            )
            try:
                async with asyncio.timeout(spec.timeout_seconds):
                    dispatched = await self.dispatcher.dispatch(
                        spec, arguments, call_id=call.id
                    )
                if dispatched.status != "SUCCEEDED":
                    result = ToolResult(
                        status="FAILED",
                        call_id=call.id,
                        error=dispatched.error
                        or ToolError("TOOL_FAILED", "Tool execution failed"),
                        decision=decision,
                    )
                elif isinstance(dispatched.value, ToolResult):
                    result = ToolResult(
                        status="SUCCEEDED",
                        call_id=call.id,
                        value=dispatched.value.value,
                        error=dispatched.value.error,
                        decision=decision,
                        artifact_refs=dispatched.value.artifact_refs,
                    )
                else:
                    result = ToolResult(
                        status="SUCCEEDED",
                        call_id=call.id,
                        value=dispatched.value,
                        decision=decision,
                    )
                await self.store.save_tool_call(
                    call, status="SUCCEEDED", result=result, decision_id=decision.id
                )
                await self._audit_result(
                    call, result, decision, resource, spec.execution_mode.value
                )
                return result
            except TimeoutError:
                result = self._error(
                    call, "TIMEOUT", "Tool execution timed out", decision
                )
            except Exception:
                result = self._error(
                    call, "TOOL_FAILED", "Tool execution failed", decision
                )
            await self.store.save_tool_call(
                call, status="FAILED", result=result, decision_id=decision.id
            )
            await self._audit_result(
                call, result, decision, resource, spec.execution_mode.value
            )
            return result

    async def approve_confirmation(
        self, confirmation_id: UUID, *, lifetime: GrantLifetime = GrantLifetime.ONE_SHOT
    ) -> ToolResult:
        confirmation = await self.store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise KeyError("Confirmation not found")
        if confirmation.status is not ConfirmationStatus.PENDING:
            raise ValueError("Confirmation is already resolved")
        if lifetime is not confirmation.requested_lifetime:
            raise ValueError("Approval lifetime exceeds the requested authority scope")
        grant = await self.create_grant(
            subject=confirmation.subject,
            capability=confirmation.capability,
            resource_scope=confirmation.resource,
            lifetime=lifetime,
            session_id=confirmation.session_id,
            constraints=confirmation.constraints,
            issuing_context={"confirmation_id": str(confirmation.id)},
        )
        resolved = await self.store.resolve_confirmation(
            confirmation.id,
            status=ConfirmationStatus.APPROVED,
            resolved_at=datetime.now(UTC),
            grant_id=grant.id,
        )
        if not resolved:
            await self.revoke_grant(grant.id)
            raise ValueError("Confirmation was resolved concurrently")
        await self.audit.record(
            event_type="CONFIRMATION_APPROVED",
            actor=confirmation.subject,
            subject=confirmation.subject,
            action=confirmation.operation,
            resource=confirmation.resource,
            outcome="APPROVED",
            origin="USER_REQUEST",
            correlation_id=confirmation.tool_call_id,
            causation_id=confirmation.id,
            tool_call_id=confirmation.tool_call_id,
            confirmation_id=confirmation.id,
            grant_id=grant.id,
            metadata={"lifetime": lifetime.value},
        )
        stored_call = await self.store.get_tool_call(confirmation.tool_call_id)
        if stored_call is None:
            raise RuntimeError("Confirmation ToolCall is missing")
        return await self.invoke(stored_call[0], grant_id=grant.id)

    async def deny_confirmation(self, confirmation_id: UUID) -> bool:
        confirmation = await self.store.get_confirmation(confirmation_id)
        if confirmation is None:
            raise KeyError("Confirmation not found")
        resolved = await self.store.resolve_confirmation(
            confirmation.id,
            status=ConfirmationStatus.DENIED,
            resolved_at=datetime.now(UTC),
            grant_id=None,
        )
        if resolved:
            await self.audit.record(
                event_type="CONFIRMATION_DENIED",
                actor=confirmation.subject,
                subject=confirmation.subject,
                action=confirmation.operation,
                resource=confirmation.resource,
                outcome="DENIED",
                origin="USER_REQUEST",
                correlation_id=confirmation.tool_call_id,
                causation_id=confirmation.id,
                tool_call_id=confirmation.tool_call_id,
                confirmation_id=confirmation.id,
            )
        return resolved

    def _error(
        self,
        call: ToolCall,
        code: str,
        message: str,
        decision: PolicyDecision | None = None,
    ) -> ToolResult:
        return ToolResult(
            status="FAILED",
            call_id=call.id,
            error=ToolError(code, message),
            decision=decision,
        )

    async def _audit_result(
        self,
        call: ToolCall,
        result: ToolResult,
        decision: PolicyDecision | None,
        resource: str,
        mode: str | None,
    ) -> None:
        await self.audit.record(
            event_type=(
                "TOOL_EXECUTION_COMPLETED"
                if result.status == "SUCCEEDED"
                else "TOOL_CALL_DENIED"
                if decision is None or decision.outcome is not DecisionOutcome.ALLOW
                else "TOOL_EXECUTION_FAILED"
            ),
            actor=call.subject,
            subject=call.subject,
            action=call.name,
            resource=resource,
            outcome=result.status,
            origin="DIRECT_INVOCATION",
            correlation_id=call.correlation_id,
            causation_id=decision.id if decision else call.id,
            tool_call_id=call.id,
            policy_decision_id=decision.id if decision else None,
            execution_context={"mode": mode},
            metadata={
                "error_code": result.error.code if result.error else None,
                "artifact_count": len(result.artifact_refs),
            },
        )
