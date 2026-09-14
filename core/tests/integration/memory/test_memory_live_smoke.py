"""Explicitly opt-in real Sofias Memory v0.7 Cognitive Memory smoke coverage.

Not part of the default suite. Proves the Adapter against a real, running
Sofias Memory v0.7 instance: /info handshake, PROFILE/SEMANTIC Create,
Recall, same-key Create replay, Supersede, historical Recall, Forget, and
new-key repeated Forget. Cleans up the created items via Forget when safe.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sofias_assistant.config.loader import load_runtime_config, resolve_environment
from sofias_assistant.memory.adapter import SofiasMemoryAdapter
from sofias_assistant.memory.models import (
    CreateMemoryRequest,
    MemoryLifecycle,
    MemoryOriginKind,
    MemoryProvenance,
    MemoryType,
    RecallRequest,
    SupersedeMemoryRequest,
)
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

_API_KEY_REF = SecretRef("integrations/sofias-memory/api-key")

# `core/.env`: explicit, well-known local dev file. Never read implicitly by
# production; only this opt-in smoke consults it, and only when present, so
# CI (which has no `.env`) keeps resolving the opt-in gate from the real
# environment exactly as before.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def _local_env_file() -> Path | None:
    return _ENV_FILE if _ENV_FILE.is_file() else None


pytestmark = pytest.mark.skipif(
    resolve_environment(env_file=_local_env_file()).get(
        "SOFIAS_ASSISTANT_RUN_MEMORY_INTEGRATION_TESTS"
    )
    != "1",
    reason="requires explicit Sofias Memory integration smoke opt-in",
)


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_sofias_memory_v070_live_contract_smoke() -> None:
    config = load_runtime_config(env_file=_local_env_file())
    if not config.memory.enabled or config.memory.base_url is None:
        pytest.fail(
            "SOFIAS_ASSISTANT_MEMORY_BASE_URL must be configured for this smoke"
        )
    secret_service = SecretService(WindowsCredentialStore())
    if secret_service.get(_API_KEY_REF) is None:
        pytest.fail(
            "Sofias Memory API key must be stored at "
            "SecretRef('integrations/sofias-memory/api-key') for this smoke"
        )

    adapter = SofiasMemoryAdapter(
        base_url=config.memory.base_url,
        secret_service=secret_service,
        api_key_ref=_API_KEY_REF,
        timeout_seconds=config.memory.timeout_seconds,
    )
    scope = f"project:gate-i6-smoke-{uuid.uuid4().hex[:12]}"
    created_memory_ids: list[uuid.UUID] = []

    try:
        capabilities = await adapter.probe_contract()
        assert capabilities.supports_cognitive_memory is True

        profile_key = f"sofias-assistant:memory:create:{uuid.uuid4()}"
        profile = await adapter.create_memory(
            CreateMemoryRequest(
                memory_type=MemoryType.PROFILE,
                scope=scope,
                content="Gate I6 smoke: prefers dark mode.",
                provenance=MemoryProvenance(
                    origin_kind=MemoryOriginKind.USER_ASSERTED,
                    turn_uuid=uuid.uuid4(),
                ),
            ),
            idempotency_key=profile_key,
        )
        created_memory_ids.append(profile.memory_id)
        assert profile.memory_type is MemoryType.PROFILE
        assert profile.lifecycle is MemoryLifecycle.ACTIVE

        semantic_key = f"sofias-assistant:memory:create:{uuid.uuid4()}"
        semantic = await adapter.create_memory(
            CreateMemoryRequest(
                memory_type=MemoryType.SEMANTIC,
                scope=scope,
                content="Gate I6 smoke: this project uses SQLite.",
                provenance=MemoryProvenance(
                    origin_kind=MemoryOriginKind.USER_ASSERTED,
                    turn_uuid=uuid.uuid4(),
                ),
            ),
            idempotency_key=semantic_key,
        )
        created_memory_ids.append(semantic.memory_id)
        assert semantic.memory_type is MemoryType.SEMANTIC

        replay = await adapter.create_memory(
            CreateMemoryRequest(
                memory_type=MemoryType.PROFILE,
                scope=scope,
                content="Gate I6 smoke: prefers dark mode.",
                provenance=MemoryProvenance(
                    origin_kind=MemoryOriginKind.USER_ASSERTED,
                    turn_uuid=profile.provenance.turn_uuid,
                ),
            ),
            idempotency_key=profile_key,
        )
        assert replay.memory_id == profile.memory_id

        recall_result = await adapter.recall_memories(
            RecallRequest(query="dark mode", scopes=(scope,))
        )
        assert any(
            item.memory.memory_id == profile.memory_id for item in recall_result.items
        )

        t1 = datetime.now(UTC)
        supersede_result = await adapter.supersede_memory(
            profile.memory_id,
            SupersedeMemoryRequest(
                content="Gate I6 smoke: now prefers light mode.",
                provenance=MemoryProvenance(
                    origin_kind=MemoryOriginKind.USER_ASSERTED,
                    turn_uuid=uuid.uuid4(),
                ),
            ),
            idempotency_key=f"sofias-assistant:memory:supersede:{uuid.uuid4()}",
        )
        created_memory_ids.append(supersede_result.replacement.memory_id)
        assert supersede_result.old.lifecycle is MemoryLifecycle.SUPERSEDED
        assert supersede_result.replacement.lifecycle is MemoryLifecycle.ACTIVE

        historical = await adapter.recall_memories(
            RecallRequest(
                query="dark mode",
                scopes=(scope,),
                as_of=t1,
                include_superseded=True,
            )
        )
        historical_match = next(
            item
            for item in historical.items
            if item.memory.memory_id == profile.memory_id
        )
        assert historical_match.is_current_truth is True

        forgotten = await adapter.forget_memory(
            profile.memory_id,
            idempotency_key=f"sofias-assistant:memory:forget:{uuid.uuid4()}",
        )
        assert forgotten.lifecycle is MemoryLifecycle.FORGOTTEN

        repeated_forget = await adapter.forget_memory(
            profile.memory_id,
            idempotency_key=f"sofias-assistant:memory:forget:{uuid.uuid4()}",
        )
        assert repeated_forget.lifecycle is MemoryLifecycle.FORGOTTEN
    finally:
        for memory_id in created_memory_ids:
            try:
                await adapter.forget_memory(
                    memory_id,
                    idempotency_key=f"sofias-assistant:memory:forget:{uuid.uuid4()}",
                )
            except Exception:  # noqa: BLE001 - best-effort smoke cleanup
                pass
