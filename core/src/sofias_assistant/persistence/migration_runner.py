"""Programmatic Alembic boundary for the Operational Store."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_PATH = Path(__file__).with_name("migrations")


def upgrade_to_head(database_url: str) -> None:
    """Upgrade the explicitly selected Operational Store to head."""
    command.upgrade(_config_for(database_url), "head")


def downgrade_to_base(database_url: str) -> None:
    """Downgrade the explicitly selected Operational Store to base."""
    command.downgrade(_config_for(database_url), "base")


def _config_for(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.set_main_option("sqlalchemy.url", database_url)
    return config
