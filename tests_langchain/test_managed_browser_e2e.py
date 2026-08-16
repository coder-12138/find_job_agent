"""Real Playwright E2E against the deterministic local recruiting site."""

import asyncio
import socket
import threading
import time

import uvicorn

from job_application_agent_langchain.application.applications import ApplicationService
from job_application_agent_langchain.application.file_resources import FileResourceService
from job_application_agent_langchain.application.profiles import ProfileService
from job_application_agent_langchain.browser_runtime import BrowserCoordinator
from job_application_agent_langchain.infrastructure.database import Database, MigrationRunner
from job_application_agent_langchain.infrastructure.file_store import EncryptedContentStore
from job_application_agent_langchain.infrastructure.security import (
    SensitiveJsonCodec,
    StaticKeyProvider,
)
from tests_langchain.simulated_recruiting_site.app import app as simulated_app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_services(tmp_path, host: str):
    database = Database(tmp_path / "core.sqlite3")
    with database.connect() as connection:
        MigrationRunner().apply(connection)
    key = StaticKeyProvider(b"b" * 32)
    codec = SensitiveJsonCodec(key)
    files = FileResourceService(database, EncryptedContentStore(tmp_path / "files", key))
    profiles = ProfileService(database, codec)
    applications = ApplicationService(database, codec, allowed_hosts={host})
    resume_id = files.save(
        b"%PDF-1.4\nmanaged browser resume\n%%EOF",
        original_name="original-resume.pdf",
        media_type="application/pdf",
    ).resource_id
    profile = profiles.create_profile(
        {
            "full_name": "Browser Candidate",
            "email": "candidate@example.test",
            "phone": "18000000000",
        },
        source_file_resource_id=resume_id,
    )
    return files, applications, profile


def test_managed_browser_login_fill_manual_submit_and_receipt(tmp_path):
    port = free_port()
    config = uvicorn.Config(
        simulated_app, host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started

    async def scenario():
        host = "127.0.0.1"
        files, applications, profile = build_services(tmp_path, host)
        created = applications.create_application(
            source_url=f"http://{host}:{port}/jobs/demo/apply",
            profile_version_id=profile.id,
            title="Simulated Engineer",
        )
        prepared = applications.prepare_for_review(
            created.id,
            form_values=profile.fields,
            expected_version=1,
        )
        applications.approve_review(created.id, expected_version=prepared.row_version)
        coordinator = BrowserCoordinator(
            applications,
            files,
            tmp_path / "browser-profile",
            headless=True,
        )
        try:
            opened = await coordinator.open_application(created.id)
            assert "受管浏览器" in opened.message
            page = coordinator._pages[created.id]
            await page.locator('input[name="email"]').fill("login@example.test")
            await page.locator('button[type="submit"]').click()
            await page.wait_for_load_state("domcontentloaded")

            continued = await coordinator.continue_after_takeover(created.id)
            assert set(continued.filled_fields) >= {"full_name", "email", "phone", "resume"}
            assert applications.get_application(created.id).state == "awaiting_user_submit"
            assert await page.locator('input[name="full_name"]').input_value() == "Browser Candidate"
            assert await page.locator('input[name="phone"]').input_value() == "18000000000"
            assert await page.locator('[data-submission-state="submitted"]').count() == 0

            # The user, not the coordinator, performs this final click.
            await page.locator('[data-final-submit="true"]').click()
            await page.wait_for_load_state("domcontentloaded")
            observed = await coordinator.observe_submission(created.id)
            assert observed.state == "completed"
            assert applications.get_application(created.id).state == "submitted"
            hints = coordinator.list_hints(review_status="candidate")
            assert any(item["field_key"] == "email" for item in hints)
        finally:
            await coordinator.close()

    try:
        asyncio.run(scenario())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
