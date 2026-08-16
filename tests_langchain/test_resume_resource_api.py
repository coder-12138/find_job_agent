"""API tests for immutable encrypted resume resources."""

import fitz
from fastapi.testclient import TestClient

from job_application_agent_langchain.api_v2.dependencies import (
    get_file_resource_service,
)
from job_application_agent_langchain.application.file_resources import (
    FileResourceService,
)
from job_application_agent_langchain.infrastructure.database import (
    Database,
    MigrationRunner,
)
from job_application_agent_langchain.infrastructure.file_store import (
    EncryptedContentStore,
)
from job_application_agent_langchain.infrastructure.security import StaticKeyProvider
from job_application_agent_langchain.web.app import app


def build_service(tmp_path) -> FileResourceService:
    database = Database(tmp_path / "core.sqlite3")
    with database.connect() as connection:
        MigrationRunner().apply(connection)
    store = EncryptedContentStore(
        tmp_path / "files",
        StaticKeyProvider(b"r" * 32),
    )
    return FileResourceService(database, store)


def build_valid_pdf() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "Candidate Resume\nPython backend engineer\nProject and education experience",
        )
        return document.tobytes()
    finally:
        document.close()


def test_pdf_upload_is_encrypted_and_deduplicated(tmp_path):
    service = build_service(tmp_path)
    app.dependency_overrides[get_file_resource_service] = lambda: service
    pdf = build_valid_pdf()
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/v2/resumes",
                files={"file": ("candidate.pdf", pdf, "application/pdf")},
            )
            second = client.post(
                "/api/v2/resumes",
                files={"file": ("renamed.pdf", pdf, "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["resource_id"] == first.json()["resource_id"]
    encrypted = list((tmp_path / "files").rglob("*.blob"))
    assert len(encrypted) == 1
    assert pdf not in encrypted[0].read_bytes()


def test_non_pdf_upload_is_rejected_before_storage(tmp_path):
    service = build_service(tmp_path)
    app.dependency_overrides[get_file_resource_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v2/resumes",
                files={"file": ("candidate.txt", b"plain text", "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert not list((tmp_path / "files").rglob("*.blob"))
