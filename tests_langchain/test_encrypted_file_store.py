"""Security and integrity tests for content-addressed file resources."""

from pathlib import Path
import sys

import pytest

from job_application_agent_langchain.infrastructure.file_store import (
    EncryptedContentStore,
    IntegrityError,
)
from job_application_agent_langchain.infrastructure.security import (
    StaticKeyProvider,
    WindowsDpapiKeyProvider,
)


def make_store(root: Path) -> EncryptedContentStore:
    return EncryptedContentStore(root, StaticKeyProvider(b"k" * 32))


def test_content_is_encrypted_deduplicated_and_round_trips(tmp_path):
    store = make_store(tmp_path)
    plaintext = b"private resume content with phone 13800000000"

    first = store.put(plaintext)
    second = store.put(plaintext)

    assert first.created is True
    assert second.created is False
    assert first.content_sha256 == second.content_sha256
    assert store.get(first.content_sha256) == plaintext
    disk_payload = (tmp_path / first.storage_key).read_bytes()
    assert plaintext not in disk_payload
    assert disk_payload.startswith(b"JAF1")


def test_tampering_is_detected(tmp_path):
    store = make_store(tmp_path)
    stored = store.put(b"sensitive resume")
    target = tmp_path / stored.storage_key
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 1
    target.write_bytes(payload)

    with pytest.raises(IntegrityError, match="authentication failed"):
        store.get(stored.content_sha256)


def test_invalid_content_identifier_is_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ValueError, match="invalid SHA-256"):
        store.get("../resume.pdf")


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-specific")
def test_windows_dpapi_key_survives_provider_restart(tmp_path):
    protected_path = tmp_path / "master-key.dpapi"
    first = WindowsDpapiKeyProvider(protected_path).get_or_create_key()
    second = WindowsDpapiKeyProvider(protected_path).get_or_create_key()

    assert first == second
    assert len(first) == 32
    assert first not in protected_path.read_bytes()
