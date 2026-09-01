"""Shared SQLAlchemy declarative metadata for the Operational Store."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for future Operational Store models."""
