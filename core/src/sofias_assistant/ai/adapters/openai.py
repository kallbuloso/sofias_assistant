"""OpenAI adapters isolated from provider-independent Core contracts."""

import asyncio
import base64
import contextlib
import json
from collections import deque
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
    AssistantAudioChunk,
    AssistantTranscriptFinal,
    AssistantTranscriptPartial,
    AudioEncoding,
    AudioFormat,
    AudioInputFrame,
    ModelIdentity,
    ProviderCompleted,
    ProviderError,
    ProviderErrorCategory,
    ProviderFailed,
    ProviderInvocationError,
    ProviderResponseMetadata,
    ProviderStreamEvent,
    RealtimeInteractionId,
    RealtimeProviderEvent,
    RealtimeResponseCompleted,
    RealtimeResponseFailed,
    RealtimeSessionFailed,
    RealtimeSessionRequest,
    StructuredOutputResult,
    StructuredOutputSpec,
    TextDelta,
    TextResponse,
    UsageMetadata,
    UserTranscriptFinal,
    UserTranscriptPartial,
)
from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService

_OPENAI_PROVIDER_ID = "openai"
_OpenAIClientFactory = Callable[[str], Any]
_OPENAI_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
_OPENAI_PCM24K = {"type": "audio/pcm", "rate": 24_000}
_RETIRED_INTERACTION_LIMIT = 8


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

    async def open_realtime_session(
        self, *, model: ModelIdentity, request: RealtimeSessionRequest
    ) -> "OpenAIRealtimeProviderSession":
        """Open one disposable OpenAI WebSocket session for a Core session.

        The OpenAI SDK is deliberately configured without reconnect attempts. A
        lost native session is surfaced to the Core runtime, which owns the
        replacement and Conversation lifecycle.
        """

        self._require_openai_model(model)
        _require_pcm24k(request.input_audio_format)
        _require_pcm24k(request.output_audio_format)
        client = self._client()
        try:
            manager = client.realtime.connect(
                model=model.model_id,
                max_retries=0,
            )
            connection = await manager.enter()
            session = OpenAIRealtimeProviderSession(
                client=client,
                connection=connection,
                request=request,
            )
            await session.configure()
            return session
        except asyncio.CancelledError:
            await client.close()
            raise
        except _OPENAI_ERRORS as error:
            await client.close()
            raise _normalize_error(error) from error
        except Exception as error:
            await client.close()
            raise ProviderInvocationError(
                ProviderError(
                    ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                    "OpenAI realtime service is unavailable",
                    False,
                )
            ) from error

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


class OpenAIRealtimeProviderSession:
    """Disposable OpenAI Realtime transport normalized to Core realtime events.

    OpenAI item and response identifiers are intentionally kept only in this
    short-lived adapter object.  Core identifiers remain the only identifiers
    emitted to the runtime.
    """

    def __init__(
        self, *, client: Any, connection: Any, request: RealtimeSessionRequest
    ) -> None:
        self._client = client
        self._connection = connection
        self._request = request
        self._active_interaction_id: RealtimeInteractionId | None = None
        self._next_sequences: dict[RealtimeInteractionId, int] = {}
        self._pending_transcripts: deque[RealtimeInteractionId] = deque()
        self._pending_responses: deque[RealtimeInteractionId] = deque()
        self._item_interactions: dict[str, RealtimeInteractionId] = {}
        self._response_interactions: dict[str, RealtimeInteractionId] = {}
        self._retired_interactions: deque[RealtimeInteractionId] = deque()
        self._retired_interaction_set: set[RealtimeInteractionId] = set()
        self._closed = False

    async def configure(self) -> None:
        """Install manual-PTT PCM configuration and Core-built context."""

        instructions = "\n\n".join(
            message.text
            for message in self._request.context_seed.messages
            if message.role is AIMessageRole.SYSTEM
        )
        session: dict[str, object] = {
            "type": "realtime",
            "audio": {
                "input": {
                    "format": _OPENAI_PCM24K,
                    "transcription": {"model": _OPENAI_TRANSCRIPTION_MODEL},
                    "turn_detection": None,
                },
                "output": {"format": _OPENAI_PCM24K},
            },
            "output_modalities": ["audio"],
        }
        if instructions:
            session["instructions"] = instructions
        await self._connection.session.update(session=session)

        for message in self._request.context_seed.messages:
            if message.role is AIMessageRole.SYSTEM:
                continue
            await self._connection.conversation.item.create(
                item={
                    "type": "message",
                    "role": message.role.value,
                    "content": [{"type": "input_text", "text": message.text}],
                }
            )

    async def start_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        if self._closed:
            raise RuntimeError("OpenAI realtime session is closed")
        if self._active_interaction_id is not None:
            raise RuntimeError("OpenAI realtime interaction is already active")
        self._active_interaction_id = realtime_interaction_id
        self._next_sequences[realtime_interaction_id] = 0

    async def send_audio(self, *, frame: AudioInputFrame) -> None:
        if self._closed or self._active_interaction_id is None:
            raise RuntimeError("OpenAI realtime interaction is not active")
        await self._connection.input_audio_buffer.append(
            audio=base64.b64encode(frame.audio).decode("ascii")
        )

    async def commit_interaction(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        self._require_active(realtime_interaction_id)
        self._pending_transcripts.append(realtime_interaction_id)
        await self._connection.input_audio_buffer.commit()

    async def interrupt(
        self, *, realtime_interaction_id: RealtimeInteractionId
    ) -> None:
        if realtime_interaction_id in self._retired_interaction_set:
            return
        self._require_active(realtime_interaction_id)
        response_id = next(
            (
                provider_id
                for provider_id, interaction_id in self._response_interactions.items()
                if interaction_id == realtime_interaction_id
            ),
            None,
        )
        if response_id is None:
            await self._connection.response.cancel()
        else:
            await self._connection.response.cancel(response_id=response_id)
        self._retire(realtime_interaction_id)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._connection.close()
        await self._client.close()

    async def events(self) -> AsyncIterator[RealtimeProviderEvent]:
        try:
            async for event in self._connection:
                async for normalized in self._normalize_event(event):
                    yield normalized
        except asyncio.CancelledError:
            raise
        except _OPENAI_ERRORS:
            yield self._session_failed()
        except Exception:
            yield self._session_failed()

    async def _normalize_event(
        self, event: Any
    ) -> AsyncIterator[RealtimeProviderEvent]:
        event_type = getattr(event, "type", "")
        if event_type == "input_audio_buffer.committed":
            self._associate_item(getattr(event, "item_id", None))
            return
        if event_type == "conversation.item.input_audio_transcription.delta":
            interaction_id = self._interaction_for_item(getattr(event, "item_id", None))
            if interaction_id is not None:
                yield UserTranscriptPartial(
                    self._request.realtime_session_id,
                    interaction_id,
                    self._next_sequence(interaction_id),
                    _text(getattr(event, "delta", "")),
                )
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            interaction_id = self._interaction_for_item(getattr(event, "item_id", None))
            if interaction_id is None:
                return
            yield UserTranscriptFinal(
                self._request.realtime_session_id,
                interaction_id,
                self._next_sequence(interaction_id),
                _text(getattr(event, "transcript", "")),
            )
            self._discard_pending_transcript(interaction_id)
            self._pending_responses.append(interaction_id)
            try:
                await self._connection.response.create(
                    response={"output_modalities": ["audio"]}
                )
            except _OPENAI_ERRORS:
                yield self._response_failed(interaction_id)
                self._retire(interaction_id)
            return
        if event_type == "conversation.item.input_audio_transcription.failed":
            interaction_id = self._interaction_for_item(getattr(event, "item_id", None))
            if interaction_id is not None:
                yield self._response_failed(interaction_id)
                self._retire(interaction_id)
            return
        if event_type == "response.created":
            response = getattr(event, "response", None)
            response_id = getattr(response, "id", None)
            if isinstance(response_id, str) and self._pending_responses:
                self._response_interactions[response_id] = (
                    self._pending_responses.popleft()
                )
            return

        interaction_id = self._interaction_for_response(event)
        if interaction_id is None:
            if event_type == "error":
                active = self._active_interaction_id
                if active is None:
                    yield self._session_failed()
                elif active not in self._retired_interaction_set:
                    yield self._response_failed(active)
                    self._retire(active)
            return

        if event_type == "response.output_audio.delta":
            try:
                audio = base64.b64decode(getattr(event, "delta", ""), validate=True)
            except (TypeError, ValueError):
                yield self._response_failed(interaction_id)
                self._retire(interaction_id)
                return
            if audio:
                yield AssistantAudioChunk(
                    self._request.realtime_session_id,
                    interaction_id,
                    self._next_sequence(interaction_id),
                    audio,
                    self._request.output_audio_format,
                )
            return
        if event_type == "response.output_audio_transcript.delta":
            yield AssistantTranscriptPartial(
                self._request.realtime_session_id,
                interaction_id,
                self._next_sequence(interaction_id),
                _text(getattr(event, "delta", "")),
            )
            return
        if event_type == "response.output_audio_transcript.done":
            yield AssistantTranscriptFinal(
                self._request.realtime_session_id,
                interaction_id,
                self._next_sequence(interaction_id),
                _text(getattr(event, "transcript", "")),
            )
            return
        if event_type == "response.done":
            status = getattr(getattr(event, "response", None), "status", None)
            if status == "completed":
                yield RealtimeResponseCompleted(
                    self._request.realtime_session_id,
                    interaction_id,
                    self._next_sequence(interaction_id),
                )
            elif status != "cancelled":
                yield self._response_failed(interaction_id)
            self._retire(interaction_id)

    def _associate_item(self, provider_item_id: object) -> RealtimeInteractionId | None:
        if not isinstance(provider_item_id, str):
            return None
        if provider_item_id in self._item_interactions:
            return self._item_interactions[provider_item_id]
        if not self._pending_transcripts:
            return None
        interaction_id = self._pending_transcripts[0]
        self._item_interactions[provider_item_id] = interaction_id
        return interaction_id

    def _interaction_for_item(
        self, provider_item_id: object
    ) -> RealtimeInteractionId | None:
        interaction_id = self._associate_item(provider_item_id)
        if interaction_id is None or interaction_id in self._retired_interaction_set:
            return None
        return interaction_id

    def _interaction_for_response(self, event: Any) -> RealtimeInteractionId | None:
        response_id = getattr(event, "response_id", None)
        if not isinstance(response_id, str):
            response_id = getattr(getattr(event, "response", None), "id", None)
        if not isinstance(response_id, str):
            return None
        interaction_id = self._response_interactions.get(response_id)
        if interaction_id is None or interaction_id in self._retired_interaction_set:
            return None
        return interaction_id

    def _discard_pending_transcript(
        self, interaction_id: RealtimeInteractionId
    ) -> None:
        with contextlib.suppress(ValueError):
            self._pending_transcripts.remove(interaction_id)

    def _next_sequence(self, interaction_id: RealtimeInteractionId) -> int:
        sequence = self._next_sequences[interaction_id]
        self._next_sequences[interaction_id] = sequence + 1
        return sequence

    def _response_failed(
        self, interaction_id: RealtimeInteractionId
    ) -> RealtimeResponseFailed:
        return RealtimeResponseFailed(
            self._request.realtime_session_id,
            interaction_id,
            self._next_sequence(interaction_id),
            ProviderError(
                ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                "OpenAI realtime response failed",
                False,
            ),
        )

    def _session_failed(self) -> RealtimeSessionFailed:
        return RealtimeSessionFailed(
            self._request.realtime_session_id,
            0,
            ProviderError(
                ProviderErrorCategory.PROVIDER_UNAVAILABLE,
                "OpenAI realtime session failed",
                False,
            ),
        )

    def _retire(self, interaction_id: RealtimeInteractionId) -> None:
        if interaction_id in self._retired_interaction_set:
            return
        self._retired_interactions.append(interaction_id)
        self._retired_interaction_set.add(interaction_id)
        if self._active_interaction_id == interaction_id:
            self._active_interaction_id = None
        while len(self._retired_interactions) > _RETIRED_INTERACTION_LIMIT:
            self._retired_interaction_set.discard(self._retired_interactions.popleft())

    def _require_active(self, interaction_id: RealtimeInteractionId) -> None:
        if self._closed or self._active_interaction_id != interaction_id:
            raise RuntimeError("OpenAI realtime interaction is not active")


def _create_client(api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=api_key, max_retries=0, timeout=30.0)


def _require_pcm24k(audio_format: AudioFormat) -> None:
    if audio_format != AudioFormat(AudioEncoding.PCM16, 24_000, 1):
        raise ValueError("OpenAI Realtime requires PCM16 24 kHz mono audio")


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


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
