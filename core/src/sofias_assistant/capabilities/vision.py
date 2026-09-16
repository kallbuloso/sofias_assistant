"""Provider-neutral screenshot observation service."""

from __future__ import annotations

from uuid import UUID, uuid4

from sofias_assistant.ai import (
    AIRequestRequirements,
    Capability,
    DataLocality,
    VisionImageInput,
    VisionRequest,
    VisionResponse,
)
from sofias_assistant.ai.routing import RoutingError
from sofias_assistant.ai.routing_policy import Router, RoutingPolicy
from sofias_assistant.ai_config.service import record_routing_decision
from sofias_assistant.execution.artifacts import ArtifactService
from sofias_assistant.execution.audit import AuditService


class VisionCapability:
    """Load an ArtifactRef and invoke only a model declaring IMAGE_INPUT."""

    def __init__(
        self,
        artifacts: ArtifactService,
        router: Router,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.router = router
        self._audit = audit

    async def observe(
        self,
        *,
        artifact_id: UUID,
        prompt: str,
        locality: DataLocality = DataLocality.LOCAL_ONLY,
    ) -> VisionResponse:
        ref, data = await self.artifacts.read(artifact_id)
        requirements = AIRequestRequirements(
            required_capabilities=frozenset({Capability.IMAGE_INPUT}),
            preferred_capabilities=frozenset(),
            locality=locality,
        )
        correlation_id = uuid4()
        try:
            route = self.router.route(requirements)
        except RoutingError:
            if isinstance(self.router, RoutingPolicy) and self._audit is not None:
                decision = self.router.resolve(requirements)
                await record_routing_decision(
                    self._audit,
                    decision,
                    correlation_id=correlation_id,
                    actor="Sofia/root",
                    subject=str(artifact_id),
                    origin="VISION",
                )
            raise
        if isinstance(self.router, RoutingPolicy) and self._audit is not None:
            decision = self.router.resolve(requirements)
            await record_routing_decision(
                self._audit,
                decision,
                correlation_id=correlation_id,
                actor="Sofia/root",
                subject=str(artifact_id),
                origin="VISION",
            )
        provider = route.binding.vision
        if provider is None:
            raise RuntimeError("selected model has no vision provider binding")
        return await provider.generate_vision(
            model=route.descriptor.identity,
            request=VisionRequest(
                request_id=uuid4(),
                prompt=prompt,
                image=VisionImageInput(ref.id, ref.media_type, data),
            ),
        )
