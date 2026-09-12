"""Explicitly opt-in smoke coverage for the OpenAI Realtime adapter."""

import asyncio
import os
from uuid import uuid4

import pytest

from sofias_assistant.ai.adapters.openai import OpenAIProviderAdapter
from sofias_assistant.ai.contracts import (
    AIMessage,
    AIMessageRole,
    AssistantAudioChunk,
    AudioEncoding,
    AudioFormat,
    AudioInputFrame,
    ModelIdentity,
    RealtimeContextSeed,
    RealtimeInteractionId,
    RealtimeSessionId,
    RealtimeSessionRequest,
    UserTranscriptFinal,
)
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

_API_KEY_REF = SecretRef("providers/openai/api-key")
_AUDIO_FORMAT = AudioFormat(AudioEncoding.PCM16, 24_000, 1)

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.getenv("SOFIAS_ASSISTANT_RUN_OPENAI_REALTIME_TESTS") != "1",
    reason="requires explicit OpenAI Realtime smoke opt-in on Windows",
)


def _request() -> RealtimeSessionRequest:
    return RealtimeSessionRequest(
        RealtimeSessionId(uuid4()),
        _AUDIO_FORMAT,
        _AUDIO_FORMAT,
        RealtimeContextSeed(
            (
                AIMessage(
                    AIMessageRole.SYSTEM,
                    "Respond briefly in audio even if the input is not intelligible.",
                ),
            ),
            True,
        ),
    )


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_openai_realtime_adapter_live_ptt_cancel_smoke() -> None:
    secret_service = SecretService(WindowsCredentialStore())
    if secret_service.get(_API_KEY_REF) is None:
        pytest.fail(
            "OpenAI Realtime smoke was enabled but providers/openai/api-key is not configured"
        )
    model_id = os.getenv(
        "SOFIAS_ASSISTANT_OPENAI_REALTIME_SMOKE_MODEL", "gpt-realtime-1.5"
    )
    if not model_id.strip():
        pytest.fail("OpenAI Realtime smoke model must not be blank")

    request = _request()
    adapter = OpenAIProviderAdapter(
        secret_service=secret_service,
        api_key_ref=_API_KEY_REF,
    )
    session = await adapter.open_realtime_session(
        model=ModelIdentity("openai", model_id), request=request
    )
    interaction_id = RealtimeInteractionId(uuid4())
    transcript_seen = False
    audio_seen = False
    try:
        await session.start_interaction(realtime_interaction_id=interaction_id)
        # A short, valid PCM16 frame proves append/commit without requiring a
        # bundled speech recording or a secret-bearing test fixture.
        await session.send_audio(frame=AudioInputFrame(0, b"\x00\x00" * 12_000))
        await session.commit_interaction(realtime_interaction_id=interaction_id)
        async with asyncio.timeout(90):
            async for event in session.events():
                assert not type(event).__module__.startswith("openai")
                if isinstance(event, UserTranscriptFinal):
                    transcript_seen = True
                if isinstance(event, AssistantAudioChunk):
                    audio_seen = True
                    await session.interrupt(realtime_interaction_id=interaction_id)
                    break
        assert transcript_seen
        assert audio_seen
    finally:
        await session.close()
