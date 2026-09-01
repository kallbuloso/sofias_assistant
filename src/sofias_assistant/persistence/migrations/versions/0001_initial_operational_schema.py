"""Initial Operational Store schema.

Revision ID: 0001_initial_operational_schema
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_operational_schema"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    status = sa.Enum(
        "RUNNING",
        "STOPPED",
        "INTERRUPTED",
        name="runtime_session_status",
        native_enum=False,
        create_constraint=True,
    )
    op.create_table(
        "runtime_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("status", status, nullable=False),
        sa.Column("application_version", sa.String(length=64), nullable=False),
    )
    op.create_table(
        "application_settings",
        sa.Column("key", sa.String(length=255), primary_key=True),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("application_settings")
    op.drop_table("runtime_sessions")
