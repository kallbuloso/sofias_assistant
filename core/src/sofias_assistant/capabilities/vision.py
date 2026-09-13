"""Provider-neutral screenshot observation service."""

from __future__ import annotations

from uuid import UUID, uuid4

from sofias_assistant.ai import (
    AIRequestRequirements,
    Capability,
    CapabilityRouter,
    DataLocality,
    VisionImageInput,
    VisionRequest,
    VisionResponse,
)
from sofias_assistant.execution.artifacts import ArtifactService


class VisionCapability:
    """Load an ArtifactRef and invoke only a model declaring IMAGE_INPUT."""

    def __init__(self, artifacts: ArtifactService, router: CapabilityRouter) -> None:
        self.artifacts = artifacts
        self.router = router

    async def observe(
        self,
        *,
        artifact_id: UUID,
        prompt: str,
        locality: DataLocality = DataLocality.LOCAL_ONLY,
    ) -> VisionResponse:
        ref, data = await self.artifacts.read(artifact_id)
        route = self.router.route(
            AIRequestRequirements(
                required_capabilities=frozenset({Capability.IMAGE_INPUT}),
                preferred_capabilities=frozenset(),
                locality=locality,
            )
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
