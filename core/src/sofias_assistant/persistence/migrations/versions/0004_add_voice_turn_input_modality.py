"""Allow durable VOICE Turn input modality without storing audio.

Revision ID: 0004_add_voice_turn_input_modality
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_voice_turn_input_modality"
down_revision: str | None = "0003_turn_cloud_context_eligibility"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _input_modality(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(
        *values,
        name="turn_input_modality",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    with op.batch_alter_table("turns", recreate="always") as batch:
        batch.alter_column(
            "input_modality",
            existing_type=_input_modality(("TEXT",)),
            type_=_input_modality(("TEXT", "VOICE")),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    voice_row = bind.execute(
        sa.text("SELECT 1 FROM turns WHERE input_modality = 'VOICE' LIMIT 1")
    ).first()
    if voice_row is not None:
        raise RuntimeError("Cannot downgrade while VOICE turns exist")
    with op.batch_alter_table("turns", recreate="always") as batch:
        batch.alter_column(
            "input_modality",
            existing_type=_input_modality(("TEXT", "VOICE")),
            type_=_input_modality(("TEXT",)),
            existing_nullable=False,
        )
