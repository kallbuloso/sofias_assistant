"""OpenAI Responses API adapter for provider-independent Core contracts."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, cast

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
from openai.types.responses import EasyInputMessageParam, Response
from openai.types.responses.response_text_config_param import ResponseTextConfigParam

from sofias_assistant.ai.contracts import (
    AIMessageRole,
    AIRequest,
    ModelIdentity,
    ProviderCompleted,
    ProviderError,
    ProviderErrorCategory,
    ProviderFailed,
    ProviderInvocationError,
    ProviderResponseMetadata,
    ProviderStreamEvent,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextDelta,
    TextResponse,
    UsageMetadata,
)
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService

_OPENAI_PROVIDER_ID = "openai"
_OpenAIClientFactory = Callable[[str], Any]


class OpenAIProviderAdapter:
    """Stateless OpenAI Responses adapter with credentials held only at call scope."""

    def __init__(
        self,
        *,
        secret_service: SecretService,
        api_key_ref: SecretRef,
        client_factory: _OpenAIClientFactory | None = None,
    ) -> None:
        self._secret_service = secret_service
        self._api_key_ref = api_key_ref
        self._client_factory = client_factory or _create_client

    async def generate_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> TextResponse:
        self._require_openai_model(model)
        response = await self._create_response(model=model, request=request)
        if response.status != "completed":
            raise _terminal_failure(response.status)
        return TextResponse(
            text=response.output_text,
            metadata=_metadata(request, model, response),
            usage=_usage(response),
        )

    def stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        self._require_openai_model(model)
        return self._stream_text(model=model, request=request)

    async def generate_structured_output(
        self,
        *,
        model: ModelIdentity,
        request: AIRequest,
        spec: StructuredOutputSpec,
    ) -> StructuredOutputResult:
        self._require_openai_model(model)
        response = await self._create_response(
            model=model,
            request=request,
            text=cast(
                ResponseTextConfigParam,
                {
                    "format": {
                        "type": "json_schema",
                        "name": spec.name,
                        "schema": spec.schema,
                        "strict": True,
                    }
                },
            ),
        )
        if response.status != "completed":
            raise _terminal_failure(response.status)
        try:
            value = json.loads(response.output_text)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderInvocationError(
                ProviderError(
                    ProviderErrorCategory.INVALID_REQUEST,
                    "OpenAI returned invalid structured output",
                    False,
                )
            ) from error
        return StructuredOutputResult(
            value, _metadata(request, model, response), _usage(response)
        )

    async def _create_response(
        self,
        *,
        model: ModelIdentity,
        request: AIRequest,
        text: ResponseTextConfigParam | None = None,
    ) -> Response:
        client = self._client()
        try:
            if text is None:
                return cast(
                    Response,
                    await client.responses.create(
                        model=model.model_id,
                        input=_input_messages(request),
                        store=False,
                        truncation="disabled",
                    ),
                )
            return cast(
                Response,
                await client.responses.create(
                    model=model.model_id,
                    input=_input_messages(request),
                    text=text,
                    store=False,
                    truncation="disabled",
                ),
            )
        except _OPENAI_ERRORS as error:
            raise _normalize_error(error) from error
        finally:
            await client.close()

    async def _stream_text(
        self, *, model: ModelIdentity, request: AIRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        client = self._client()
        metadata = ProviderResponseMetadata(request.request_id, model)
        try:
            stream = await client.responses.create(
                model=model.model_id,
                input=_input_messages(request),
                stream=True,
                store=False,
                truncation="disabled",
            )
            async for event in stream:
                if event.type == "response.output_text.delta":
                    yield TextDelta(metadata, event.delta)
                elif event.type == "response.completed":
                    if event.response.status == "completed":
                        yield ProviderCompleted(metadata, _usage(event.response))
                    else:
                        yield ProviderFailed(
                            metadata, _terminal_failure(event.response.status).error
                        )
                    return
                elif event.type == "response.failed":
                    yield ProviderFailed(metadata, _terminal_failure("failed").error)
                    return
                elif event.type == "response.incomplete":
                    yield ProviderFailed(
                        metadata, _terminal_failure("incomplete").error
                    )
                    return
        except _OPENAI_ERRORS as error:
            raise _normalize_error(error) from error
        finally:
            await client.close()

    def _client(self) -> Any:
        secret = self._secret_service.get(self._api_key_ref)
        if secret is None:
            raise ProviderInvocationError(
                ProviderError(
                    ProviderErrorCategory.AUTHENTICATION_ERROR,
                    "OpenAI credential is not configured",
                    False,
                )
            )
        return self._client_factory(secret.reveal())

    @staticmethod
    def _require_openai_model(model: ModelIdentity) -> None:
        if model.provider_id != _OPENAI_PROVIDER_ID:
            raise ValueError("OpenAIProviderAdapter requires an openai model identity")


def _create_client(api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, max_retries=0, timeout=30.0)


def _input_messages(request: AIRequest) -> list[EasyInputMessageParam]:
    role_map: dict[AIMessageRole, Literal["system", "user", "assistant"]] = {
        AIMessageRole.SYSTEM: "system",
        AIMessageRole.USER: "user",
        AIMessageRole.ASSISTANT: "assistant",
    }
    return [
        {"role": role_map[message.role], "content": message.text}
        for message in request.messages
    ]


def _metadata(
    request: AIRequest, model: ModelIdentity, response: Response
) -> ProviderResponseMetadata:
    return ProviderResponseMetadata(
        request.request_id, model, getattr(response, "_request_id", None), None
    )


def _usage(response: Response) -> UsageMetadata | None:
    if response.usage is None:
        return None
    details = response.usage.input_tokens_details
    return UsageMetadata(
        response.usage.input_tokens,
        response.usage.output_tokens,
        details.cached_tokens if details is not None else None,
    )


def _terminal_failure(status: object) -> ProviderInvocationError:
    if status == "failed":
        error = ProviderError(
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "OpenAI response failed",
            True,
        )
    elif status == "incomplete":
        error = ProviderError(
            ProviderErrorCategory.INVALID_REQUEST,
            "OpenAI response was incomplete",
            False,
        )
    else:
        error = ProviderError(
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "OpenAI response did not complete",
            True,
        )
    return ProviderInvocationError(error)


_OPENAI_ERRORS = (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    NotFoundError,
    BadRequestError,
    UnprocessableEntityError,
    InternalServerError,
    APIStatusError,
)


def _normalize_error(error: BaseException) -> ProviderInvocationError:
    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        category, message, retryable = (
            ProviderErrorCategory.AUTHENTICATION_ERROR,
            "OpenAI authentication failed",
            False,
        )
    elif isinstance(error, RateLimitError):
        category, message, retryable = (
            ProviderErrorCategory.RATE_LIMITED,
            "OpenAI rate limit reached",
            True,
        )
    elif isinstance(error, APITimeoutError):
        category, message, retryable = (
            ProviderErrorCategory.TIMEOUT,
            "OpenAI request timed out",
            True,
        )
    elif isinstance(error, APIConnectionError):
        category, message, retryable = (
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "OpenAI service is unavailable",
            True,
        )
    elif isinstance(error, NotFoundError):
        category, message, retryable = (
            ProviderErrorCategory.MODEL_UNAVAILABLE,
            "OpenAI model is unavailable",
            False,
        )
    elif isinstance(error, (BadRequestError, UnprocessableEntityError)):
        category, message, retryable = (
            ProviderErrorCategory.INVALID_REQUEST,
            "OpenAI rejected the request",
            False,
        )
    else:
        category, message, retryable = (
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "OpenAI service is unavailable",
            True,
        )
    return ProviderInvocationError(ProviderError(category, message, retryable))
