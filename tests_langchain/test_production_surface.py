"""The production app unifies the original agent WebUI and versioned core."""

from fastapi.testclient import TestClient

from job_application_agent_langchain.web.app import app


def all_paths() -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        original = getattr(route, "original_router", None)
        for nested in getattr(original, "routes", []):
            nested_path = getattr(nested, "path", None)
            if nested_path:
                paths.add(nested_path)
    return paths


def test_original_webui_is_root_and_versioned_core_is_mounted():
    paths = all_paths()
    assert "/api/v2/profiles" in paths
    assert "/api/v2/applications" in paths
    assert "/api/v2/applications/{application_id}/browser/open" in paths
    assert "/api/sessions" in paths
    assert "/api/sessions/document" in paths
    assert "/api/settings/api" in paths
    assert "/ws/sessions/{session_id}" in paths

    with TestClient(app) as client:
        root = client.get("/")
        task_app = client.get("/app")
    assert root.status_code == 200
    assert "<title>简历自动投递 Agent</title>" in root.text
    assert task_app.status_code == 200
    assert "task-assets" in task_app.text
