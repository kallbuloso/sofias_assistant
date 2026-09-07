"""Add conservative cloud context eligibility to durable turns.

Revision ID: 0003_turn_cloud_context_eligibility
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_turn_cloud_context_eligibility"
down_revision: str | None = "0002_conversation_operational_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "turns",
        sa.Column(
            "cloud_context_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("turns", "cloud_context_eligible")
