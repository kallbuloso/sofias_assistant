"""ClientAttachRecord (Desktop/Core Interaction Contract v1 SS7).

The bounded, versioned material a Desktop process needs to attach to one
current Core lifecycle. The bearer `credential` is typed as `SecretValue` so
the dataclass-generated `repr` omits it (`field(repr=False)`); it must never
appear in `repr`, logs, Audit or ordinary diagnostics (Contract v1 SS7).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sofias_assistant.secrets.models import SecretValue

CONTRACT_VERSION = 1

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class InvalidAttachRecordError(ValueError):
    """Raised when an observed/serialized attach record fails validation."""


@dataclass(frozen=True, slots=True)
class ClientAttachRecord:
    """Bounded attach material for exactly one current Core lifecycle."""

    contract_version: int
    instance_key: str
    runtime_session_id: UUID
    host: str
    port: int
    credential: SecretValue = field(repr=False)
    application_version: str
    process_id: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise InvalidAttachRecordError(
                f"unsupported attach record contract_version: {self.contract_version}"
            )
        if not self.instance_key.strip():
            raise InvalidAttachRecordError("instance_key must not be blank")
        if self.host not in _LOOPBACK_HOSTS:
            raise InvalidAttachRecordError("attach record host must be loopback")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise InvalidAttachRecordError("attach record port must be 1..65535")
        if not self.application_version.strip():
            raise InvalidAttachRecordError("application_version must not be blank")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvalidAttachRecordError("created_at must be timezone-aware")

    def to_json(self) -> str:
        """Serialize compactly enough for a protected-store credential blob.

        Windows Credential Manager caps a generic credential blob at 2560
        bytes (`CRED_MAX_CREDENTIAL_BLOB_SIZE`); this uses compact separators
        and no whitespace so the bounded field set stays well under that
        limit.
        """

        payload: dict[str, Any] = {
            "contract_version": self.contract_version,
            "instance_key": self.instance_key,
            "runtime_session_id": str(self.runtime_session_id),
            "host": self.host,
            "port": self.port,
            "credential": self.credential.reveal(),
            "application_version": self.application_version,
            "process_id": self.process_id,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
        }
        return json.dumps(payload, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> ClientAttachRecord:
        """Parse a serialized record; raises `InvalidAttachRecordError` on any defect."""

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise InvalidAttachRecordError("attach record is not valid JSON") from error
        if not isinstance(payload, dict):
            raise InvalidAttachRecordError("attach record must be a JSON object")
        try:
            return cls(
                contract_version=int(payload["contract_version"]),
                instance_key=str(payload["instance_key"]),
                runtime_session_id=UUID(str(payload["runtime_session_id"])),
                host=str(payload["host"]),
                port=int(payload["port"]),
                credential=SecretValue(str(payload["credential"])),
                application_version=str(payload["application_version"]),
                process_id=(
                    int(payload["process_id"])
                    if payload.get("process_id") is not None
                    else None
                ),
                created_at=datetime.fromisoformat(str(payload["created_at"])),
            )
        except InvalidAttachRecordError:
            raise
        except (KeyError, ValueError, TypeError) as error:
            raise InvalidAttachRecordError("attach record is malformed") from error
