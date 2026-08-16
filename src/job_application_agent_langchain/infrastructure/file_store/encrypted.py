"""AES-GCM encrypted, content-addressed blob storage."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from job_application_agent_langchain.infrastructure.security import KeyProvider


_MAGIC = b"JAF1"
_NONCE_SIZE = 12
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class IntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredBlob:
    content_sha256: str
    byte_size: int
    storage_key: str
    created: bool


class EncryptedContentStore:
    def __init__(self, root: Path, key_provider: KeyProvider):
        self.root = root
        self._key_provider = key_provider

    def put(self, plaintext: bytes) -> StoredBlob:
        digest = sha256(plaintext).hexdigest()
        storage_key = f"{digest[:2]}/{digest}.blob"
        target = self.root / storage_key
        if target.exists():
            existing = self.get(digest)
            if existing != plaintext:
                raise IntegrityError("content-address collision or corrupted blob")
            return StoredBlob(digest, len(plaintext), storage_key, False)

        target.parent.mkdir(parents=True, exist_ok=True)
        nonce = secrets.token_bytes(_NONCE_SIZE)
        associated_data = digest.encode("ascii")
        ciphertext = AESGCM(self._key_provider.get_or_create_key()).encrypt(
            nonce,
            plaintext,
            associated_data,
        )
        payload = _MAGIC + nonce + ciphertext
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with open(temporary, "xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(temporary, target)
            except FileExistsError:
                if self.get(digest) != plaintext:
                    raise IntegrityError("concurrent blob write produced bad content")
        finally:
            if temporary.exists():
                temporary.unlink()
        return StoredBlob(digest, len(plaintext), storage_key, True)

    def get(self, content_sha256: str) -> bytes:
        if not _DIGEST_PATTERN.fullmatch(content_sha256):
            raise ValueError("invalid SHA-256 content identifier")
        target = self.root / content_sha256[:2] / f"{content_sha256}.blob"
        payload = target.read_bytes()
        if len(payload) <= len(_MAGIC) + _NONCE_SIZE or not payload.startswith(_MAGIC):
            raise IntegrityError("invalid encrypted blob header")
        nonce_start = len(_MAGIC)
        nonce_end = nonce_start + _NONCE_SIZE
        try:
            plaintext = AESGCM(self._key_provider.get_or_create_key()).decrypt(
                payload[nonce_start:nonce_end],
                payload[nonce_end:],
                content_sha256.encode("ascii"),
            )
        except InvalidTag as exc:
            raise IntegrityError("encrypted blob authentication failed") from exc
        if sha256(plaintext).hexdigest() != content_sha256:
            raise IntegrityError("decrypted content digest does not match its address")
        return plaintext
