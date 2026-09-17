"""Domain-oriented repositories for the Operational Store."""

import json
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sofias_assistant.ai.contracts import (
    Capability,
    CapabilityProvenance,
    DataLocality,
    ExecutionLocation,
)
from sofias_assistant.ai.registry import ModelAvailability
from sofias_assistant.ai.routing_policy import FallbackPolicy
from sofias_assistant.ai_config.models import (
    CapabilityClaim,
    DiscoverySource,
    InferenceProfile,
    ModelCatalogEntry,
    ProfileModelBinding,
    ProviderConfiguration,
)
from sofias_assistant.conversation.models import Conversation, Turn
from sofias_assistant.persistence.models import (
    ApplicationSetting,
    ConversationRecord,
    InferenceProfileRecord,
    ModelCatalogEntryRecord,
    ProfileModelBindingRecord,
    ProviderConfigurationRecord,
    RuntimeSession,
    RuntimeSessionStatus,
    TurnRecord,
)
from sofias_assistant.secrets.models import SecretRef


class RepositoryEntityNotFoundError(RuntimeError):
    """Raised when save is requested for an entity absent from the store."""


class RuntimeSessionRepository:
    """Persistence operations for runtime session records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, runtime_session: RuntimeSession) -> None:
        self._session.add(runtime_session)

    async def get_by_id(self, runtime_session_id: UUID) -> RuntimeSession | None:
        return await self._session.get(RuntimeSession, runtime_session_id)

    async def list_by_status(
        self, status: RuntimeSessionStatus
    ) -> list[RuntimeSession]:
        result = await self._session.scalars(
            select(RuntimeSession).where(RuntimeSession.status == status)
        )
        return list(result)


class ApplicationSettingRepository:
    """Persistence operations for application setting records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, application_setting: ApplicationSetting) -> None:
        self._session.add(application_setting)

    async def get_by_key(self, key: str) -> ApplicationSetting | None:
        return await self._session.get(ApplicationSetting, key)


class ConversationRepository:
    """Explicit persistence mapping for Core-owned Conversation snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, conversation: Conversation) -> None:
        self._session.add(_conversation_to_record(conversation))

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        record = await self._session.get(ConversationRecord, conversation_id)
        return _conversation_from_record(record) if record is not None else None

    async def save(self, conversation: Conversation) -> None:
        record = await self._session.get(ConversationRecord, conversation.id)
        if record is None:
            raise RepositoryEntityNotFoundError("Conversation does not exist")
        record.created_at = conversation.created_at
        record.updated_at = conversation.updated_at

    async def list_page(
        self, *, limit: int, before: tuple[datetime, UUID] | None
    ) -> tuple[list[Conversation], bool]:
        """Return one keyset-paginated page ordered by (updated_at, id) desc.

        Fetches `limit + 1` rows to determine `has_more` without a second
        COUNT query; only the first `limit` rows are returned.
        """

        query = select(ConversationRecord).order_by(
            ConversationRecord.updated_at.desc(), ConversationRecord.id.desc()
        )
        if before is not None:
            before_updated_at, before_id = before
            query = query.where(
                or_(
                    ConversationRecord.updated_at < before_updated_at,
                    and_(
                        ConversationRecord.updated_at == before_updated_at,
                        ConversationRecord.id < before_id,
                    ),
                )
            )
        records = list(await self._session.scalars(query.limit(limit + 1)))
        has_more = len(records) > limit
        page = records[:limit]
        return [_conversation_from_record(record) for record in page], has_more


class TurnRepository:
    """Explicit persistence mapping for ordered Core-owned Turn snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, turn: Turn) -> None:
        self._session.add(_turn_to_record(turn))

    async def get_by_id(self, turn_id: UUID) -> Turn | None:
        record = await self._session.get(TurnRecord, turn_id)
        return _turn_from_record(record) if record is not None else None

    async def list_for_conversation(self, conversation_id: UUID) -> list[Turn]:
        records = await self._session.scalars(
            select(TurnRecord)
            .where(TurnRecord.conversation_id == conversation_id)
            .order_by(TurnRecord.sequence.asc())
        )
        return [_turn_from_record(record) for record in records]

    async def next_sequence(self, conversation_id: UUID) -> int:
        """Return max(sequence) + 1; runtime serialization remains a later concern."""
        maximum = await self._session.scalar(
            select(func.max(TurnRecord.sequence)).where(
                TurnRecord.conversation_id == conversation_id
            )
        )
        return 1 if maximum is None else int(maximum) + 1

    async def save(self, turn: Turn) -> None:
        record = await self._session.get(TurnRecord, turn.id)
        if record is None:
            raise RepositoryEntityNotFoundError("Turn does not exist")
        _copy_turn_to_record(turn, record)

    async def list_recent(
        self, conversation_id: UUID, *, limit: int
    ) -> tuple[list[Turn], bool]:
        """Return the most recent `limit` Turns in chronological order.

        Fetches `limit + 1` (by sequence desc) to determine `has_older`
        without a second COUNT query, then reverses to chronological order.
        """

        records = list(
            await self._session.scalars(
                select(TurnRecord)
                .where(TurnRecord.conversation_id == conversation_id)
                .order_by(TurnRecord.sequence.desc())
                .limit(limit + 1)
            )
        )
        has_older = len(records) > limit
        page = list(reversed(records[:limit]))
        return [_turn_from_record(record) for record in page], has_older

    async def list_before(
        self, conversation_id: UUID, *, before_sequence: int, limit: int
    ) -> tuple[list[Turn], bool]:
        """Return an older bounded page strictly before `before_sequence`."""

        records = list(
            await self._session.scalars(
                select(TurnRecord)
                .where(
                    TurnRecord.conversation_id == conversation_id,
                    TurnRecord.sequence < before_sequence,
                )
                .order_by(TurnRecord.sequence.desc())
                .limit(limit + 1)
            )
        )
        has_older = len(records) > limit
        page = list(reversed(records[:limit]))
        return [_turn_from_record(record) for record in page], has_older

    async def first_turns_for(
        self, conversation_ids: Sequence[UUID]
    ) -> dict[UUID, Turn]:
        """Return the first non-blank-user-text Turn per conversation id.

        Bounded to the given id set in one query (never per-conversation),
        avoiding N+1 when building list previews for a page of Conversations.
        """

        if not conversation_ids:
            return {}
        first_sequence = (
            select(
                TurnRecord.conversation_id,
                func.min(TurnRecord.sequence).label("first_sequence"),
            )
            .where(
                TurnRecord.conversation_id.in_(conversation_ids),
                TurnRecord.user_text != "",
            )
            .group_by(TurnRecord.conversation_id)
            .subquery()
        )
        records = await self._session.scalars(
            select(TurnRecord).join(
                first_sequence,
                and_(
                    TurnRecord.conversation_id == first_sequence.c.conversation_id,
                    TurnRecord.sequence == first_sequence.c.first_sequence,
                ),
            )
        )
        return {record.conversation_id: _turn_from_record(record) for record in records}

    async def latest_turns_for(
        self, conversation_ids: Sequence[UUID]
    ) -> dict[UUID, Turn]:
        """Return the latest Turn per conversation id, bounded to one query."""

        if not conversation_ids:
            return {}
        latest_sequence = (
            select(
                TurnRecord.conversation_id,
                func.max(TurnRecord.sequence).label("latest_sequence"),
            )
            .where(TurnRecord.conversation_id.in_(conversation_ids))
            .group_by(TurnRecord.conversation_id)
            .subquery()
        )
        records = await self._session.scalars(
            select(TurnRecord).join(
                latest_sequence,
                and_(
                    TurnRecord.conversation_id == latest_sequence.c.conversation_id,
                    TurnRecord.sequence == latest_sequence.c.latest_sequence,
                ),
            )
        )
        return {record.conversation_id: _turn_from_record(record) for record in records}


def _conversation_to_record(conversation: Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _conversation_from_record(record: ConversationRecord) -> Conversation:
    return Conversation(
        id=record.id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _turn_to_record(turn: Turn) -> TurnRecord:
    record = TurnRecord(id=turn.id, conversation_id=turn.conversation_id)
    _copy_turn_to_record(turn, record)
    return record


def _copy_turn_to_record(turn: Turn, record: TurnRecord) -> None:
    record.conversation_id = turn.conversation_id
    record.sequence = turn.sequence
    record.status = turn.status
    record.input_modality = turn.input_modality
    record.cloud_context_eligible = turn.cloud_context_eligible
    record.user_text = turn.user_text
    record.assistant_text = turn.assistant_text
    record.ai_request_id = turn.ai_request_id
    record.provider_id = turn.provider_id
    record.model_id = turn.model_id
    record.provider_request_id = turn.provider_request_id
    record.provider_session_id = turn.provider_session_id
    record.error_category = turn.error_category
    record.error_message = turn.error_message
    record.created_at = turn.created_at
    record.updated_at = turn.updated_at
    record.finished_at = turn.finished_at


def _turn_from_record(record: TurnRecord) -> Turn:
    return Turn(
        id=record.id,
        conversation_id=record.conversation_id,
        sequence=record.sequence,
        status=record.status,
        input_modality=record.input_modality,
        cloud_context_eligible=record.cloud_context_eligible,
        user_text=record.user_text,
        assistant_text=record.assistant_text,
        ai_request_id=record.ai_request_id,
        provider_id=record.provider_id,
        model_id=record.model_id,
        provider_request_id=record.provider_request_id,
        provider_session_id=record.provider_session_id,
        error_category=record.error_category,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
        finished_at=record.finished_at,
    )


class ProviderConfigurationRepository:
    """Persistence operations for non-secret AI provider configuration."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, provider: ProviderConfiguration) -> None:
        self._session.add(_provider_to_record(provider))

    async def get_by_id(self, provider_id: str) -> ProviderConfiguration | None:
        record = await self._session.get(ProviderConfigurationRecord, provider_id)
        return _provider_from_record(record) if record is not None else None

    async def list_all(self) -> list[ProviderConfiguration]:
        result = await self._session.scalars(
            select(ProviderConfigurationRecord).order_by(ProviderConfigurationRecord.id)
        )
        return [_provider_from_record(record) for record in result]

    async def save(self, provider: ProviderConfiguration) -> None:
        record = await self._session.get(ProviderConfigurationRecord, provider.id)
        if record is None:
            raise RepositoryEntityNotFoundError("ProviderConfiguration does not exist")
        _copy_provider_to_record(provider, record)


class ModelCatalogRepository:
    """Persistence operations for the (provider_id, model_id) keyed catalog."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entry: ModelCatalogEntry) -> None:
        self._session.add(_model_to_record(entry))

    async def get_by_identity(
        self, provider_id: str, model_id: str
    ) -> ModelCatalogEntry | None:
        record = await self._get_record(provider_id, model_id)
        return _model_from_record(record) if record is not None else None

    async def list_all(self) -> list[ModelCatalogEntry]:
        result = await self._session.scalars(
            select(ModelCatalogEntryRecord).order_by(
                ModelCatalogEntryRecord.provider_id, ModelCatalogEntryRecord.model_id
            )
        )
        return [_model_from_record(record) for record in result]

    async def list_for_provider(self, provider_id: str) -> list[ModelCatalogEntry]:
        result = await self._session.scalars(
            select(ModelCatalogEntryRecord)
            .where(ModelCatalogEntryRecord.provider_id == provider_id)
            .order_by(ModelCatalogEntryRecord.model_id)
        )
        return [_model_from_record(record) for record in result]

    async def save(self, entry: ModelCatalogEntry) -> None:
        record = await self._get_record(entry.provider_id, entry.model_id)
        if record is None:
            raise RepositoryEntityNotFoundError("ModelCatalogEntry does not exist")
        _copy_model_to_record(entry, record)

    async def _get_record(
        self, provider_id: str, model_id: str
    ) -> ModelCatalogEntryRecord | None:
        return await self._session.scalar(
            select(ModelCatalogEntryRecord).where(
                ModelCatalogEntryRecord.provider_id == provider_id,
                ModelCatalogEntryRecord.model_id == model_id,
            )
        )


class InferenceProfileRepository:
    """Persistence operations for workload InferenceProfile records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, profile: InferenceProfile) -> None:
        self._session.add(_profile_to_record(profile))

    async def get_by_key(self, key: str) -> InferenceProfile | None:
        record = await self._session.get(InferenceProfileRecord, key)
        return _profile_from_record(record) if record is not None else None

    async def list_all(self) -> list[InferenceProfile]:
        result = await self._session.scalars(
            select(InferenceProfileRecord).order_by(InferenceProfileRecord.key)
        )
        return [_profile_from_record(record) for record in result]

    async def save(self, profile: InferenceProfile) -> None:
        record = await self._session.get(InferenceProfileRecord, profile.key)
        if record is None:
            raise RepositoryEntityNotFoundError("InferenceProfile does not exist")
        _copy_profile_to_record(profile, record)


class ProfileModelBindingRepository:
    """Persistence operations for ordered ProfileModelBinding preferences."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, binding: ProfileModelBinding) -> None:
        self._session.add(_binding_to_record(binding))

    async def list_for_profile(self, profile_key: str) -> list[ProfileModelBinding]:
        result = await self._session.scalars(
            select(ProfileModelBindingRecord)
            .where(ProfileModelBindingRecord.profile_key == profile_key)
            .order_by(ProfileModelBindingRecord.priority)
        )
        return [_binding_from_record(record) for record in result]

    async def list_all(self) -> list[ProfileModelBinding]:
        result = await self._session.scalars(
            select(ProfileModelBindingRecord).order_by(
                ProfileModelBindingRecord.profile_key,
                ProfileModelBindingRecord.priority,
            )
        )
        return [_binding_from_record(record) for record in result]

    async def replace_for_profile(
        self, profile_key: str, bindings: list[ProfileModelBinding]
    ) -> None:
        await self._session.execute(
            delete(ProfileModelBindingRecord).where(
                ProfileModelBindingRecord.profile_key == profile_key
            )
        )
        for binding in bindings:
            self.add(binding)


def _provider_to_record(provider: ProviderConfiguration) -> ProviderConfigurationRecord:
    record = ProviderConfigurationRecord(id=provider.id)
    _copy_provider_to_record(provider, record)
    return record


def _copy_provider_to_record(
    provider: ProviderConfiguration, record: ProviderConfigurationRecord
) -> None:
    record.display_name = provider.display_name
    record.adapter_type = provider.adapter_type
    record.base_url = provider.base_url
    record.enabled = provider.enabled
    record.execution_location = provider.execution_location.value
    record.credential_ref = (
        provider.credential_ref.identifier if provider.credential_ref else None
    )
    record.created_at = provider.created_at
    record.updated_at = provider.updated_at


def _provider_from_record(record: ProviderConfigurationRecord) -> ProviderConfiguration:
    return ProviderConfiguration(
        id=record.id,
        display_name=record.display_name,
        adapter_type=record.adapter_type,
        base_url=record.base_url,
        enabled=record.enabled,
        execution_location=ExecutionLocation(record.execution_location),
        credential_ref=(
            SecretRef(record.credential_ref) if record.credential_ref else None
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _require_timestamp(
    value: "datetime | None", fallback: "datetime | None"
) -> "datetime":
    if value is not None:
        return value
    if fallback is not None:
        return fallback
    raise ValueError("a created_at/updated_at timestamp is required")


def _capabilities_to_json(capabilities: frozenset[CapabilityClaim]) -> str:
    return json.dumps(
        {claim.capability.value: claim.provenance.value for claim in capabilities},
        sort_keys=True,
    )


def _capabilities_from_json(value: str) -> frozenset[CapabilityClaim]:
    raw = json.loads(value)
    return frozenset(
        CapabilityClaim(Capability(capability), CapabilityProvenance(provenance))
        for capability, provenance in raw.items()
    )


def _model_to_record(entry: ModelCatalogEntry) -> ModelCatalogEntryRecord:
    record = ModelCatalogEntryRecord(
        id=uuid4(), provider_id=entry.provider_id, model_id=entry.model_id
    )
    _copy_model_to_record(entry, record)
    return record


def _copy_model_to_record(
    entry: ModelCatalogEntry, record: ModelCatalogEntryRecord
) -> None:
    record.provider_id = entry.provider_id
    record.model_id = entry.model_id
    record.display_name = entry.display_name
    record.context_window = entry.context_window
    record.execution_location = entry.execution_location.value
    record.availability = entry.availability.value
    record.enabled = entry.enabled
    record.discovery_source = entry.discovery_source.value
    record.capabilities_json = _capabilities_to_json(entry.capabilities)
    record.metadata_json = json.dumps(entry.metadata, sort_keys=True, default=str)
    record.last_seen_at = entry.last_seen_at
    record.created_at = _require_timestamp(entry.created_at, entry.updated_at)
    record.updated_at = _require_timestamp(entry.updated_at, entry.created_at)


def _model_from_record(record: ModelCatalogEntryRecord) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        provider_id=record.provider_id,
        model_id=record.model_id,
        display_name=record.display_name,
        context_window=record.context_window,
        execution_location=ExecutionLocation(record.execution_location),
        availability=ModelAvailability(record.availability),
        enabled=record.enabled,
        discovery_source=DiscoverySource(record.discovery_source),
        capabilities=_capabilities_from_json(record.capabilities_json),
        metadata=json.loads(record.metadata_json),
        last_seen_at=record.last_seen_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _profile_to_record(profile: InferenceProfile) -> InferenceProfileRecord:
    record = InferenceProfileRecord(key=profile.key)
    _copy_profile_to_record(profile, record)
    return record


def _copy_profile_to_record(
    profile: InferenceProfile, record: InferenceProfileRecord
) -> None:
    record.display_name = profile.display_name
    record.description = profile.description
    record.required_capabilities_json = json.dumps(
        sorted(capability.value for capability in profile.required_capabilities)
    )
    record.preferred_capabilities_json = json.dumps(
        sorted(capability.value for capability in profile.preferred_capabilities)
    )
    record.locality = profile.locality.value
    record.enabled = profile.enabled
    record.fallback_policy = profile.fallback_policy.value
    record.created_at = _require_timestamp(profile.created_at, profile.updated_at)
    record.updated_at = _require_timestamp(profile.updated_at, profile.created_at)


def _profile_from_record(record: InferenceProfileRecord) -> InferenceProfile:
    return InferenceProfile(
        key=record.key,
        display_name=record.display_name,
        description=record.description,
        required_capabilities=frozenset(
            Capability(value) for value in json.loads(record.required_capabilities_json)
        ),
        preferred_capabilities=frozenset(
            Capability(value)
            for value in json.loads(record.preferred_capabilities_json)
        ),
        locality=DataLocality(record.locality),
        enabled=record.enabled,
        fallback_policy=FallbackPolicy(record.fallback_policy),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _binding_to_record(binding: ProfileModelBinding) -> ProfileModelBindingRecord:
    now = binding.created_at or binding.updated_at
    return ProfileModelBindingRecord(
        id=uuid4(),
        profile_key=binding.profile_key,
        provider_id=binding.provider_id,
        model_id=binding.model_id,
        priority=binding.priority,
        enabled=binding.enabled,
        source=binding.source,
        created_at=now,
        updated_at=binding.updated_at or now,
    )


def _binding_from_record(record: ProfileModelBindingRecord) -> ProfileModelBinding:
    return ProfileModelBinding(
        profile_key=record.profile_key,
        provider_id=record.provider_id,
        model_id=record.model_id,
        priority=record.priority,
        enabled=record.enabled,
        source=record.source,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
