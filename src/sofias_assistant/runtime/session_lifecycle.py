"""Persistent lifecycle transitions for the current runtime session."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.persistence.models import RuntimeSession, RuntimeSessionStatus
from sofias_assistant.persistence.unit_of_work import SqlAlchemyUnitOfWork


class RuntimeSessionLifecycle:
    """Recover prior running sessions and persist one current runtime session."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        application_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not application_version.strip():
            raise ValueError("Application version must not be blank")

        self._session_factory = session_factory
        self._application_version = application_version
        self._clock = clock or _utc_now
        self._active_session_id: UUID | None = None

    @property
    def active_session_id(self) -> UUID | None:
        """Return the current session identity after a successful start."""

        return self._active_session_id

    async def start(self) -> RuntimeSession:
        """Recover previous running sessions and create one current session."""

        if self._active_session_id is not None:
            raise RuntimeError("Runtime session lifecycle has already started")

        started_at = self._current_utc_time()
        current_session = RuntimeSession(
            started_at=started_at,
            status=RuntimeSessionStatus.RUNNING,
            application_version=self._application_version,
        )
        async with SqlAlchemyUnitOfWork(self._session_factory) as unit_of_work:
            previous_running_sessions = (
                await unit_of_work.runtime_sessions.list_by_status(
                    RuntimeSessionStatus.RUNNING
                )
            )
            for previous_session in previous_running_sessions:
                previous_session.status = RuntimeSessionStatus.INTERRUPTED
                previous_session.stopped_at = None

            unit_of_work.runtime_sessions.add(current_session)
            await unit_of_work.commit()
            self._active_session_id = current_session.id
        return current_session

    async def stop(self) -> RuntimeSession:
        """Persist a clean stop for the current runtime session."""

        if self._active_session_id is None:
            raise RuntimeError("Runtime session lifecycle has not started")

        stopped_at = self._current_utc_time()
        active_session_id = self._active_session_id
        async with SqlAlchemyUnitOfWork(self._session_factory) as unit_of_work:
            current_session = await unit_of_work.runtime_sessions.get_by_id(
                active_session_id
            )
            if current_session is None:
                raise RuntimeError("Current runtime session was not found")
            if current_session.status is not RuntimeSessionStatus.RUNNING:
                raise RuntimeError("Current runtime session is not running")

            current_session.status = RuntimeSessionStatus.STOPPED
            current_session.stopped_at = stopped_at
            await unit_of_work.commit()
            self._active_session_id = None
        return current_session

    def _current_utc_time(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(
                "Runtime session clock must return a timezone-aware datetime"
            )
        return timestamp.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
