"""Explicit transaction boundary for Operational Store writes."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sofias_assistant.persistence.repositories import (
    ApplicationSettingRepository,
    ConversationRepository,
    RuntimeSessionRepository,
    TurnRepository,
)


class SqlAlchemyUnitOfWork:
    """Own one AsyncSession and its domain repositories per async context."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._runtime_sessions: RuntimeSessionRepository | None = None
        self._application_settings: ApplicationSettingRepository | None = None
        self._conversations: ConversationRepository | None = None
        self._turns: TurnRepository | None = None

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self._runtime_sessions = RuntimeSessionRepository(self._session)
        self._application_settings = ApplicationSettingRepository(self._session)
        self._conversations = ConversationRepository(self._session)
        self._turns = TurnRepository(self._session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        session = self.session
        try:
            await session.rollback()
        finally:
            try:
                await session.close()
            finally:
                self._session = None
                self._runtime_sessions = None
                self._application_settings = None
                self._conversations = None
                self._turns = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork is only available inside an async context")
        return self._session

    @property
    def runtime_sessions(self) -> RuntimeSessionRepository:
        if self._runtime_sessions is None:
            raise RuntimeError("UnitOfWork is only available inside an async context")
        return self._runtime_sessions

    @property
    def application_settings(self) -> ApplicationSettingRepository:
        if self._application_settings is None:
            raise RuntimeError("UnitOfWork is only available inside an async context")
        return self._application_settings

    @property
    def conversations(self) -> ConversationRepository:
        if self._conversations is None:
            raise RuntimeError("UnitOfWork is only available inside an async context")
        return self._conversations

    @property
    def turns(self) -> TurnRepository:
        if self._turns is None:
            raise RuntimeError("UnitOfWork is only available inside an async context")
        return self._turns

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def flush(self) -> None:
        await self.session.flush()
