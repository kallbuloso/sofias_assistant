"""Minimal lazy ctypes boundary for Win32 Credential Manager."""

import ctypes
import os
from ctypes import POINTER, Structure, byref, c_void_p, wintypes
from typing import Any, Protocol

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512
CRED_MAX_GENERIC_TARGET_NAME_LENGTH = 32767


class CREDENTIAL_ATTRIBUTEW(Structure):
    """Win32 CREDENTIAL_ATTRIBUTEW structure for CREDENTIALW layout."""

    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", POINTER(wintypes.BYTE)),
    ]


class CREDENTIALW(Structure):
    """Win32 CREDENTIALW structure used by the Unicode Credential APIs."""

    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", POINTER(CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = POINTER(CREDENTIALW)


class CredentialApi(Protocol):
    """Small low-level contract used by the Windows SecretStore."""

    def read(self, target: str) -> Any: ...

    def write(self, credential: CREDENTIALW) -> None: ...

    def delete(self, target: str) -> None: ...

    def free(self, credential: Any) -> None: ...


class WinCredentialApi:
    """Lazy wrapper around the required Unicode Credential APIs."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError(
                "Windows Credential Manager is only available on Windows"
            )

        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            POINTER(PCREDENTIALW),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [POINTER(CREDENTIALW), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [c_void_p]
        api.CredFree.restype = None
        self._api = api

    def read(self, target: str) -> Any:
        credential = PCREDENTIALW()
        if not self._api.CredReadW(target, CRED_TYPE_GENERIC, 0, byref(credential)):
            self._raise_last_error()
        return credential

    def write(self, credential: CREDENTIALW) -> None:
        if not self._api.CredWriteW(byref(credential), 0):
            self._raise_last_error()

    def delete(self, target: str) -> None:
        if not self._api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            self._raise_last_error()

    def free(self, credential: Any) -> None:
        self._api.CredFree(credential)

    @staticmethod
    def _raise_last_error() -> None:
        error_code = ctypes.get_last_error()
        raise OSError(0, ctypes.FormatError(error_code), None, error_code)
