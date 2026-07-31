"""Persistent application aggregate and transition safety."""

import pytest
from fastapi.testclient import TestClient

from job_application_agent_langchain.api_v2.dependencies import get_application_service
from job_application_agent_langchain.application.applications import (
    ApplicationConflictError,
    ApplicationService,
    UnsupportedJobUrlError,
)
from job_application_agent_langchain.application.file_resources import FileResourceService
from job_application_agent_langchain.application.profiles import ProfileService
from job_application_agent_langchain.infrastructure.database import Database, MigrationRunner
from job_application_agent_langchain.infrastructure.file_store import EncryptedContentStore
from job_application_agent_langchain.infrastructure.security import (
    SensitiveJsonCodec,
    StaticKeyProvider,
)
from job_application_agent_langchain.web.app import app


def build_services(tmp_path, *, allowed_hosts=None):
    database = Database(tmp_path / "core.sqlite3")
    with database.connect() as connection:
        MigrationRunner().apply(connection)
    key = StaticKeyProvider(b"a" * 32)
    codec = SensitiveJsonCodec(key)
    files = FileResourceService(database, EncryptedContentStore(tmp_path / "files", key))
    profiles = ProfileService(database, codec)
    applications = ApplicationService(
        database, codec, allowed_hosts=allowed_hosts or {"jobs.feishu.cn"}
    )
    resource_id = files.save(
        b"%PDF-1.4\nresume\n%%EOF",
        original_name="resume.pdf",
        media_type="application/pdf",
    ).resource_id
    profile = profiles.create_profile(
        {"full_name": "Private Candidate", "phone": "18000000000"},
        source_file_resource_id=resource_id,
    )
    return database, profiles, applications, profile


def test_application_happy_path_requires_verified_outcome(tmp_path):
    database, _, applications, profile = build_services(tmp_path)
    created = applications.create_application(
        source_url="https://jobs.feishu.cn/s/abc123",
        profile_version_id=profile.id,
        title="Backend Engineer",
        company="Example Co",
        description="Private JD snapshot",
    )
    assert created.state == "draft"
    assert created.profile_version_id == profile.id

    reviewed = applications.prepare_for_review(
        created.id,
        form_values={"full_name": "Private Candidate", "phone": "18000000000"},
        expected_version=1,
    )
    assert reviewed.state == "ready_for_review"
    approved = applications.approve_review(created.id, expected_version=2)
    assert approved.state == "awaiting_login"
    waiting = applications.transition(
        created.id,
        to_state="awaiting_user_submit",
        reason="form filled; user must inspect and submit",
        expected_version=3,
        actor_type="browser_worker",
    )
    assert waiting.state == "awaiting_user_submit"
    submitted = applications.record_submission_outcome(
        created.id,
        outcome="submitted",
        evidence={"summary": "success receipt detected", "url": "https://jobs.feishu.cn/success"},
        expected_version=4,
    )
    assert submitted.state == "submitted"
    assert submitted.submitted_at is not None
    with pytest.raises(ApplicationConflictError):
        applications.transition(
            created.id,
            to_state="draft",
            reason=None,
            expected_version=5,
        )

    events = applications.list_audit_events(created.id)
    assert [event["event_type"] for event in events].count("application.state_changed") == 4
    raw = (tmp_path / "core.sqlite3").read_bytes()
    assert b"Private Candidate" not in raw
    assert b"Private JD snapshot" not in raw


def test_url_allowlist_and_idempotency(tmp_path):
    _, _, applications, profile = build_services(tmp_path)
    with pytest.raises(UnsupportedJobUrlError):
        applications.create_application(
            source_url="https://example.com/jobs/1", profile_version_id=profile.id
        )
    first = applications.create_application(
        source_url="https://jobs.feishu.cn/s/one",
        profile_version_id=profile.id,
        idempotency_key="same-command",
    )
    second = applications.create_application(
        source_url="https://jobs.feishu.cn/s/other",
        profile_version_id=profile.id,
        idempotency_key="same-command",
    )
    assert second.id == first.id
    assert len(applications.list_applications()) == 1


def test_application_api_exposes_explicit_commands(tmp_path):
    _, _, applications, profile = build_services(tmp_path)
    app.dependency_overrides[get_application_service] = lambda: applications
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v2/applications",
                json={
                    "source_url": "https://jobs.feishu.cn/s/api",
                    "profile_version_id": profile.id,
                    "title": "QA Engineer",
                },
            )
            application_id = created.json()["id"]
            prepared = client.post(
                f"/api/v2/applications/{application_id}/prepare",
                json={"form_values": {"full_name": "Candidate"}, "expected_version": 1},
            )
            stale = client.post(
                f"/api/v2/applications/{application_id}/approve-review",
                json={"expected_version": 1},
            )
            listed = client.get("/api/v2/applications")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert prepared.status_code == 200
    assert prepared.json()["state"] == "ready_for_review"
    assert stale.status_code == 409
    assert listed.json()[0]["id"] == application_id
