"""Immutable, provider-independent conversation domain snapshots."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class TurnStatus(StrEnum):
    """Explicit lifecycle states for one Core-owned conversation turn."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class TurnInputModality(StrEnum):
    """Input modalities supported by the durable turn contract."""

    TEXT = "TEXT"


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{field_name} must be a UUID")


def _require_non_blank(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class Conversation:
    """A Core-owned durable operational conversation."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        created_at = _normalize_utc(self.created_at, "created_at")
        updated_at = _normalize_utc(self.updated_at, "updated_at")
        if updated_at < created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)


@dataclass(frozen=True, slots=True)
class Turn:
    """A durable, ordered unit of text interaction within a Conversation."""

    id: UUID
    conversation_id: UUID
    sequence: int
    status: TurnStatus
    input_modality: TurnInputModality
    user_text: str
    assistant_text: str | None
    ai_request_id: UUID | None
    provider_id: str | None
    model_id: str | None
    provider_request_id: str | None
    provider_session_id: str | None
    error_category: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "id")
        _require_uuid(self.conversation_id, "conversation_id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence must be an integer greater than or equal to one")
        if self.sequence < 1:
            raise ValueError("sequence must be an integer greater than or equal to one")
        if not isinstance(self.status, TurnStatus):
            raise ValueError("status must be a TurnStatus")
        if not isinstance(self.input_modality, TurnInputModality):
            raise ValueError("input_modality must be a TurnInputModality")
        _require_non_blank(self.user_text, "user_text")
        if self.assistant_text is not None and not isinstance(self.assistant_text, str):
            raise ValueError("assistant_text must be a string or None")
        if self.ai_request_id is not None:
            _require_uuid(self.ai_request_id, "ai_request_id")
        self._validate_provider_correlation()
        self._validate_state_fields()

        created_at = _normalize_utc(self.created_at, "created_at")
        updated_at = _normalize_utc(self.updated_at, "updated_at")
        finished_at = (
            _normalize_utc(self.finished_at, "finished_at")
            if self.finished_at is not None
            else None
        )
        if updated_at < created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        if finished_at is not None:
            if finished_at < created_at:
                raise ValueError("finished_at must not be earlier than created_at")
            if updated_at < finished_at:
                raise ValueError("updated_at must not be earlier than finished_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "finished_at", finished_at)

    def complete(
        self,
        *,
        assistant_text: str,
        updated_at: datetime,
        finished_at: datetime,
        ai_request_id: UUID | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        provider_request_id: str | None = None,
        provider_session_id: str | None = None,
    ) -> "Turn":
        """Return a completed snapshot from a processing turn."""
        self._require_processing_transition()
        return replace(
            self,
            status=TurnStatus.COMPLETED,
            assistant_text=assistant_text,
            ai_request_id=ai_request_id,
            provider_id=provider_id,
            model_id=model_id,
            provider_request_id=provider_request_id,
            provider_session_id=provider_session_id,
            error_category=None,
            error_message=None,
            updated_at=updated_at,
            finished_at=finished_at,
        )

    def interrupt(
        self,
        *,
        assistant_text: str | None,
        updated_at: datetime,
        finished_at: datetime,
    ) -> "Turn":
        """Return an interrupted snapshot from a processing turn."""
        self._require_processing_transition()
        return replace(
            self,
            status=TurnStatus.INTERRUPTED,
            assistant_text=assistant_text,
            error_category=None,
            error_message=None,
            updated_at=updated_at,
            finished_at=finished_at,
        )

    def fail(
        self,
        *,
        error_message: str,
        error_category: str | None,
        assistant_text: str | None,
        updated_at: datetime,
        finished_at: datetime,
    ) -> "Turn":
        """Return a failed snapshot from a processing turn."""
        self._require_processing_transition()
        return replace(
            self,
            status=TurnStatus.FAILED,
            assistant_text=assistant_text,
            error_category=error_category,
            error_message=error_message,
            updated_at=updated_at,
            finished_at=finished_at,
        )

    def _validate_provider_correlation(self) -> None:
        provider_and_model = (self.provider_id, self.model_id)
        if provider_and_model == (None, None):
            if (
                self.provider_request_id is not None
                or self.provider_session_id is not None
            ):
                raise ValueError(
                    "provider request and session IDs require provider_id and model_id"
                )
            return
        if self.provider_id is None or self.model_id is None:
            raise ValueError("provider_id and model_id must be provided together")
        _require_non_blank(self.provider_id, "provider_id")
        _require_non_blank(self.model_id, "model_id")
        if self.provider_request_id is not None:
            _require_non_blank(self.provider_request_id, "provider_request_id")
        if self.provider_session_id is not None:
            _require_non_blank(self.provider_session_id, "provider_session_id")

    def _validate_state_fields(self) -> None:
        if self.status is TurnStatus.PROCESSING:
            if self.assistant_text is not None or self.finished_at is not None:
                raise ValueError(
                    "a processing turn has no assistant text or finished_at"
                )
            if self.error_category is not None or self.error_message is not None:
                raise ValueError("a processing turn has no error fields")
            return
        if self.finished_at is None:
            raise ValueError("a terminal turn requires finished_at")
        if self.status in (TurnStatus.COMPLETED, TurnStatus.INTERRUPTED):
            if self.status is TurnStatus.COMPLETED and not isinstance(
                self.assistant_text, str
            ):
                raise ValueError("a completed turn requires assistant_text")
            if self.error_category is not None or self.error_message is not None:
                raise ValueError("completed and interrupted turns have no error fields")
            return
        if self.status is TurnStatus.FAILED:
            if self.error_message is None:
                raise ValueError("error_message must not be blank")
            _require_non_blank(self.error_message, "error_message")
            if self.error_category is not None:
                _require_non_blank(self.error_category, "error_category")

    def _require_processing_transition(self) -> None:
        if self.status is not TurnStatus.PROCESSING:
            raise ValueError(
                "only a processing turn can transition to a terminal state"
            )
