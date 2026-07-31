"""Versioned candidate-profile behavior and API contracts."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from job_application_agent_langchain.api_v2.dependencies import (
    get_file_resource_service,
    get_profile_service,
)
from job_application_agent_langchain.application.file_resources import FileResourceService
from job_application_agent_langchain.application.profiles import (
    ProfileConflictError,
    ProfileService,
)
from job_application_agent_langchain.infrastructure.database import Database, MigrationRunner
from job_application_agent_langchain.infrastructure.file_store import EncryptedContentStore
from job_application_agent_langchain.infrastructure.security import (
    SensitiveJsonCodec,
    StaticKeyProvider,
)
from job_application_agent_langchain.web.app import app


def build_services(tmp_path):
    database = Database(tmp_path / "core.sqlite3")
    with database.connect() as connection:
        MigrationRunner().apply(connection)
    key = StaticKeyProvider(b"p" * 32)
    files = FileResourceService(database, EncryptedContentStore(tmp_path / "files", key))
    profiles = ProfileService(database, SensitiveJsonCodec(key))
    return database, files, profiles


def source(files: FileResourceService, name: str = "resume.pdf") -> str:
    return files.save(
        b"%PDF-1.4\nprofile source\n%%EOF",
        original_name=name,
        media_type="application/pdf",
    ).resource_id


def test_versions_are_immutable_switchable_and_encrypted(tmp_path):
    database, files, profiles = build_services(tmp_path)
    resource_id = source(files)
    first = profiles.create_profile(
        {"full_name": "Alice Private", "email": "first@example.test"},
        source_file_resource_id=resource_id,
    )
    second = profiles.create_version(
        first.profile_id,
        {"full_name": "Alice Private", "email": "second@example.test"},
        source_file_resource_id=resource_id,
        expected_version=1,
    )

    versions = profiles.list_versions(first.profile_id)
    assert [item.version_number for item in versions] == [2, 1]
    assert versions[1].fields["email"] == "first@example.test"
    assert profiles.list_profiles()[0]["active_version"].id == second.id

    activated = profiles.set_active_version(
        first.profile_id, first.id, expected_version=2
    )
    assert activated.id == first.id
    profiles.archive_version(first.profile_id, second.id, expected_version=3)
    profiles.delete_version(first.profile_id, second.id, expected_version=4)
    assert [item.id for item in profiles.list_versions(first.profile_id)] == [first.id]

    raw_database = (tmp_path / "core.sqlite3").read_bytes()
    assert b"Alice Private" not in raw_database
    assert b"first@example.test" not in raw_database
    with sqlite3.connect(database.path) as connection:
        marker, ciphertext = connection.execute(
            "SELECT profile_json, profile_ciphertext FROM profile_versions WHERE id = ?",
            (first.id,),
        ).fetchone()
    assert marker == "encrypted:v1"
    assert b"Alice Private" not in ciphertext


def test_change_proposal_accepts_only_selected_fields_atomically(tmp_path):
    _, files, profiles = build_services(tmp_path)
    old_source = source(files)
    new_source = files.save(
        b"%PDF-1.4\nupdated profile\n%%EOF",
        original_name="updated.pdf",
        media_type="application/pdf",
    ).resource_id
    first = profiles.create_profile(
        {"email": "old@example.test", "phone": "100", "city": "Shanghai"},
        source_file_resource_id=old_source,
    )
    proposal = profiles.create_change_proposal(
        first.profile_id,
        base_version_id=first.id,
        source_file_resource_id=new_source,
        proposed_fields={
            "email": "new@example.test",
            "phone": "200",
            "city": "Shanghai",
        },
    )
    assert set(proposal["changes"]) == {"email", "phone"}

    created = profiles.accept_change_proposal(
        proposal["id"], selected_fields=["email"], expected_version=1
    )
    assert created.version_number == 2
    assert created.fields == {
        "email": "new@example.test",
        "phone": "100",
        "city": "Shanghai",
    }
    assert profiles.get_change_proposal(proposal["id"])["status"] == "accepted"
    with pytest.raises(ProfileConflictError):
        profiles.accept_change_proposal(
            proposal["id"], selected_fields=["phone"], expected_version=2
        )
    assert len(profiles.list_versions(first.profile_id)) == 2


def test_profile_api_round_trip_and_conflict(tmp_path):
    _, files, profiles = build_services(tmp_path)
    resource_id = source(files)
    app.dependency_overrides[get_file_resource_service] = lambda: files
    app.dependency_overrides[get_profile_service] = lambda: profiles
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v2/profiles",
                json={
                    "fields": {"full_name": "API Candidate"},
                    "source_file_resource_id": resource_id,
                },
            )
            assert created.status_code == 201
            profile_id = created.json()["profile_id"]
            second = client.post(
                f"/api/v2/profiles/{profile_id}/versions",
                json={
                    "fields": {"full_name": "API Candidate", "city": "Hangzhou"},
                    "source_file_resource_id": resource_id,
                    "expected_version": 1,
                },
            )
            stale = client.post(
                f"/api/v2/profiles/{profile_id}/versions",
                json={
                    "fields": {"full_name": "stale"},
                    "source_file_resource_id": resource_id,
                    "expected_version": 1,
                },
            )
            listed = client.get("/api/v2/profiles")
    finally:
        app.dependency_overrides.clear()

    assert second.status_code == 201
    assert stale.status_code == 409
    assert listed.status_code == 200
    assert listed.json()[0]["active_version"]["version_number"] == 2
