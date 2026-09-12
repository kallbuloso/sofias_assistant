"""Small deterministic, fail-closed policy engine for Gate I4."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sofias_assistant.execution.models import (
    DecisionOutcome,
    PermissionGrant,
    PolicyDecision,
    PolicyRequest,
)


class PolicyEngine:
    """Evaluate explicit grants and Tool risk metadata without side effects."""

    def __init__(
        self, grant_lookup: Callable[[Any], Awaitable[PermissionGrant | None]]
    ) -> None:
        self._grant_lookup = grant_lookup

    async def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        if request.requires_elevation:
            return PolicyDecision(
                outcome=DecisionOutcome.REQUIRE_ELEVATION,
                reason="The requested Tool requires elevation",
                request_id=request.correlation_id,
                grant_id=request.grant_id,
            )
        if request.grant_id is not None:
            grant = await self._grant_lookup(request.grant_id)
            if grant is None or not grant.matches(request):
                return PolicyDecision(
                    outcome=DecisionOutcome.DENY,
                    reason="Grant is absent, expired, revoked, consumed, or out of scope",
                    request_id=request.correlation_id,
                    grant_id=request.grant_id,
                )
            return PolicyDecision(
                outcome=DecisionOutcome.ALLOW,
                reason="An explicit grant authorizes the exact requested scope",
                request_id=request.correlation_id,
                grant_id=grant.id,
            )
        if request.requires_confirmation:
            outcome = DecisionOutcome.REQUIRE_CONFIRMATION
            reason = "The requested Tool requires explicit confirmation"
        else:
            outcome = DecisionOutcome.DENY
            reason = "No explicit authority grant authorizes this request"
        return PolicyDecision(
            outcome=outcome,
            reason=reason,
            request_id=request.correlation_id,
        )
