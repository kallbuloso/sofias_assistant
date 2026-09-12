"""Add append-only structured execution audit evidence."""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0007_audit_traceability"
down_revision: str | None = "0006_task_agent_execution"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid() -> Any:
    return sa.Uuid(as_uuid=True)


def _timestamp() -> Any:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    for table in ("tool_calls", "tasks"):
        op.add_column(table, sa.Column("correlation_id", _uuid(), nullable=True))
        op.add_column(table, sa.Column("causation_id", _uuid(), nullable=True))
    op.add_column("task_attempts", sa.Column("correlation_id", _uuid(), nullable=True))
    op.add_column("task_attempts", sa.Column("causation_id", _uuid(), nullable=True))

    # Existing rows are assigned stable identities before tightening nullability.
    connection = op.get_bind()
    for table in ("tool_calls", "tasks", "task_attempts"):
        rows = connection.execute(
            sa.text(f"SELECT id FROM {table} WHERE correlation_id IS NULL")
        )
        for (row_id,) in rows:
            connection.execute(
                sa.text(f"UPDATE {table} SET correlation_id = :value WHERE id = :id"),
                {"value": row_id, "id": row_id},
            )
    with op.batch_alter_table("tool_calls") as batch:
        batch.alter_column("correlation_id", nullable=False)
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("correlation_id", nullable=False)

    op.create_table(
        "audit_entries",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("timestamp", _timestamp(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("origin", sa.String(64), nullable=False),
        sa.Column("correlation_id", _uuid(), nullable=False),
        sa.Column("causation_id", _uuid(), nullable=True),
        sa.Column("authority_context_json", sa.Text(), nullable=False),
        sa.Column("execution_context_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("conversation_id", _uuid(), nullable=True),
        sa.Column("turn_id", _uuid(), nullable=True),
        sa.Column("task_id", _uuid(), nullable=True),
        sa.Column("attempt_id", _uuid(), nullable=True),
        sa.Column("agent_run_id", _uuid(), nullable=True),
        sa.Column("tool_call_id", _uuid(), nullable=True),
        sa.Column("policy_decision_id", _uuid(), nullable=True),
        sa.Column("grant_id", _uuid(), nullable=True),
        sa.Column("delegation_id", _uuid(), nullable=True),
        sa.Column("confirmation_id", _uuid(), nullable=True),
        sa.Column("artifact_id", _uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_entries_correlation_id", "audit_entries", ["correlation_id"]
    )
    op.create_index("ix_audit_entries_task_id", "audit_entries", ["task_id"])
    op.create_index("ix_audit_entries_timestamp", "audit_entries", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_audit_entries_timestamp", table_name="audit_entries")
    op.drop_index("ix_audit_entries_task_id", table_name="audit_entries")
    op.drop_index("ix_audit_entries_correlation_id", table_name="audit_entries")
    op.drop_table("audit_entries")
    with op.batch_alter_table("task_attempts") as batch:
        batch.drop_column("causation_id")
        batch.drop_column("correlation_id")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("causation_id")
        batch.drop_column("correlation_id")
    with op.batch_alter_table("tool_calls") as batch:
        batch.drop_column("causation_id")
        batch.drop_column("correlation_id")
