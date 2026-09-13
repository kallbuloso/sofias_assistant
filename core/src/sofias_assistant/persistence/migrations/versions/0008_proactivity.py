"""Add selective event delivery, durable schedules and user notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0008_proactivity"
down_revision = "0007_audit_traceability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("causation_id", sa.Uuid()),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("owner", sa.Uuid()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("completed_handlers_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','DISPATCHING','DELIVERED','FAILED','CANCELLED')"
        ),
    )
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("reminder", sa.String(1024), nullable=False),
        sa.Column("timezone", sa.String(128), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("next_run_at", sa.DateTime()),
        sa.Column("last_run_at", sa.DateTime()),
        sa.Column("recurrence", sa.String(32), nullable=False),
        sa.Column("interval_seconds", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id")),
        sa.Column("tool_call_id", sa.Uuid(), sa.ForeignKey("tool_calls.id")),
        sa.Column("grant_id", sa.Uuid()),
        sa.Column("last_event_id", sa.Uuid(), sa.ForeignKey("runtime_events.id")),
        sa.CheckConstraint("status IN ('ACTIVE','COMPLETED','CANCELLED')"),
        sa.CheckConstraint("kind IN ('REMINDER','TASK_WAKEUP')"),
        sa.CheckConstraint("recurrence IN ('ONCE','INTERVAL','DAILY')"),
        sa.CheckConstraint(
            "(recurrence = 'INTERVAL' AND interval_seconds IS NOT NULL "
            "AND interval_seconds BETWEEN 1 AND 31622400) OR "
            "(recurrence != 'INTERVAL' AND interval_seconds IS NULL)"
        ),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("runtime_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("type", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.String(1024), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("action_reference", sa.Uuid()),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime()),
        sa.CheckConstraint("state IN ('PENDING','ACKNOWLEDGED')"),
    )
    op.create_index(
        "ix_runtime_events_cause_type",
        "runtime_events",
        ["causation_id", "type", "occurred_at"],
    )
    for table in ("runtime_events", "schedules", "notifications"):
        op.create_index(f"ix_{table}_correlation_id", table, ["correlation_id"])
    op.create_index(
        "ix_runtime_events_pending", "runtime_events", ["status", "available_at"]
    )
    op.create_index("ix_schedules_due", "schedules", ["status", "next_run_at"])
    op.create_index(
        "ix_notifications_pending", "notifications", ["state", "created_at"]
    )


def downgrade() -> None:
    for table in ("notifications", "schedules", "runtime_events"):
        op.drop_table(table)
