"""Add durable grant_id to task_attempts for Gate I12 startup recovery.

A TaskAttempt's grant_id is part of its durable execution intent: without
it, a safely-retried/reconstructed Task can never re-satisfy authorization
that legitimately still applies, because the deterministic PolicyEngine only
consults a grant when one is explicitly referenced (it never searches for a
matching grant). Persisting the reference does not skip re-validation: the
referenced grant is always re-checked live (ACTIVE/expiry/revocation/scope)
at the moment of use, so this does not revive stale authority.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_task_attempt_grant"
down_revision = "0009_cognitive_memory_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_attempts", sa.Column("grant_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_attempts", "grant_id")
