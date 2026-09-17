"""Known bootstrap secret mappings (Runtime Configuration Contract v1 SS8-SS10).

Only these two environment variable names are ever bridged into
`SecretService`. Adapters never read them directly; they always resolve a
`SecretRef` through `SecretService`.
"""

from __future__ import annotations

from collections.abc import Mapping

from sofias_assistant.secrets.models import SecretRef
from sofias_assistant.secrets.service import SecretService

LLM_API_KEY_ENVIRONMENT_VARIABLE = "LLM_API_KEY"
SOFIAS_MEMORY_API_KEY_ENVIRONMENT_VARIABLE = "SOFIAS_MEMORY_API_KEY"

SOFIAS_MEMORY_API_KEY_REF = SecretRef("integrations/sofias-memory/api-key")


def provider_api_key_ref(provider_id: str) -> SecretRef:
    """Return the stable `SecretRef` identity for one provider's API key.

    The same normalization must be used everywhere a provider identity
    becomes part of a `SecretRef`, so the environment bridge and the
    provider adapter composition always agree on one reference.
    """

    normalized = provider_id.strip().lower()
    return SecretRef(f"providers/{normalized}/api-key")


def bootstrap_secret_mappings(*, llm_provider_id: str) -> dict[str, SecretRef]:
    """Return the exhaustive, explicit environment-to-SecretRef bridge for v1."""

    return {
        LLM_API_KEY_ENVIRONMENT_VARIABLE: provider_api_key_ref(llm_provider_id),
        SOFIAS_MEMORY_API_KEY_ENVIRONMENT_VARIABLE: SOFIAS_MEMORY_API_KEY_REF,
    }


def describe_secret_source(
    *,
    variable_name: str,
    ref: SecretRef,
    real_environment: Mapping[str, str],
    env_file_environment: Mapping[str, str] | None,
    secret_service: SecretService,
) -> str:
    """Return a safe, value-free diagnostic: environment|env_file|platform_store|missing."""

    if real_environment.get(variable_name):
        return "environment"
    if env_file_environment and env_file_environment.get(variable_name):
        return "env_file"
    if secret_service.get(ref) is not None:
        return "platform_store"
    return "missing"


def credential_write_status(
    ref: SecretRef, secret_service: SecretService
) -> tuple[str, bool, bool]:
    """Return (effective_source, configured, shadowed) for a write/delete response.

    Desktop/Core Interaction Contract v1 SS26-SS27: writes always target the
    writable platform store; a higher-priority environment-backed secret may
    still shadow it. `shadowed` is true exactly when the environment layer,
    not the platform store we just wrote/deleted, is the effective source.
    """

    source = secret_service.describe(ref)
    configured = source != "missing"
    shadowed = source == "environment"
    return source, configured, shadowed
