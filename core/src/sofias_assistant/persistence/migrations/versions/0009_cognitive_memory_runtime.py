"""Add Assistant-owned Cognitive Memory candidate/operation runtime state."""

import sqlalchemy as sa
from alembic import op

revision = "0009_cognitive_memory_runtime"
down_revision = "0008_proactivity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("origin_kind", sa.String(32), nullable=False),
        sa.Column("decision_status", sa.String(32), nullable=False),
        sa.Column("persistence_status", sa.String(32), nullable=False),
        sa.Column("conversation_id", sa.Uuid()),
        sa.Column("turn_id", sa.Uuid()),
        sa.Column("task_id", sa.Uuid()),
        sa.Column("source_ref", sa.String(255)),
        sa.Column("confirmation_ref", sa.String(255)),
        sa.Column("observed_at", sa.DateTime()),
        sa.Column("confidence", sa.Float()),
        sa.Column("valid_from", sa.DateTime()),
        sa.Column("valid_until", sa.DateTime()),
        sa.Column("cloud_context_eligible", sa.Boolean(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("memory_id", sa.Uuid()),
        sa.Column("safe_failure_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime()),
        sa.Column("persisted_at", sa.DateTime()),
        sa.CheckConstraint("memory_type IN ('profile','semantic')"),
        sa.CheckConstraint(
            "origin_kind IN ('user_asserted','tool_observed','imported',"
            "'inferred','assistant_generated')"
        ),
        sa.CheckConstraint("decision_status IN ('PENDING','APPROVED','REJECTED')"),
        sa.CheckConstraint(
            "persistence_status IN ('NOT_REQUESTED','PENDING','SUCCEEDED','FAILED')"
        ),
    )
    op.create_index(
        "ix_memory_candidates_conversation_id",
        "memory_candidates",
        ["conversation_id"],
    )
    op.create_table(
        "memory_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("target_memory_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("replacement_candidate_id", sa.Uuid()),
        sa.Column("replacement_memory_id", sa.Uuid()),
        sa.Column("safe_failure_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.CheckConstraint("kind IN ('SUPERSEDE','FORGET')"),
        sa.CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED')"),
    )
    op.add_column(
        "audit_entries", sa.Column("memory_candidate_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "audit_entries", sa.Column("memory_operation_id", sa.Uuid(), nullable=True)
    )
    op.add_column("audit_entries", sa.Column("memory_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_entries", "memory_id")
    op.drop_column("audit_entries", "memory_operation_id")
    op.drop_column("audit_entries", "memory_candidate_id")
    op.drop_table("memory_operations")
    op.drop_index("ix_memory_candidates_conversation_id", "memory_candidates")
    op.drop_table("memory_candidates")
