"""Domain-oriented repositories for the Operational Store."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sofias_assistant.persistence.models import (
    ApplicationSetting,
    RuntimeSession,
    RuntimeSessionStatus,
)


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
