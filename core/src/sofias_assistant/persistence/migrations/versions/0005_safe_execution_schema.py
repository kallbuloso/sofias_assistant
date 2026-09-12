"""Add Gate I4 authorization, Tool and artifact persistence."""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0005_safe_execution_schema"
down_revision: str | None = "0004_add_voice_turn_input_modality"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid() -> Any:
    return sa.Uuid(as_uuid=True)


def _timestamp() -> Any:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "permission_grants",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("capability", sa.String(255), nullable=False),
        sa.Column("resource_scope", sa.Text(), nullable=False),
        sa.Column("constraints_json", sa.Text(), nullable=False),
        sa.Column("lifetime", sa.String(32), nullable=False),
        sa.Column("session_id", _uuid(), nullable=True),
        sa.Column("issued_at", _timestamp(), nullable=False),
        sa.Column("expires_at", _timestamp(), nullable=True),
        sa.Column("issuing_context_json", sa.Text(), nullable=False),
        sa.Column("remaining_uses", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("revoked_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "delegations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("resource_scope", sa.Text(), nullable=False),
        sa.Column("authority_scope", sa.Text(), nullable=False),
        sa.Column("constraints_json", sa.Text(), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("expires_at", _timestamp(), nullable=True),
        sa.Column("revoked_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "confirmation_requests",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("capability", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(255), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("tool_call_id", _uuid(), nullable=False),
        sa.Column("session_id", _uuid(), nullable=True),
        sa.Column("requested_lifetime", sa.String(32), nullable=False),
        sa.Column("constraints_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("resolved_at", _timestamp(), nullable=True),
        sa.Column("grant_id", _uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "policy_decisions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("request_id", _uuid(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("grant_id", _uuid(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("session_id", _uuid(), nullable=True),
        sa.Column("arguments_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("decision_id", _uuid(), nullable=True),
        sa.Column("confirmation_id", _uuid(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "artifacts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("retention", sa.String(32), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("expires_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("relative_path"),
    )


def downgrade() -> None:
    for table in (
        "artifacts",
        "tool_calls",
        "policy_decisions",
        "confirmation_requests",
        "delegations",
        "permission_grants",
    ):
        op.drop_table(table)
