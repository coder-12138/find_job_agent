"""Web UI 临时 Agent API 配置测试。"""

import asyncio

import langchain_openai
import pytest
from fastapi.testclient import TestClient

from job_application_agent_langchain.web.app import app
from job_application_agent_langchain.web.schemas import ApiSettings
from job_application_agent_langchain.web.settings_store import (
    clear_api_settings,
    is_api_verified,
    load_api_settings,
    save_api_settings,
    verify_api_settings,
)


def test_api_settings_are_memory_only_and_secret_is_not_returned():
    clear_api_settings()
    status = save_api_settings(
        ApiSettings(
            api_base_url="https://example.test/v1",
            api_key="secret-test-key",
            model_name="test-model",
        )
    )

    assert status.api_key_configured is True
    assert status.verified is False
    assert "api_key" not in status.model_dump()
    assert load_api_settings().model_name == "test-model"

    cleared = clear_api_settings()
    assert cleared.api_key_configured is False
    assert cleared.verified is False


def test_verify_api_settings_enables_current_process(monkeypatch):
    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "secret-test-key"
            assert kwargs["base_url"] == "https://example.test/v1"
            assert kwargs["model"] == "test-model"

        async def ainvoke(self, message):
            assert "connection test" in message
            return object()

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)
    clear_api_settings()
    result = asyncio.run(
        verify_api_settings(
            ApiSettings(
                api_base_url="https://example.test/v1",
                api_key="secret-test-key",
                model_name="test-model",
            )
        )
    )

    assert result.success is True
    assert is_api_verified() is True
    assert load_api_settings().verified is True
    clear_api_settings()


def test_failed_new_verification_invalidates_previous_connection(monkeypatch):
    class FailingChatOpenAI:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, message):
            raise RuntimeError("invalid credentials")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FailingChatOpenAI)
    save_api_settings(
        ApiSettings(
            api_base_url="https://old.example.test/v1",
            api_key="old-secret",
            model_name="old-model",
        )
    )

    with pytest.raises(RuntimeError, match="连接验证失败"):
        asyncio.run(
            verify_api_settings(
                ApiSettings(
                    api_base_url="https://new.example.test/v1",
                    api_key="bad-secret",
                    model_name="new-model",
                )
            )
        )

    assert is_api_verified() is False
    assert load_api_settings().api_key_configured is False
    assert "invalid credentials" in load_api_settings().last_error


def test_verify_accepts_environment_assignment_lines(monkeypatch):
    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "secret-test-key"
            assert kwargs["base_url"] == "https://example.test/v1"
            assert kwargs["model"] == "test-model"

        async def ainvoke(self, message):
            return object()

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)
    result = asyncio.run(
        verify_api_settings(
            ApiSettings(
                api_base_url="OPENAI_API_BASE=https://example.test/v1",
                api_key="OPENAI_API_KEY=secret-test-key",
                model_name="OPENAI_MODEL=test-model",
            )
        )
    )

    assert result.success is True
    clear_api_settings()


def test_unified_production_api_mounts_agent_settings_and_versioned_core():
    clear_api_settings()
    client = TestClient(app)

    status_response = client.get("/api/settings/api")
    assert status_response.status_code == 200
    assert "api_key" not in status_response.json()

    capabilities = client.get("/api/v2/system/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["external_model_required"] is False
