"""SQLAlchemy models for the Operational Store."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sofias_assistant.persistence.types import UTCDateTime


class Base(DeclarativeBase):
    """Base class for future Operational Store models."""


class RuntimeSessionStatus(StrEnum):
    """Lifecycle states persisted for a runtime session."""

    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    INTERRUPTED = "INTERRUPTED"


class RuntimeSession(Base):
    """Persistent marker for a single runtime process session."""

    __tablename__ = "runtime_sessions"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[RuntimeSessionStatus] = mapped_column(
        SqlEnum(
            RuntimeSessionStatus,
            name="runtime_session_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    application_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ApplicationSetting(Base):
    """Operational setting stored as serialized JSON text."""

    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
