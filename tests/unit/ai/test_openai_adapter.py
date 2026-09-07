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
    ModelIdentity,
    ProviderCompleted,
    ProviderErrorCategory,
    ProviderFailed,
    ProviderInvocationError,
    StructuredOutputSpec,
    TextDelta,
)
from sofias_assistant.ai.providers import (
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


def _request() -> AIRequest:
    return AIRequest(
        uuid4(),
        (
            AIMessage(AIMessageRole.SYSTEM, "  system  "),
            AIMessage(AIMessageRole.USER, "  user  "),
            AIMessage(AIMessageRole.ASSISTANT, "  assistant  "),
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
) -> tuple[TextGenerationProvider, TextStreamingProvider, StructuredOutputProvider]:
    return provider, provider, provider


def test_openai_adapter_satisfies_provider_protocols() -> None:
    assert len(_as_provider_protocols(_adapter(_Client()))) == 3


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
