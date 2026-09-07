"""Domain-oriented repositories for the Operational Store."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sofias_assistant.conversation.models import Conversation, Turn
from sofias_assistant.persistence.models import (
    ApplicationSetting,
    ConversationRecord,
    RuntimeSession,
    RuntimeSessionStatus,
    TurnRecord,
)


class RepositoryEntityNotFoundError(RuntimeError):
    """Raised when save is requested for an entity absent from the store."""


class RuntimeSessionRepository:
    """Persistence operations for runtime session records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, runtime_session: RuntimeSession) -> None:
        self._session.add(runtime_session)

    async def get_by_id(self, runtime_session_id: UUID) -> RuntimeSession | None:
        return await self._session.get(RuntimeSession, runtime_session_id)

    async def list_by_status(
        self, status: RuntimeSessionStatus
    ) -> list[RuntimeSession]:
        result = await self._session.scalars(
            select(RuntimeSession).where(RuntimeSession.status == status)
        )
        return list(result)


class ApplicationSettingRepository:
    """Persistence operations for application setting records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, application_setting: ApplicationSetting) -> None:
        self._session.add(application_setting)

    async def get_by_key(self, key: str) -> ApplicationSetting | None:
        return await self._session.get(ApplicationSetting, key)


class ConversationRepository:
    """Explicit persistence mapping for Core-owned Conversation snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, conversation: Conversation) -> None:
        self._session.add(_conversation_to_record(conversation))

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        record = await self._session.get(ConversationRecord, conversation_id)
        return _conversation_from_record(record) if record is not None else None

    async def save(self, conversation: Conversation) -> None:
        record = await self._session.get(ConversationRecord, conversation.id)
        if record is None:
            raise RepositoryEntityNotFoundError("Conversation does not exist")
        record.created_at = conversation.created_at
        record.updated_at = conversation.updated_at


class TurnRepository:
    """Explicit persistence mapping for ordered Core-owned Turn snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, turn: Turn) -> None:
        self._session.add(_turn_to_record(turn))

    async def get_by_id(self, turn_id: UUID) -> Turn | None:
        record = await self._session.get(TurnRecord, turn_id)
        return _turn_from_record(record) if record is not None else None

    async def list_for_conversation(self, conversation_id: UUID) -> list[Turn]:
        records = await self._session.scalars(
            select(TurnRecord)
            .where(TurnRecord.conversation_id == conversation_id)
            .order_by(TurnRecord.sequence.asc())
        )
        return [_turn_from_record(record) for record in records]

    async def next_sequence(self, conversation_id: UUID) -> int:
        """Return max(sequence) + 1; runtime serialization remains a later concern."""
        maximum = await self._session.scalar(
            select(func.max(TurnRecord.sequence)).where(
                TurnRecord.conversation_id == conversation_id
            )
        )
        return 1 if maximum is None else int(maximum) + 1

    async def save(self, turn: Turn) -> None:
        record = await self._session.get(TurnRecord, turn.id)
        if record is None:
            raise RepositoryEntityNotFoundError("Turn does not exist")
        _copy_turn_to_record(turn, record)


def _conversation_to_record(conversation: Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _conversation_from_record(record: ConversationRecord) -> Conversation:
    return Conversation(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _turn_to_record(turn: Turn) -> TurnRecord:
    record = TurnRecord(id=turn.id, conversation_id=turn.conversation_id)
    _copy_turn_to_record(turn, record)
    return record


def _copy_turn_to_record(turn: Turn, record: TurnRecord) -> None:
    record.conversation_id = turn.conversation_id
    record.sequence = turn.sequence
    record.status = turn.status
    record.input_modality = turn.input_modality
    record.cloud_context_eligible = turn.cloud_context_eligible
    record.user_text = turn.user_text
    record.assistant_text = turn.assistant_text
    record.ai_request_id = turn.ai_request_id
    record.provider_id = turn.provider_id
    record.model_id = turn.model_id
    record.provider_request_id = turn.provider_request_id
    record.provider_session_id = turn.provider_session_id
    record.error_category = turn.error_category
    record.error_message = turn.error_message
    record.created_at = turn.created_at
    record.updated_at = turn.updated_at
    record.finished_at = turn.finished_at


def _turn_from_record(record: TurnRecord) -> Turn:
    return Turn(
        id=record.id,
        conversation_id=record.conversation_id,
        sequence=record.sequence,
        status=record.status,
        input_modality=record.input_modality,
        cloud_context_eligible=record.cloud_context_eligible,
        user_text=record.user_text,
        assistant_text=record.assistant_text,
        ai_request_id=record.ai_request_id,
        provider_id=record.provider_id,
        model_id=record.model_id,
        provider_request_id=record.provider_request_id,
        provider_session_id=record.provider_session_id,
        error_category=record.error_category,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
        finished_at=record.finished_at,
    )
