"""Small deterministic Cognitive Memory eligibility policy.

This is not a second `PolicyEngine`: it answers exactly one question — is
this MemoryCandidate eligible for cognitive persistence? — and never decides
generic Tool/authority questions. Gate I6's baseline is intentionally narrow:
only an explicit, authenticated user assertion is ever approved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from sofias_assistant.memory.models import MemoryOriginKind, MemoryType

_VALID_SCOPE_PATTERN = re.compile(r"^(global|project:[a-z0-9](?:[a-z0-9._-]{0,127}))$")


class MemoryPolicyDecision(StrEnum):
    """Outcome of one Memory Policy evaluation."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class MemoryPolicyResult:
    """Deterministic Memory Policy outcome with a human-readable reason."""

    decision: MemoryPolicyDecision
    reason: str

    @property
    def approved(self) -> bool:
        return self.decision is MemoryPolicyDecision.APPROVE


class MemoryPolicy:
    """Evaluate whether one candidate may be persisted to Cognitive Memory."""

    def evaluate(
        self,
        *,
        memory_type: MemoryType,
        scope: str,
        origin_kind: MemoryOriginKind,
        explicit_user_intent: bool,
    ) -> MemoryPolicyResult:
        if not isinstance(memory_type, MemoryType):
            return MemoryPolicyResult(
                MemoryPolicyDecision.REJECT, "unsupported memory type"
            )
        if not isinstance(scope, str) or not _VALID_SCOPE_PATTERN.match(scope):
            return MemoryPolicyResult(MemoryPolicyDecision.REJECT, "invalid scope")
        if origin_kind is not MemoryOriginKind.USER_ASSERTED:
            return MemoryPolicyResult(
                MemoryPolicyDecision.REJECT,
                "only explicit user-asserted candidates may be approved in Gate I6",
            )
        if not explicit_user_intent:
            return MemoryPolicyResult(
                MemoryPolicyDecision.REJECT,
                "user-asserted candidates require explicit user intent",
            )
        return MemoryPolicyResult(
            MemoryPolicyDecision.APPROVE, "eligible for cognitive persistence"
        )
