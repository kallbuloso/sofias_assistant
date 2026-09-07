"""Explicitly opt-in OpenAI Responses API smoke coverage."""

import os
from uuid import uuid4

import pytest

from sofias_assistant.ai.adapters.openai import OpenAIProviderAdapter
from sofias_assistant.ai.contracts import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    ModelIdentity,
    ProviderCompleted,
    StructuredOutputSpec,
)
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService
from sofias_assistant.secrets.windows_store import WindowsCredentialStore

_API_KEY_REF = SecretRef("providers/openai/api-key")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or os.getenv("SOFIAS_ASSISTANT_RUN_OPENAI_PROVIDER_TESTS") != "1",
    reason="requires explicit OpenAI provider smoke opt-in on Windows",
)


def _request(text: str) -> AIRequest:
    return AIRequest(
        uuid4(),
        (
            AIMessage(AIMessageRole.SYSTEM, "Respond concisely."),
            AIMessage(AIMessageRole.USER, text),
        ),
    )


@pytest.mark.integration
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_openai_responses_adapter_live_smoke() -> None:
    secret_service = SecretService(WindowsCredentialStore())
    if secret_service.get(_API_KEY_REF) is None:
        pytest.fail(
            "OpenAI live smoke was enabled but providers/openai/api-key is not configured"
        )

    model_id = os.getenv("SOFIAS_ASSISTANT_OPENAI_SMOKE_MODEL", "gpt-5.6-luna")
    if not model_id.strip():
        pytest.fail("OpenAI live smoke model must not be blank")

    model = ModelIdentity("openai", model_id)
    adapter = OpenAIProviderAdapter(
        secret_service=secret_service,
        api_key_ref=_API_KEY_REF,
    )

    text_request = _request("Return a short greeting.")
    text_response = await adapter.generate_text(model=model, request=text_request)
    assert isinstance(text_response.text, str)
    assert text_response.text
    assert text_response.metadata.request_id == text_request.request_id
    assert text_response.metadata.model == model
    assert text_response.metadata.provider_session_id is None

    stream_request = _request("Return a short greeting.")
    events = [
        event
        async for event in adapter.stream_text(model=model, request=stream_request)
    ]
    terminals = [event for event in events if isinstance(event, ProviderCompleted)]
    assert len(terminals) == 1
    assert isinstance(events[-1], ProviderCompleted)
    assert all(not type(event).__module__.startswith("openai") for event in events)

    structured_request = _request("Return an object with one boolean field named ok.")
    structured = await adapter.generate_structured_output(
        model=model,
        request=structured_request,
        spec=StructuredOutputSpec(
            "smoke_result",
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        ),
    )
    assert isinstance(structured.value, dict)
    assert set(structured.value) == {"ok"}
    assert isinstance(structured.value["ok"], bool)
