"""Core-controlled local artifact storage."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sofias_assistant.execution.models import ArtifactRef, ArtifactRetention
from sofias_assistant.execution.store import ExecutionStore


class ArtifactService:
    """Store opaque bytes under a controlled root and expose stable references."""

    def __init__(self, root: Path, store: ExecutionStore) -> None:
        self._root = root.resolve()
        self._store = store

    async def create(
        self,
        content: bytes,
        *,
        kind: str,
        media_type: str,
        retention: ArtifactRetention = ArtifactRetention.TEMPORARY,
    ) -> ArtifactRef:
        if not kind.strip() or not media_type.strip():
            raise ValueError("artifact kind and media_type must not be blank")
        artifact_id = uuid4()
        relative_path = Path(f"{artifact_id.hex}.artifact")
        destination = (self._root / relative_path).resolve()
        if self._root not in destination.parents:
            raise ValueError("artifact destination escaped the controlled root")
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, destination)
        created_at = datetime.now(UTC)
        ref = ArtifactRef(
            id=artifact_id,
            kind=kind,
            media_type=media_type,
            size=len(content),
            retention=retention,
            created_at=created_at,
        )
        await self._store.save_artifact(ref, relative_path.as_posix())
        return ref

    async def read(self, artifact_id: UUID) -> tuple[ArtifactRef, bytes]:
        stored = await self._store.get_artifact(artifact_id)
        if stored is None:
            raise FileNotFoundError("Artifact not found")
        ref, relative_path = stored
        path = (self._root / relative_path).resolve()
        if self._root not in path.parents:
            raise RuntimeError("stored artifact path escaped the controlled root")
        data = path.read_bytes()
        if len(data) != ref.size:
            raise RuntimeError("artifact size does not match persisted metadata")
        return ref, data

    async def delete(self, artifact_id: UUID) -> bool:
        stored = await self._store.get_artifact(artifact_id)
        if stored is None:
            return False
        _, relative_path = stored
        path = (self._root / relative_path).resolve()
        if self._root not in path.parents:
            raise RuntimeError("stored artifact path escaped the controlled root")
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True
