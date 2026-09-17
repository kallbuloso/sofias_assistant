"""Windows Credential Manager implementation of `ClientAttachStore`.

Uses a target namespace (`SofiasAssistant/Attach/v1/`) separate from
`WindowsCredentialStore` (`SofiasAssistant/v1/`, provider/integration
secrets) so attach lifecycle material never mixes semantically with provider
credentials, while reusing the same low-level Win32 Credential API wrapper
(`sofias_assistant.secrets._wincred`) instead of a second ctypes boundary.
"""

from __future__ import annotations

import ctypes
from uuid import UUID

from sofias_assistant.client_attach.models import (
    ClientAttachRecord,
    InvalidAttachRecordError,
)
from sofias_assistant.secrets._wincred import (
    CRED_MAX_CREDENTIAL_BLOB_SIZE,
    CRED_MAX_GENERIC_TARGET_NAME_LENGTH,
    CRED_PERSIST_LOCAL_MACHINE,
    CRED_TYPE_GENERIC,
    CREDENTIALW,
    ERROR_NOT_FOUND,
    CredentialApi,
    WinCredentialApi,
)

TARGET_PREFIX = "SofiasAssistant/Attach/v1/"


class WindowsClientAttachStore:
    """ClientAttachStore backed by Windows Credential Manager.

    Publication is a plain overwrite: the owning Core only ever publishes
    its own lifecycle's record after acquiring exclusive single-instance
    ownership, so no concurrent writer can exist for the same `instance_key`.
    `delete_if_current` is read-then-compare-then-delete; Windows Credential
    Manager exposes no atomic compare-and-delete primitive, so a narrow
    TOCTOU window exists between the read and the delete. This is an accepted
    limitation of the platform API (Amendment 0004 SS14 threat model already
    excludes hostile code running as the same OS user).
    """

    def __init__(self, api: CredentialApi | None = None) -> None:
        self._api = api if api is not None else WinCredentialApi()

    def publish(self, instance_key: str, record: ClientAttachRecord) -> None:
        target_name = self._target_name(instance_key)
        blob = record.to_json().encode("utf-8")
        if len(blob) > CRED_MAX_CREDENTIAL_BLOB_SIZE:
            raise ValueError(
                "Attach record exceeds the Windows Credential Manager blob limit"
            )
        buffer = ctypes.create_string_buffer(blob)
        credential = CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target_name
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, type(credential.CredentialBlob))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        try:
            self._api.write(credential)
        finally:
            ctypes.memset(buffer, 0, len(blob))

    def read(self, instance_key: str) -> ClientAttachRecord | None:
        target_name = self._target_name(instance_key)
        try:
            credential = self._api.read(target_name)
        except OSError as error:
            if self._is_not_found(error):
                return None
            raise

        try:
            raw = ctypes.string_at(
                credential.contents.CredentialBlob,
                credential.contents.CredentialBlobSize,
            )
        finally:
            self._api.free(credential)

        try:
            return ClientAttachRecord.from_json(raw.decode("utf-8"))
        except (InvalidAttachRecordError, UnicodeDecodeError):
            return None

    def delete_if_current(self, instance_key: str, runtime_session_id: UUID) -> bool:
        current = self.read(instance_key)
        if current is None or current.runtime_session_id != runtime_session_id:
            return False
        target_name = self._target_name(instance_key)
        try:
            self._api.delete(target_name)
        except OSError as error:
            if self._is_not_found(error):
                return False
            raise
        return True

    @staticmethod
    def _target_name(instance_key: str) -> str:
        target_name = f"{TARGET_PREFIX}{instance_key}"
        if len(target_name) > CRED_MAX_GENERIC_TARGET_NAME_LENGTH:
            raise ValueError("instance_key exceeds the Windows target name limit")
        return target_name

    @staticmethod
    def _is_not_found(error: OSError) -> bool:
        return getattr(error, "winerror", None) == ERROR_NOT_FOUND
