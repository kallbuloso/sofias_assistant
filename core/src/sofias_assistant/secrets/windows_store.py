"""Windows Credential Manager implementation of SecretStore."""

import ctypes

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
from sofias_assistant.secrets.models import SecretRef, SecretValue

TARGET_PREFIX = "SofiasAssistant/"


class WindowsCredentialStore:
    """SecretStore backed by Windows Credential Manager."""

    def __init__(self, api: CredentialApi | None = None) -> None:
        self._api = api if api is not None else WinCredentialApi()

    def get(self, ref: SecretRef) -> SecretValue | None:
        target_name = self._target_name(ref)
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
            return SecretValue(raw.decode("utf-8"))
        finally:
            self._api.free(credential)

    def set(self, ref: SecretRef, value: SecretValue) -> None:
        target_name = self._target_name(ref)
        blob = value.reveal().encode("utf-8")
        if len(blob) > CRED_MAX_CREDENTIAL_BLOB_SIZE:
            raise ValueError(
                "Secret value exceeds the Windows Credential Manager blob limit"
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

    def delete(self, ref: SecretRef) -> bool:
        target_name = self._target_name(ref)
        try:
            self._api.delete(target_name)
        except OSError as error:
            if self._is_not_found(error):
                return False
            raise
        return True

    @staticmethod
    def _target_name(ref: SecretRef) -> str:
        target_name = f"{TARGET_PREFIX}v1/{ref.identifier.encode('utf-8').hex()}"
        if len(target_name) > CRED_MAX_GENERIC_TARGET_NAME_LENGTH:
            raise ValueError("Secret reference exceeds the Windows target name limit")
        return target_name

    @staticmethod
    def _is_not_found(error: OSError) -> bool:
        return getattr(error, "winerror", None) == ERROR_NOT_FOUND
