"""Bounded Conversation History index for Gate I18 (SA-B040).

Adds a composite index on conversations(updated_at, id) so the new
keyset-paginated `GET /api/v1/conversations` list query (ordered by
updated_at desc with a deterministic id tie-break) stays index-friendly
without a full table scan. No data migration: the existing
`turns(conversation_id, sequence)` unique constraint already covers the
new bounded Turn history queries.

Revision ID: 0012_conversation_history_index
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_conversation_history_index"
down_revision: str | None = "0011_ai_provider_model_profile_routing"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_updated_at_id",
        "conversations",
        ["updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_updated_at_id", table_name="conversations")
