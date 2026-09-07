"""In-process ASGI contract for the future loopback local client boundary."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal, Protocol, assert_never
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from sofias_assistant.ai.contracts import DataLocality, ModelIdentity
from sofias_assistant.client_boundary.auth import LocalClientAuthenticator
from sofias_assistant.client_boundary.sessions import (
    ClientSession,
    ClientSessionRegistry,
)
from sofias_assistant.conversation.events import (
    ConversationStreamEvent,
    ConversationTextDelta,
    ConversationToolCallProposed,
    ConversationTurnCompleted,
    ConversationTurnFailed,
    ConversationTurnInterrupted,
    ConversationTurnStarted,
    ConversationUsageUpdated,
)
from sofias_assistant.conversation.models import Conversation, Turn
from sofias_assistant.conversation.runtime import (
    ConversationNotFoundError,
    ConversationState,
    SendTextCommand,
)
from sofias_assistant.core.core import CoreState
from sofias_assistant.health.models import (
    ComponentHealth,
    HealthStatus,
    RuntimeHealthSnapshot,
)
from sofias_assistant.secrets.models import SecretValue

_AUTHENTICATION_FAILURE_DETAIL = "Local client authentication failed"


class ClientSessionResponse(BaseModel):
    """HTTP representation of a local client session without credentials."""

    id: UUID
    created_at: datetime

    @classmethod
    def from_session(cls, session: ClientSession) -> "ClientSessionResponse":
        """Create the transport representation for a runtime session."""

        return cls(id=session.id, created_at=session.created_at)


class CoreReadApi(Protocol):
    """Minimal read-only Core contract exposed by the local HTTP adapter."""

    @property
    def state(self) -> CoreState: ...

    @property
    def runtime_session_id(self) -> UUID | None: ...

    @property
    def health(self) -> RuntimeHealthSnapshot: ...


class ConversationHttpApi(Protocol):
    """Minimal Core-owned Conversation API used by the local HTTP adapter."""

    async def create_conversation(self) -> Conversation: ...

    async def get_conversation_state(
        self, conversation_id: UUID
    ) -> ConversationState: ...

    def stream_text(
        self, command: SendTextCommand
    ) -> AsyncIterator[ConversationStreamEvent]: ...


class ComponentHealthResponse(BaseModel):
    """Transport-only representation of one Core health component."""

    name: str
    status: HealthStatus
    detail: str | None

    @classmethod
    def from_component(cls, component: ComponentHealth) -> "ComponentHealthResponse":
        """Create the transport representation while preserving component fields."""

        return cls(
            name=component.name,
            status=component.status,
            detail=component.detail,
        )


class RuntimeHealthResponse(BaseModel):
    """Transport-only representation of the ordered Core health snapshot."""

    status: HealthStatus
    components: list[ComponentHealthResponse]

    @classmethod
    def from_snapshot(cls, snapshot: RuntimeHealthSnapshot) -> "RuntimeHealthResponse":
        """Create an ordered transport health response from the Core snapshot."""

        return cls(
            status=snapshot.status,
            components=[
                ComponentHealthResponse.from_component(component)
                for component in snapshot.components
            ],
        )


class CoreResponse(BaseModel):
    """Transport-safe read-only snapshot of the Core runtime."""

    state: CoreState
    runtime_session_id: UUID | None
    health: RuntimeHealthResponse

    @classmethod
    def from_core(cls, core: CoreReadApi) -> "CoreResponse":
        """Create a response without exposing Core resources or configuration."""

        return cls(
            state=core.state,
            runtime_session_id=core.runtime_session_id,
            health=RuntimeHealthResponse.from_snapshot(core.health),
        )


class ModelOverrideRequest(BaseModel):
    """Transport-only explicit provider/model selection request."""

    provider_id: str
    model_id: str

    @field_validator("provider_id", "model_id")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model identity fields must not be blank")
        return value

    def to_model_identity(self) -> ModelIdentity:
        """Map the validated wire identity to the Core-owned contract."""

        return ModelIdentity(provider_id=self.provider_id, model_id=self.model_id)


class TextTurnRequest(BaseModel):
    """Transport-only input for one streamed textual Turn."""

    text: str
    locality: DataLocality
    cloud_context_eligible: bool
    model_override: ModelOverrideRequest | None = None

    @field_validator("text")
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value

    def to_command(self, conversation_id: UUID) -> SendTextCommand:
        """Map the validated transport request to the application command."""

        return SendTextCommand(
            conversation_id=conversation_id,
            text=self.text,
            locality=self.locality,
            cloud_context_eligible=self.cloud_context_eligible,
            model_override=(
                self.model_override.to_model_identity()
                if self.model_override is not None
                else None
            ),
        )


class ConversationResponse(BaseModel):
    """Transport-safe representation of one Core-owned Conversation."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_conversation(cls, conversation: Conversation) -> "ConversationResponse":
        """Map a domain snapshot explicitly."""

        return cls(
            id=conversation.id,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class TurnResponse(BaseModel):
    """Transport-safe durable Turn state without provider operational IDs."""

    id: UUID
    conversation_id: UUID
    sequence: int
    status: str
    input_modality: str
    cloud_context_eligible: bool
    user_text: str
    assistant_text: str | None
    ai_request_id: UUID | None
    provider_id: str | None
    model_id: str | None
    error_category: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    @classmethod
    def from_turn(cls, turn: Turn) -> "TurnResponse":
        """Map only the client-safe durable fields explicitly."""

        return cls(
            id=turn.id,
            conversation_id=turn.conversation_id,
            sequence=turn.sequence,
            status=turn.status,
            input_modality=turn.input_modality,
            cloud_context_eligible=turn.cloud_context_eligible,
            user_text=turn.user_text,
            assistant_text=turn.assistant_text,
            ai_request_id=turn.ai_request_id,
            provider_id=turn.provider_id,
            model_id=turn.model_id,
            error_category=turn.error_category,
            error_message=turn.error_message,
            created_at=turn.created_at,
            updated_at=turn.updated_at,
            finished_at=turn.finished_at,
        )


class ConversationStateResponse(BaseModel):
    """Ordered read representation for a Conversation and all durable Turns."""

    conversation: ConversationResponse
    turns: list[TurnResponse]

    @classmethod
    def from_state(cls, state: ConversationState) -> "ConversationStateResponse":
        """Map the Core-owned state snapshot without ORM serialization."""

        return cls(
            conversation=ConversationResponse.from_conversation(state.conversation),
            turns=[TurnResponse.from_turn(turn) for turn in state.turns],
        )


class ModelResponse(BaseModel):
    """Transport model identity for normalized Conversation events."""

    provider_id: str
    model_id: str

    @classmethod
    def from_identity(cls, model: ModelIdentity) -> "ModelResponse":
        """Map a provider-independent selected model identity."""

        return cls(provider_id=model.provider_id, model_id=model.model_id)


class UsageResponse(BaseModel):
    """Transport-only normalized usage metadata."""

    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


class ToolCallProposalResponse(BaseModel):
    """An inert normalized ToolCall proposal on the transport boundary."""

    call_id: str
    name: str
    arguments: object


class TurnStartedRecord(BaseModel):
    type: Literal["turn_started"] = "turn_started"
    conversation: ConversationResponse
    turn: TurnResponse


class TextDeltaRecord(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    conversation_id: UUID
    turn_id: UUID
    ai_request_id: UUID
    model: ModelResponse
    text: str


class UsageUpdatedRecord(BaseModel):
    type: Literal["usage_updated"] = "usage_updated"
    conversation_id: UUID
    turn_id: UUID
    ai_request_id: UUID
    model: ModelResponse
    usage: UsageResponse


class ToolCallProposedRecord(BaseModel):
    type: Literal["tool_call_proposed"] = "tool_call_proposed"
    conversation_id: UUID
    turn_id: UUID
    ai_request_id: UUID
    model: ModelResponse
    proposal: ToolCallProposalResponse


class TurnCompletedRecord(BaseModel):
    type: Literal["turn_completed"] = "turn_completed"
    conversation: ConversationResponse
    turn: TurnResponse
    usage: UsageResponse | None


class TurnFailedRecord(BaseModel):
    type: Literal["turn_failed"] = "turn_failed"
    conversation: ConversationResponse
    turn: TurnResponse


class TurnInterruptedRecord(BaseModel):
    type: Literal["turn_interrupted"] = "turn_interrupted"
    conversation: ConversationResponse
    turn: TurnResponse


type ConversationEventRecord = (
    TurnStartedRecord
    | TextDeltaRecord
    | UsageUpdatedRecord
    | ToolCallProposedRecord
    | TurnCompletedRecord
    | TurnFailedRecord
    | TurnInterruptedRecord
)


def create_local_http_app(
    authenticator: LocalClientAuthenticator,
    sessions: ClientSessionRegistry,
    *,
    core: CoreReadApi | None = None,
    conversation: ConversationHttpApi | None = None,
) -> FastAPI:
    """Create an unbound ASGI app for one explicitly composed local boundary."""

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def require_bearer(
        authorization: Annotated[str | None, Header()] = None,
    ) -> SecretValue:
        credential = _credential_from_authorization(authorization)
        if credential is None or not authenticator.authenticate(credential):
            raise _authentication_failure()
        return credential

    async def require_session(
        _: Annotated[SecretValue, Depends(require_bearer)],
        session_id: Annotated[
            str | None, Header(alias="X-Sofia-Client-Session-ID")
        ] = None,
    ) -> ClientSession:
        if session_id is None:
            raise _authentication_failure()
        try:
            parsed_session_id = UUID(session_id)
        except ValueError:
            raise _authentication_failure() from None

        session = sessions.get(parsed_session_id)
        if session is None:
            raise _authentication_failure()
        return session

    @app.post(
        "/api/v1/client-sessions",
        response_model=ClientSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def open_session(
        credential: Annotated[SecretValue, Depends(require_bearer)],
    ) -> ClientSessionResponse:
        """Open a runtime session after authenticating the bearer credential."""

        return ClientSessionResponse.from_session(sessions.open_session(credential))

    @app.get("/api/v1/client-session", response_model=ClientSessionResponse)
    async def get_current_session(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> ClientSessionResponse:
        """Return the session associated with both required authentication headers."""

        return ClientSessionResponse.from_session(session)

    @app.delete("/api/v1/client-session", status_code=status.HTTP_204_NO_CONTENT)
    async def close_current_session(
        session: Annotated[ClientSession, Depends(require_session)],
    ) -> Response:
        """Close only the session associated with the authenticated request."""

        sessions.close_session(session.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if core is not None:

        @app.get("/api/v1/core", response_model=CoreResponse)
        async def get_core(
            _: Annotated[ClientSession, Depends(require_session)],
        ) -> CoreResponse:
            """Return the authenticated, transport-safe Core runtime snapshot."""

            return CoreResponse.from_core(core)

    if conversation is not None:

        @app.post(
            "/api/v1/conversations",
            response_model=ConversationResponse,
            status_code=status.HTTP_201_CREATED,
        )
        async def create_conversation(
            _: Annotated[ClientSession, Depends(require_session)],
        ) -> ConversationResponse:
            """Create one authenticated Core-owned Conversation."""

            return ConversationResponse.from_conversation(
                await conversation.create_conversation()
            )

        @app.get(
            "/api/v1/conversations/{conversation_id}",
            response_model=ConversationStateResponse,
        )
        async def get_conversation(
            conversation_id: UUID,
            _: Annotated[ClientSession, Depends(require_session)],
        ) -> ConversationStateResponse:
            """Return authenticated, durable Conversation state."""

            try:
                state_snapshot = await conversation.get_conversation_state(
                    conversation_id
                )
            except ConversationNotFoundError:
                raise _conversation_not_found() from None
            return ConversationStateResponse.from_state(state_snapshot)

        @app.post("/api/v1/conversations/{conversation_id}/turns")
        async def stream_turn(
            conversation_id: UUID,
            request: TextTurnRequest,
            _: Annotated[ClientSession, Depends(require_session)],
        ) -> StreamingResponse:
            """Stream one authenticated text Turn as ordered NDJSON records."""

            try:
                await conversation.get_conversation_state(conversation_id)
            except ConversationNotFoundError:
                raise _conversation_not_found() from None
            return StreamingResponse(
                _ndjson_records(
                    conversation.stream_text(request.to_command(conversation_id))
                ),
                media_type="application/x-ndjson",
            )

    return app


async def _ndjson_records(
    events: AsyncIterator[ConversationStreamEvent],
) -> AsyncIterator[str]:
    """Translate Core stream events to one explicit JSON object per line."""

    async for event in events:
        yield _conversation_event_to_record(event).model_dump_json() + "\n"


def _conversation_event_to_record(
    event: ConversationStreamEvent,
) -> ConversationEventRecord:
    """Exhaustively map Core events without serializing internal dataclasses."""

    if isinstance(event, ConversationTurnStarted):
        return TurnStartedRecord(
            conversation=ConversationResponse.from_conversation(event.conversation),
            turn=TurnResponse.from_turn(event.turn),
        )
    if isinstance(event, ConversationTextDelta):
        return TextDeltaRecord(
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            ai_request_id=event.ai_request_id,
            model=ModelResponse.from_identity(event.model),
            text=event.text,
        )
    if isinstance(event, ConversationUsageUpdated):
        return UsageUpdatedRecord(
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            ai_request_id=event.ai_request_id,
            model=ModelResponse.from_identity(event.model),
            usage=UsageResponse(
                input_tokens=event.usage.input_tokens,
                output_tokens=event.usage.output_tokens,
                cached_tokens=event.usage.cached_tokens,
            ),
        )
    if isinstance(event, ConversationToolCallProposed):
        return ToolCallProposedRecord(
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            ai_request_id=event.ai_request_id,
            model=ModelResponse.from_identity(event.model),
            proposal=ToolCallProposalResponse(
                call_id=event.proposal.call_id,
                name=event.proposal.name,
                arguments=event.proposal.arguments,
            ),
        )
    if isinstance(event, ConversationTurnCompleted):
        return TurnCompletedRecord(
            conversation=ConversationResponse.from_conversation(event.conversation),
            turn=TurnResponse.from_turn(event.turn),
            usage=(
                UsageResponse(
                    input_tokens=event.usage.input_tokens,
                    output_tokens=event.usage.output_tokens,
                    cached_tokens=event.usage.cached_tokens,
                )
                if event.usage is not None
                else None
            ),
        )
    if isinstance(event, ConversationTurnFailed):
        return TurnFailedRecord(
            conversation=ConversationResponse.from_conversation(event.conversation),
            turn=TurnResponse.from_turn(event.turn),
        )
    if isinstance(event, ConversationTurnInterrupted):
        return TurnInterruptedRecord(
            conversation=ConversationResponse.from_conversation(event.conversation),
            turn=TurnResponse.from_turn(event.turn),
        )
    assert_never(event)


def _credential_from_authorization(authorization: str | None) -> SecretValue | None:
    if authorization is None:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if scheme != "Bearer" or not separator or not credential.strip():
        return None
    if credential != credential.strip() or " " in credential:
        return None
    return SecretValue(credential)


def _authentication_failure() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTHENTICATION_FAILURE_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _conversation_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Conversation not found",
    )
