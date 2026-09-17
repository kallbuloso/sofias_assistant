"""The Client adapter exercises the real authenticated Local Client Boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from sofias_assistant.client_app.api import CoreApiClient, CoreApiError
from sofias_assistant.client_app.service import ClientApplicationService
from sofias_assistant.client_boundary.boundary import LocalClientBoundary
from sofias_assistant.client_boundary.http_api import create_local_http_app
from sofias_assistant.conversation.models import Conversation
from sofias_assistant.conversation.runtime import ConversationState
from sofias_assistant.core import CoreState
from sofias_assistant.execution import ExecutionRuntime, TaskRuntime
from sofias_assistant.health.models import (
    ComponentHealth,
    HealthStatus,
    RuntimeHealthSnapshot,
)
from sofias_assistant.persistence.database import (
    create_async_engine,
    create_session_factory,
)
from sofias_assistant.persistence.migration_runner import upgrade_to_head
from sofias_assistant.proactivity.runtime import ProactivityRuntime
from sofias_assistant.runtime.bootstrap import operational_database_url


class FakeCore:
    state = CoreState.RUNNING
    runtime_session_id = uuid4()
    health = RuntimeHealthSnapshot(
        (
            ComponentHealth("scheduler", HealthStatus.HEALTHY),
            ComponentHealth("notifications", HealthStatus.HEALTHY),
        )
    )


class FakeConversation:
    def __init__(self) -> None:
        self.conversation = Conversation(uuid4(), datetime.now(UTC), datetime.now(UTC))

    async def create_conversation(self) -> Conversation:
        return self.conversation

    async def get_conversation_state(self, conversation_id):
        if conversation_id != self.conversation.id:
            raise RuntimeError("conversation not found")
        return ConversationState(self.conversation, ())

    def stream_text(self, _command):
        raise AssertionError("streaming is covered by the existing Core boundary suite")


@pytest_asyncio.fixture
async def local_boundary(tmp_path: Path):
    url = operational_database_url(tmp_path / "state.sqlite")
    await asyncio.to_thread(upgrade_to_head, url)
    engine = create_async_engine(url)
    sessions = create_session_factory(engine)
    execution = ExecutionRuntime(sessions, artifact_root=tmp_path / "artifacts")
    tasks = TaskRuntime(execution)
    runtime = ProactivityRuntime(sessions, execution.audit)
    conversation = FakeConversation()
    boundary = LocalClientBoundary(
        port=0,
        app_factory=lambda authenticator, client_sessions: create_local_http_app(
            authenticator,
            client_sessions,
            core=FakeCore(),
            conversation=conversation,
            execution=execution,
            tasks=tasks,
            proactivity=runtime,
        ),
    )
    access = await boundary.start()
    try:
        yield access, conversation
    finally:
        await boundary.stop()
        await tasks.stop()
        await runtime.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_boundary_auth_sync_and_core_owned_conversation(
    local_boundary,
) -> None:
    access, conversation = local_boundary
    client = CoreApiClient(
        f"http://{access.host}:{access.port}", access.credential.reveal()
    )
    try:
        service = ClientApplicationService(client)
        snapshot = await asyncio.to_thread(service.connect)
        assert snapshot.connection.value == "CONNECTED"
        # connect() alone must never create a Conversation just because the
        # Desktop started (Contract v1 SS41 / Slice 10 SA-B040).
        assert service.conversation_id is None
        assert snapshot.notifications == ()
        assert snapshot.tasks == ()

        conversation_id = await asyncio.to_thread(service.start_new_conversation)
        assert conversation_id == conversation.conversation.id
    finally:
        await asyncio.to_thread(client.close)


@pytest.mark.asyncio
async def test_real_boundary_rejects_wrong_credential(local_boundary) -> None:
    access, _ = local_boundary
    client = CoreApiClient(f"http://{access.host}:{access.port}", "wrong-credential")
    with pytest.raises(CoreApiError, match="authentication"):
        await asyncio.to_thread(client.connect)
