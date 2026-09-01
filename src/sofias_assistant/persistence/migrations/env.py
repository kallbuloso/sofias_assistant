"""Alembic environment for the Operational Store."""

from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from sofias_assistant.persistence.database import create_async_engine
from sofias_assistant.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    database_url = config.get_main_option("sqlalchemy.url")
    if database_url is None:
        raise RuntimeError("Alembic requires an explicit database URL")

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    run(run_async_migrations())
