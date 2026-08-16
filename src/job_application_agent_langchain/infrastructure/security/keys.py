"""Master-key providers.

Production on Windows uses user-scoped DPAPI.  The plaintext master key is
never written to disk.  ``StaticKeyProvider`` exists for deterministic tests
and must not be selected from environment variables in production.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import sys
from typing import Protocol
from uuid import uuid4


MASTER_KEY_SIZE = 32
_DPAPI_ENTROPY = b"job-application-agent-core-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class KeyProvider(Protocol):
    def get_or_create_key(self) -> bytes: ...


class StaticKeyProvider:
    def __init__(self, key: bytes):
        if len(key) != MASTER_KEY_SIZE:
            raise ValueError("AES-256 master key must be exactly 32 bytes")
        self._key = key

    def get_or_create_key(self) -> bytes:
        return self._key


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _make_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI is only available on Windows")

    input_blob, input_buffer = _make_blob(data)
    entropy_blob, entropy_buffer = _make_blob(_DPAPI_ENTROPY)
    output_blob = _DataBlob()

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "job-application-agent master key",
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output_blob),
        )
    if not ok:
        raise ctypes.WinError()
    try:
        # Keep the input buffers alive until the native call has completed.
        del input_buffer, entropy_buffer
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


class WindowsDpapiKeyProvider:
    """Persist a DPAPI-wrapped random master key for the current OS user."""

    def __init__(self, protected_key_path: Path):
        self.protected_key_path = protected_key_path

    def get_or_create_key(self) -> bytes:
        if self.protected_key_path.exists():
            key = _dpapi_transform(
                self.protected_key_path.read_bytes(), protect=False
            )
            if len(key) != MASTER_KEY_SIZE:
                raise RuntimeError("invalid protected master key length")
            return key

        self.protected_key_path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(MASTER_KEY_SIZE)
        wrapped = _dpapi_transform(key, protect=True)
        temporary = self.protected_key_path.with_name(
            f".{self.protected_key_path.name}.{uuid4().hex}.tmp"
        )
        try:
            with open(temporary, "xb") as handle:
                handle.write(wrapped)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.protected_key_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return key
