"""Authenticated encryption for sensitive structured columns."""

from __future__ import annotations

import json
import secrets
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from job_application_agent_langchain.infrastructure.security.keys import KeyProvider


_MAGIC = b"JAJ1"
_NONCE_SIZE = 12


class SensitiveJsonError(RuntimeError):
    pass


class SensitiveJsonCodec:
    def __init__(self, key_provider: KeyProvider):
        self._key_provider = key_provider

    def encode(self, value: Any, *, context: str) -> bytes:
        plaintext = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = AESGCM(self._key_provider.get_or_create_key()).encrypt(
            nonce,
            plaintext,
            context.encode("utf-8"),
        )
        return _MAGIC + nonce + ciphertext

    def decode(self, payload: bytes, *, context: str) -> Any:
        if len(payload) <= len(_MAGIC) + _NONCE_SIZE or not payload.startswith(_MAGIC):
            raise SensitiveJsonError("invalid encrypted JSON header")
        nonce_start = len(_MAGIC)
        nonce_end = nonce_start + _NONCE_SIZE
        try:
            plaintext = AESGCM(self._key_provider.get_or_create_key()).decrypt(
                payload[nonce_start:nonce_end],
                payload[nonce_end:],
                context.encode("utf-8"),
            )
        except InvalidTag as exc:
            raise SensitiveJsonError("encrypted JSON authentication failed") from exc
        return json.loads(plaintext.decode("utf-8"))
