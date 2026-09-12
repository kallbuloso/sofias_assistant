"""Deterministic no-network tests for the OpenAI provider adapter."""

import asyncio
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from sofias_assistant.ai.adapters.openai import OpenAIProviderAdapter
from sofias_assistant.ai.contracts import (
    AIMessage,
    AIMessageRole,
    AIRequest,
    AssistantAudioChunk,
    AssistantTranscriptFinal,
    AudioEncoding,
    AudioFormat,
    AudioInputFrame,
    ModelIdentity,
    ProviderCompleted,
    ProviderErrorCategory,
    ProviderFailed,
    ProviderInvocationError,
    RealtimeContextSeed,
    RealtimeInteractionId,
    RealtimeResponseCompleted,
    RealtimeSessionFailed,
    RealtimeSessionId,
    RealtimeSessionRequest,
    StructuredOutputSpec,
    TextDelta,
    UserTranscriptFinal,
)
from sofias_assistant.ai.providers import (
    RealtimeProvider,
    StructuredOutputProvider,
    TextGenerationProvider,
    TextStreamingProvider,
)
from sofias_assistant.secrets.models import SecretRef, SecretValue
from sofias_assistant.secrets.service import SecretService


class _Store:
    def __init__(self) -> None:
        self.value: SecretValue | None = SecretValue("test-secret")

    def get(self, _: SecretRef) -> SecretValue | None:
        return self.value

    def set(self, _: SecretRef, value: SecretValue) -> None:
        self.value = value

    def delete(self, _: SecretRef) -> bool:
        self.value = None
        return True


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.responses = self
        self.closed = False

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream()
        return SimpleNamespace(
            status="completed",
            output_text='{"answer":"ok"}' if "text" in kwargs else "answer",
            usage=SimpleNamespace(
                input_tokens=2,
                output_tokens=1,
                input_tokens_details=SimpleNamespace(cached_tokens=1),
            ),
            _request_id="request-id",
        )

    async def _stream(self) -> AsyncIterator[object]:
        yield SimpleNamespace(type="response.output_text.delta", delta="a")
        yield SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(status="completed", usage=None),
        )

    async def close(self) -> None:
        self.closed = True


class _RealtimeNamespace:
    def __init__(self, connection: "_RealtimeConnection") -> None:
        self._connection = connection
        self.calls: list[dict[str, object]] = []

    def connect(self, **kwargs: object) -> "_RealtimeManager":
        self.calls.append(kwargs)
        return _RealtimeManager(self._connection)


class _RealtimeManager:
    def __init__(self, connection: "_RealtimeConnection") -> None:
        self._connection = connection

    async def enter(self) -> "_RealtimeConnection":
        return self._connection


class _RealtimeConnection:
    def __init__(self, events: tuple[object, ...] = ()) -> None:
        self._events = events
        self.session = SimpleNamespace(update=self._update)
        self.input_audio_buffer = SimpleNamespace(
            append=self._append, commit=self._commit
        )
        self.response = SimpleNamespace(create=self._create, cancel=self._cancel)
        self.conversation = SimpleNamespace(
            item=SimpleNamespace(create=self._create_item)
        )
        self.session_updates: list[dict[str, object]] = []
        self.audio: list[str] = []
        self.commits = 0
        self.responses: list[dict[str, object]] = []
        self.items: list[dict[str, object]] = []
        self.cancellations: list[dict[str, object]] = []
        self.closed = False

    async def _update(self, *, session: dict[str, object]) -> None:
        self.session_updates.append(session)

    async def _append(self, *, audio: str) -> None:
        self.audio.append(audio)

    async def _commit(self) -> None:
        self.commits += 1

    async def _create(self, *, response: dict[str, object]) -> None:
        self.responses.append(response)

    async def _cancel(self, **kwargs: object) -> None:
        self.cancellations.append(kwargs)

    async def _create_item(self, *, item: dict[str, object]) -> None:
        self.items.append(item)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for event in self._events:
            if isinstance(event, BaseException):
                raise event
            yield event


class _RealtimeClient:
    def __init__(self, connection: _RealtimeConnection) -> None:
        self.realtime = _RealtimeNamespace(connection)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _request() -> AIRequest:
    return AIRequest(
        uuid4(),
        (
            AIMessage(AIMessageRole.SYSTEM, "  system  "),
            AIMessage(AIMessageRole.USER, "  user  "),
            AIMessage(AIMessageRole.ASSISTANT, "  assistant  "),
        ),
    )


def _audio_format() -> AudioFormat:
    return AudioFormat(AudioEncoding.PCM16, 24_000, 1)


def _realtime_request() -> RealtimeSessionRequest:
    return RealtimeSessionRequest(
        RealtimeSessionId(uuid4()),
        _audio_format(),
        _audio_format(),
        RealtimeContextSeed(
            (
                AIMessage(AIMessageRole.SYSTEM, "Realtime system instruction."),
                AIMessage(AIMessageRole.USER, "Previous user turn."),
                AIMessage(AIMessageRole.ASSISTANT, "Previous assistant turn."),
            ),
            True,
        ),
    )


def _adapter(client: object, store: _Store | None = None) -> OpenAIProviderAdapter:
    return OpenAIProviderAdapter(
        secret_service=SecretService(store or _Store()),
        api_key_ref=SecretRef("providers/openai/api-key"),
        client_factory=lambda _: client,
    )


@pytest.mark.asyncio
async def test_openai_adapter_maps_stateless_text_request_and_response() -> None:
    client = _Client()
    request = _request()
    model = ModelIdentity("openai", "configured-model")

    response = await _adapter(client).generate_text(model=model, request=request)

    assert response.text == "answer"
    assert response.metadata.request_id == request.request_id
    assert response.metadata.model == model
    assert response.metadata.provider_request_id == "request-id"
    assert response.usage is not None and response.usage.cached_tokens == 1
    assert client.calls == [
        {
            "model": "configured-model",
            "input": [
                {"role": "system", "content": "  system  "},
                {"role": "user", "content": "  user  "},
                {"role": "assistant", "content": "  assistant  "},
            ],
            "store": False,
            "truncation": "disabled",
        }
    ]
    assert client.closed


@pytest.mark.asyncio
async def test_openai_realtime_adapter_normalizes_manual_ptt_audio_and_response() -> (
    None
):
    provider_item_id = "provider-item"
    provider_response_id = "provider-response"
    audio = b"\x01\x02\x03\x04"
    connection = _RealtimeConnection(
        (
            SimpleNamespace(
                type="input_audio_buffer.committed", item_id=provider_item_id
            ),
            SimpleNamespace(
                type="conversation.item.input_audio_transcription.completed",
                item_id=provider_item_id,
                transcript="spoken request",
            ),
            SimpleNamespace(
                type="response.created",
                response=SimpleNamespace(id=provider_response_id),
            ),
            SimpleNamespace(
                type="response.output_audio.delta",
                response_id=provider_response_id,
                delta="AQIDBA==",
            ),
            SimpleNamespace(
                type="response.output_audio_transcript.done",
                response_id=provider_response_id,
                transcript="spoken response",
            ),
            SimpleNamespace(
                type="response.done",
                response=SimpleNamespace(id=provider_response_id, status="completed"),
            ),
        )
    )
    client = _RealtimeClient(connection)
    request = _realtime_request()
    adapter = _adapter(client)

    session = await adapter.open_realtime_session(
        model=ModelIdentity("openai", "gpt-realtime"), request=request
    )
    interaction_id = RealtimeInteractionId(uuid4())
    await session.start_interaction(realtime_interaction_id=interaction_id)
    await session.send_audio(frame=AudioInputFrame(0, audio))
    await session.commit_interaction(realtime_interaction_id=interaction_id)
    events = [event async for event in session.events()]
    await session.close()

    assert client.realtime.calls == [{"model": "gpt-realtime", "max_retries": 0}]
    assert connection.session_updates == [
        {
            "type": "realtime",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24_000},
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                    "turn_detection": None,
                },
                "output": {"format": {"type": "audio/pcm", "rate": 24_000}},
            },
            "output_modalities": ["audio"],
            "instructions": "Realtime system instruction.",
        }
    ]
    assert connection.items == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Previous user turn."}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "input_text", "text": "Previous assistant turn."}],
        },
    ]
    assert connection.audio == ["AQIDBA=="]
    assert connection.commits == 1
    assert connection.responses == [{"output_modalities": ["audio"]}]
    assert [type(event) for event in events] == [
        UserTranscriptFinal,
        AssistantAudioChunk,
        AssistantTranscriptFinal,
        RealtimeResponseCompleted,
    ]
    assert [event.sequence for event in events] == [0, 1, 2, 3]
    user_final, audio_chunk, assistant_final, _completed = events
    assert isinstance(user_final, UserTranscriptFinal)
    assert isinstance(audio_chunk, AssistantAudioChunk)
    assert isinstance(assistant_final, AssistantTranscriptFinal)
    assert user_final.text == "spoken request"
    assert audio_chunk.audio == audio
    assert audio_chunk.audio_format == _audio_format()
    assert assistant_final.text == "spoken response"
    assert connection.closed and client.closed


@pytest.mark.asyncio
async def test_openai_realtime_adapter_redacts_transport_failure_and_closes_once() -> (
    None
):
    connection = _RealtimeConnection((RuntimeError("SDK SECRET INTERNAL"),))
    client = _RealtimeClient(connection)
    session = await _adapter(client).open_realtime_session(
        model=ModelIdentity("openai", "gpt-realtime"), request=_realtime_request()
    )

    events = [event async for event in session.events()]
    await session.close()
    await session.close()

    assert len(events) == 1 and isinstance(events[0], RealtimeSessionFailed)
    assert events[0].error.safe_message == "OpenAI realtime session failed"
    assert "SDK SECRET INTERNAL" not in repr(events[0])
    assert connection.closed and client.closed


@pytest.mark.asyncio
async def test_openai_adapter_streams_one_normalized_terminal() -> None:
    client = _Client()
    events = [
        event
        async for event in _adapter(client).stream_text(
            model=ModelIdentity("openai", "configured-model"), request=_request()
        )
    ]

    assert isinstance(events[0], TextDelta)
    assert isinstance(events[-1], ProviderCompleted)
    assert len([event for event in events if isinstance(event, ProviderCompleted)]) == 1
    assert client.calls[0]["store"] is False
    assert client.calls[0]["truncation"] == "disabled"


@pytest.mark.asyncio
async def test_openai_adapter_rejects_missing_secret_and_provider_mismatch() -> None:
    client = _Client()
    missing = _adapter(client, _Store())
    with pytest.raises(ValueError):
        await missing.generate_text(
            model=ModelIdentity("other", "model"), request=_request()
        )
    store = _Store()
    store.value = None
    with pytest.raises(ProviderInvocationError, match="credential is not configured"):
        await _adapter(client, store).generate_text(
            model=ModelIdentity("openai", "model"), request=_request()
        )
    assert client.calls == []


def _status_response(status_code: int) -> httpx2.Response:
    request = httpx2.Request("POST", "https://openai.test/v1/responses")
    return httpx2.Response(
        status_code, request=request, json={"error": {"message": "raw"}}
    )


def _status_error(error_type: type[APIStatusError], status_code: int) -> APIStatusError:
    return error_type(
        "raw provider error", response=_status_response(status_code), body={}
    )


class _ErrorClient:
    def __init__(self, error: BaseException) -> None:
        self.responses = self
        self._error = error
        self.closed = False

    async def create(self, **_: object) -> object:
        raise self._error

    async def close(self) -> None:
        self.closed = True


def _response(
    *, status: str = "completed", output_text: str | None = "answer"
) -> object:
    return SimpleNamespace(
        status=status,
        output_text=output_text,
        usage=SimpleNamespace(
            input_tokens=2,
            output_tokens=1,
            input_tokens_details=SimpleNamespace(cached_tokens=1),
        ),
        _request_id="request-id",
    )


class _ConfiguredClient(_Client):
    def __init__(
        self,
        *,
        response: object | None = None,
        stream_events: tuple[object, ...] = (),
        stream_error: BaseException | None = None,
    ) -> None:
        super().__init__()
        self._configured_response = response or _response()
        self._stream_events = stream_events
        self._stream_error = stream_error

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._configured_stream()
        return self._configured_response

    async def _configured_stream(self) -> AsyncIterator[object]:
        for event in self._stream_events:
            yield event
        if self._stream_error is not None:
            raise self._stream_error


def _spec() -> StructuredOutputSpec:
    return StructuredOutputSpec(
        "answer", {"type": "object", "properties": {"answer": {"type": "string"}}}
    )


def _as_provider_protocols(
    provider: OpenAIProviderAdapter,
) -> tuple[
    TextGenerationProvider,
    TextStreamingProvider,
    StructuredOutputProvider,
    RealtimeProvider,
]:
    return provider, provider, provider, provider


def test_openai_adapter_satisfies_provider_protocols() -> None:
    assert len(_as_provider_protocols(_adapter(_Client()))) == 4


@pytest.mark.asyncio
async def test_openai_adapter_maps_structured_request_and_response() -> None:
    client = _ConfiguredClient(response=_response(output_text='{"answer":"ok"}'))
    result = await _adapter(client).generate_structured_output(
        model=ModelIdentity("openai", "configured-model"),
        request=_request(),
        spec=_spec(),
    )

    assert result.value == {"answer": "ok"}
    assert result.metadata.provider_request_id == "request-id"
    assert result.usage is not None and result.usage.cached_tokens == 1
    assert client.calls[0]["model"] == "configured-model"
    assert client.calls[0]["store"] is False
    assert client.calls[0]["truncation"] == "disabled"
    assert client.calls[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": "answer",
            "schema": _spec().schema,
            "strict": True,
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("output_text", ("not-json", None))
async def test_openai_adapter_rejects_invalid_structured_output(
    output_text: str | None,
) -> None:
    with pytest.raises(ProviderInvocationError) as raised:
        await _adapter(
            _ConfiguredClient(response=_response(output_text=output_text))
        ).generate_structured_output(
            model=ModelIdentity("openai", "configured-model"),
            request=_request(),
            spec=_spec(),
        )

    assert raised.value.error.category is ProviderErrorCategory.INVALID_REQUEST
    assert (
        raised.value.error.safe_message == "OpenAI returned invalid structured output"
    )
    assert "not-json" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "category", "message", "retryable"),
    (
        (
            "failed",
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "OpenAI response failed",
            True,
        ),
        (
            "incomplete",
            ProviderErrorCategory.INVALID_REQUEST,
            "OpenAI response was incomplete",
            False,
        ),
    ),
)
async def test_openai_adapter_normalizes_noncompleted_responses(
    status: str,
    category: ProviderErrorCategory,
    message: str,
    retryable: bool,
) -> None:
    for structured in (False, True):
        adapter = _adapter(_ConfiguredClient(response=_response(status=status)))
        with pytest.raises(ProviderInvocationError) as raised:
            if structured:
                await adapter.generate_structured_output(
                    model=ModelIdentity("openai", "configured-model"),
                    request=_request(),
                    spec=_spec(),
                )
            else:
                await adapter.generate_text(
                    model=ModelIdentity("openai", "configured-model"),
                    request=_request(),
                )
        assert raised.value.error.category is category
        assert raised.value.error.safe_message == message
        assert raised.value.error.retryable is retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "category", "message", "retryable"),
    (
        (
            "response.failed",
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "OpenAI response failed",
            True,
        ),
        (
            "response.incomplete",
            ProviderErrorCategory.INVALID_REQUEST,
            "OpenAI response was incomplete",
            False,
        ),
    ),
)
async def test_openai_adapter_normalizes_stream_terminal_responses(
    event_type: str,
    category: ProviderErrorCategory,
    message: str,
    retryable: bool,
) -> None:
    events = [
        event
        async for event in _adapter(
            _ConfiguredClient(stream_events=(SimpleNamespace(type=event_type),))
        ).stream_text(
            model=ModelIdentity("openai", "configured-model"), request=_request()
        )
    ]

    assert len(events) == 1 and isinstance(events[0], ProviderFailed)
    assert events[0].error.category is category
    assert events[0].error.safe_message == message
    assert events[0].error.retryable is retryable


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(httpx2.Request("POST", "https://openai.test/v1/responses"))


def _connection_error() -> APIConnectionError:
    return APIConnectionError(
        message="raw provider error",
        request=httpx2.Request("POST", "https://openai.test/v1/responses"),
    )


_ERROR_CASES: tuple[
    tuple[Callable[[], BaseException], ProviderErrorCategory, str, bool], ...
] = (
    (
        lambda: _status_error(AuthenticationError, 401),
        ProviderErrorCategory.AUTHENTICATION_ERROR,
        "OpenAI authentication failed",
        False,
    ),
    (
        lambda: _status_error(PermissionDeniedError, 403),
        ProviderErrorCategory.AUTHENTICATION_ERROR,
        "OpenAI authentication failed",
        False,
    ),
    (
        lambda: _status_error(RateLimitError, 429),
        ProviderErrorCategory.RATE_LIMITED,
        "OpenAI rate limit reached",
        True,
    ),
    (_timeout_error, ProviderErrorCategory.TIMEOUT, "OpenAI request timed out", True),
    (
        _connection_error,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        "OpenAI service is unavailable",
        True,
    ),
    (
        lambda: _status_error(NotFoundError, 404),
        ProviderErrorCategory.MODEL_UNAVAILABLE,
        "OpenAI model is unavailable",
        False,
    ),
    (
        lambda: _status_error(BadRequestError, 400),
        ProviderErrorCategory.INVALID_REQUEST,
        "OpenAI rejected the request",
        False,
    ),
    (
        lambda: _status_error(UnprocessableEntityError, 422),
        ProviderErrorCategory.INVALID_REQUEST,
        "OpenAI rejected the request",
        False,
    ),
    (
        lambda: _status_error(InternalServerError, 500),
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        "OpenAI service is unavailable",
        True,
    ),
    (
        lambda: _status_error(APIStatusError, 418),
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        "OpenAI service is unavailable",
        True,
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("factory", "category", "message", "retryable"), _ERROR_CASES)
async def test_openai_adapter_normalizes_sdk_errors(
    factory: Callable[[], BaseException],
    category: ProviderErrorCategory,
    message: str,
    retryable: bool,
) -> None:
    with pytest.raises(ProviderInvocationError) as raised:
        await _adapter(_ErrorClient(factory())).generate_text(
            model=ModelIdentity("openai", "configured-model"), request=_request()
        )

    assert raised.value.error.category is category
    assert raised.value.error.safe_message == message
    assert raised.value.error.retryable is retryable
    assert "raw provider error" not in str(raised.value)


@pytest.mark.asyncio
async def test_openai_adapter_normalizes_sdk_error_during_stream_iteration() -> None:
    stream = _adapter(
        _ConfiguredClient(
            stream_events=(
                SimpleNamespace(type="response.output_text.delta", delta="partial"),
            ),
            stream_error=_timeout_error(),
        )
    ).stream_text(model=ModelIdentity("openai", "configured-model"), request=_request())

    first = await anext(stream)
    assert isinstance(first, TextDelta)
    assert first.text == "partial"
    with pytest.raises(ProviderInvocationError) as raised:
        await anext(stream)

    assert raised.value.error.category is ProviderErrorCategory.TIMEOUT
    assert raised.value.error.safe_message == "OpenAI request timed out"
    assert raised.value.error.retryable is True


@pytest.mark.asyncio
async def test_openai_adapter_propagates_stream_cancellation() -> None:
    stream = _adapter(
        _ConfiguredClient(stream_error=asyncio.CancelledError())
    ).stream_text(model=ModelIdentity("openai", "configured-model"), request=_request())

    with pytest.raises(asyncio.CancelledError):
        await anext(stream)


@pytest.mark.asyncio
async def test_openai_adapter_disables_sdk_retries() -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(429, request=request, json={"error": {"message": "raw"}})

    def factory(api_key: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=api_key,
            base_url="https://openai.test/v1",
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            max_retries=0,
            timeout=30.0,
        )

    with pytest.raises(ProviderInvocationError) as raised:
        await OpenAIProviderAdapter(
            secret_service=SecretService(_Store()),
            api_key_ref=SecretRef("providers/openai/api-key"),
            client_factory=factory,
        ).generate_text(
            model=ModelIdentity("openai", "configured-model"), request=_request()
        )

    assert attempts == 1
    assert raised.value.error.category is ProviderErrorCategory.RATE_LIMITED
