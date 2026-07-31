"""Stage 0 contract tests for the isolated rebuilt core."""

import sqlite3

from fastapi.testclient import TestClient

from job_application_agent_langchain.infrastructure.database import MigrationRunner
from job_application_agent_langchain.web.app import app as production_app
from tests_langchain.simulated_recruiting_site.app import app as simulated_site


def test_migrations_are_versioned_and_idempotent():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    runner = MigrationRunner()

    version = runner.apply(connection)
    assert version >= 4
    assert runner.apply(connection) == version

    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "schema_migrations",
        "candidate_profiles",
        "profile_versions",
        "file_resources",
        "audit_events",
    } <= tables
    assert connection.execute(
        "SELECT COUNT(*) AS count FROM schema_migrations"
    ).fetchone()["count"] == version
    connection.close()


def test_v2_health_and_capabilities_are_independent_of_model_api():
    with TestClient(production_app) as client:
        health = client.get("/api/v2/health")
        capabilities = client.get("/api/v2/system/capabilities")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["core"] == "ready"
    assert health.json()["schema_version"] >= 4
    assert capabilities.status_code == 200
    assert capabilities.json()["external_model_required"] is False
    assert capabilities.json()["formal_platforms"] == ["feishu_recruiting"]


def test_task_shell_is_the_production_root():
    with TestClient(production_app) as client:
        root = client.get("/")
        task_ui = client.get("/app")

    assert root.status_code == 200
    assert task_ui.status_code == 200
    assert '<div id="root"></div>' in root.text
    assert '<div id="root"></div>' in task_ui.text


def test_simulated_site_requires_login_and_returns_verifiable_receipt():
    with TestClient(simulated_site, follow_redirects=False) as client:
        protected = client.get("/jobs/demo/apply")
        assert protected.status_code == 303
        assert protected.headers["location"].startswith("/login")

        logged_in = client.post(
            "/login",
            data={"email": "candidate@example.test", "return_to": "/jobs/demo/apply"},
        )
        assert logged_in.status_code == 303

        form = client.get("/jobs/demo/apply")
        assert form.status_code == 200
        assert 'data-final-submit="true"' in form.text

        submitted = client.post(
            "/jobs/demo/submit",
            data={
                "full_name": "测试候选人",
                "email": "candidate@example.test",
                "phone": "13800000000",
                "outcome": "success",
            },
        )
        assert submitted.status_code == 200
        assert 'data-submission-receipt="true"' in submitted.text
        assert "SIM-DEMO-0001" in submitted.text


def test_simulated_site_can_model_unknown_submission_result():
    with TestClient(simulated_site, follow_redirects=False) as client:
        client.post(
            "/login",
            data={"email": "candidate@example.test", "return_to": "/jobs/demo/apply"},
        )
        response = client.post(
            "/jobs/demo/submit",
            data={
                "full_name": "测试候选人",
                "email": "candidate@example.test",
                "phone": "13800000000",
                "outcome": "unknown",
            },
        )

    assert response.status_code == 202
    assert 'data-submission-state="unknown"' in response.text
    assert "data-submission-receipt" not in response.text
