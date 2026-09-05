"""Add durable Core-owned conversations and turns.

Revision ID: 0002_conversation_operational_schema
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_conversation_operational_schema"
down_revision: str | None = "0001_initial_operational_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    turn_status = sa.Enum(
        "PROCESSING",
        "COMPLETED",
        "INTERRUPTED",
        "FAILED",
        name="turn_status",
        native_enum=False,
        create_constraint=True,
    )
    turn_input_modality = sa.Enum(
        "TEXT",
        name="turn_input_modality",
        native_enum=False,
        create_constraint=True,
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", turn_status, nullable=False),
        sa.Column("input_modality", turn_input_modality, nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_text", sa.Text(), nullable=True),
        sa.Column("ai_request_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("provider_id", sa.String(length=255), nullable=True),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("provider_session_id", sa.String(length=255), nullable=True),
        sa.Column("error_category", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("sequence >= 1", name="ck_turns_sequence_at_least_one"),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_turns_conversation_sequence"
        ),
    )


def downgrade() -> None:
    op.drop_table("turns")
    op.drop_table("conversations")
