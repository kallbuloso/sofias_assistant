"""Persistent AI provider/model/profile configuration for Gate I15.

Adds ProviderConfiguration, ModelCatalogEntry, InferenceProfile and
ProfileModelBinding (Architecture Review Amendment 0003 SS10; AI Runtime
Configuration Contract v1 SS16-SS23). No secret value is ever stored here:
`credential_ref` on `ai_provider_configurations` is a `SecretRef` identity
string only, never a secret value (resolved exclusively through
`SecretService` at call scope).

Revision ID: 0011_ai_provider_model_profile_routing
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_ai_provider_model_profile_routing"
down_revision: str | None = "0010_task_attempt_grant"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_configurations",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("adapter_type", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("execution_location", sa.String(length=16), nullable=False),
        sa.Column("credential_ref", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ai_inference_profiles",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required_capabilities_json", sa.Text(), nullable=False),
        sa.Column("preferred_capabilities_json", sa.Text(), nullable=False),
        sa.Column("locality", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fallback_policy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ai_model_catalog_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(length=128),
            sa.ForeignKey("ai_provider_configurations.id"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("execution_location", sa.String(length=16), nullable=False),
        sa.Column("availability", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("discovery_source", sa.String(length=32), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider_id", "model_id"),
    )
    op.create_table(
        "ai_profile_model_bindings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_key",
            sa.String(length=64),
            sa.ForeignKey("ai_inference_profiles.key"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("profile_key", "provider_id", "model_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_profile_model_bindings")
    op.drop_table("ai_model_catalog_entries")
    op.drop_table("ai_inference_profiles")
    op.drop_table("ai_provider_configurations")
