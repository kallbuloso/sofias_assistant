"""Add durable Task and Agent execution lifecycle tables."""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0006_task_agent_execution"
down_revision: str | None = "0005_safe_execution_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid() -> Any:
    return sa.Uuid(as_uuid=True)


def _timestamp() -> Any:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("authority_json", sa.Text(), nullable=False),
        sa.Column("conversation_id", _uuid(), nullable=True),
        sa.Column("delegation_id", _uuid(), nullable=True),
        sa.Column("execution_strategy", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("claimed_by", sa.String(255), nullable=True),
        sa.Column("claim_expires_at", _timestamp(), nullable=True),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("updated_at", _timestamp(), nullable=False),
        sa.Column("started_at", _timestamp(), nullable=True),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task_attempts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("task_id", _uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tool_call_id", _uuid(), nullable=True),
        sa.Column("execution_mode", sa.String(32), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", _timestamp(), nullable=True),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(("task_id",), ("tasks.id",), ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "attempt_number"),
    )
    op.create_table(
        "agent_definitions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_capabilities_json", sa.Text(), nullable=False),
        sa.Column("allowed_tools_json", sa.Text(), nullable=False),
        sa.Column("context_policy", sa.String(128), nullable=False),
        sa.Column("provider_requirements_json", sa.Text(), nullable=False),
        sa.Column("runtime_limits_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("task_id", _uuid(), nullable=False),
        sa.Column("agent_definition_id", _uuid(), nullable=False),
        sa.Column("agent_definition_version", sa.String(64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("delegated_context_json", sa.Text(), nullable=False),
        sa.Column("authority_scope", sa.Text(), nullable=False),
        sa.Column("allowed_tools_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=True),
        sa.Column("provider_requirements_json", sa.Text(), nullable=False),
        sa.Column("runtime_limits_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("correlation_id", _uuid(), nullable=False),
        sa.Column("created_at", _timestamp(), nullable=False),
        sa.Column("started_at", _timestamp(), nullable=True),
        sa.Column("finished_at", _timestamp(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(("task_id",), ("tasks.id",), ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("agent_runs")
    op.drop_table("agent_definitions")
    op.drop_table("task_attempts")
    op.drop_table("tasks")
