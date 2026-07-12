"""集成测试与端到端验证（Task 7）。

覆盖内容：
1. 模块导入与装配验证：Web app、REST/WebSocket 路由、emitter 继承关系、
   orchestrator/company_agent 调用契约、resume_polish 模块可导入性、
   公司子 Agent 工具集排除旧版阻塞式 HITL 工具。
2. Web API 集成测试：使用 FastAPI TestClient 验证 REST 端点行为。
3. 记忆持久化集成测试：补充字段 → 保存 → 新实例加载 → 自动复用。
4. 邮件通知配置测试：save_settings / load_settings 往返一致性。
"""

import inspect
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path

# 在导入 app 前设置测试用 API Key，避免 Settings 校验相关副作用
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from job_application_agent_langchain.agent_events import AgentEventEmitter
from job_application_agent_langchain.agents.company_agent import (
    get_company_agent_tools,
    run_company_agent,
)
from job_application_agent_langchain.agents.orchestrator import run_job_application
from job_application_agent_langchain.memory import AgentMemory, load_memory, save_memory
from job_application_agent_langchain.resume_polish.jd_analyzer import analyze_jd
from job_application_agent_langchain.resume_polish.polisher import polish_resume
from job_application_agent_langchain.resume_polish.resume_matcher import (
    extract_relevant_content,
)
from job_application_agent_langchain.web.app import app
from job_application_agent_langchain.web.emitter import WebEventEmitter
from job_application_agent_langchain.web.schemas import NotificationSettings
from job_application_agent_langchain.web.settings_store import load_settings, save_settings


# ============================================================================
# 辅助函数
# ============================================================================


def _collect_all_paths(fastapi_app: FastAPI) -> set[str]:
    """收集 FastAPI app 所有注册的路由路径。

    FastAPI 在 include_router 时会用 _IncludedRouter 包装 APIRouter，
    其内部路由需通过 original_router.routes 访问。
    """
    paths: set[str] = set()
    for r in fastapi_app.routes:
        path = getattr(r, "path", None)
        if path is not None:
            paths.add(path)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for ir in getattr(orig, "routes", []):
                ip = getattr(ir, "path", None)
                if ip is not None:
                    paths.add(ip)
    return paths


# ============================================================================
# 1. 模块导入与装配验证
# ============================================================================


class TestModuleWiring:
    """验证各模块能正确导入并装配在一起。"""

    def test_app_is_fastapi_instance(self):
        """app 应为 FastAPI 实例。"""
        assert isinstance(app, FastAPI)

    def test_rest_routes_registered(self):
        """所有 REST 路由应已注册到 app。"""
        paths = _collect_all_paths(app)
        expected = {
            "/api/sessions",
            "/api/upload",
            "/api/settings/notifications",
            "/api/memory",
            "/api/sessions/{session_id}/confirm",
            "/api/health",
            "/api/recruitment-types",
            "/api/uploads",
            "/api/memory/{field_name}",
        }
        missing = expected - paths
        assert not missing, f"缺少路由: {missing}"

    def test_websocket_route_registered(self):
        """WebSocket 路由 /ws/sessions/{session_id} 应已注册。"""
        paths = _collect_all_paths(app)
        assert "/ws/sessions/{session_id}" in paths

    def test_web_emitter_is_subclass(self):
        """WebEventEmitter 应为 AgentEventEmitter 的子类。"""
        assert issubclass(WebEventEmitter, AgentEventEmitter)

    def test_run_job_application_signature(self):
        """run_job_application 应可调用且接受 (user_info, companies, parallel, emitter) 参数。"""
        assert callable(run_job_application)
        params = list(inspect.signature(run_job_application).parameters.keys())
        assert params == ["user_info", "companies", "parallel", "emitter"]

    def test_run_company_agent_callable(self):
        """run_company_agent 应可调用。"""
        assert callable(run_company_agent)

    def test_polish_resume_importable(self):
        """polish_resume 应可导入且可调用。"""
        assert callable(polish_resume)

    def test_analyze_jd_importable(self):
        """analyze_jd 应可导入且可调用。"""
        assert callable(analyze_jd)

    def test_extract_relevant_content_importable(self):
        """extract_relevant_content 应可导入且可调用。"""
        assert callable(extract_relevant_content)

    def test_company_agent_tools_exclude_blocking_legacy_tools(self):
        """公司子 Agent 工具集应排除旧版阻塞式 HITL 工具。

        旧版阻塞式工具（ask_user_for_field / notify_delivery_warning /
        ask_about_resume_parser）使用 input() 阻塞终端，与 Web UI 的
        emitter-based HITL 架构冲突，不应出现在 get_company_agent_tools() 结果中。
        新版 emitter HITL 工具（emit_progress / request_* 等）保留在工具集中，
        供 LLM 调用以与用户交互。
        """
        tools = get_company_agent_tools()
        tool_names = {t.name for t in tools}
        # 旧版阻塞式工具必须被排除
        excluded = {
            "ask_user_for_field",
            "notify_delivery_warning",
            "ask_about_resume_parser",
        }
        assert not (excluded & tool_names), (
            f"工具集中不应包含旧版阻塞式工具: {excluded & tool_names}"
        )
        # 工具集非空且包含核心搜索/表单工具
        assert len(tools) > 0
        assert "search_company_website" in tool_names
        assert "fill_form_field" in tool_names


# ============================================================================
# 2. Web API 集成测试（FastAPI TestClient）
# ============================================================================


@pytest.fixture(scope="module")
def client():
    """创建 TestClient 复用于模块内所有 API 测试。"""
    return TestClient(app)


class TestWebAPI:
    """使用 TestClient 验证 REST 端点行为。"""

    def test_health_endpoint(self, client):
        """GET /api/health 应返回 {"status": "ok"}。"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_recruitment_types_endpoint(self, client):
        """GET /api/recruitment-types 应返回含 recruitment_types 列表的 dict。"""
        resp = client.get("/api/recruitment-types")
        assert resp.status_code == 200
        data = resp.json()
        assert "recruitment_types" in data
        assert isinstance(data["recruitment_types"], list)
        assert len(data["recruitment_types"]) > 0

    def test_notification_settings_endpoint(self, client):
        """GET /api/settings/notifications 应返回 NotificationSettings 形状的 dict。"""
        resp = client.get("/api/settings/notifications")
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "email_enabled",
            "smtp_server",
            "smtp_port",
            "smtp_use_tls",
            "smtp_sender_email",
            "smtp_sender_password",
            "smtp_recipient_email",
        ):
            assert key in data, f"缺少字段: {key}"

    def test_memory_endpoint(self, client):
        """GET /api/memory 应返回 MemoryResponse 形状的 dict。"""
        resp = client.get("/api/memory")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("learned_fields", "source_user_info", "field_metadata"):
            assert key in data, f"缺少字段: {key}"

    def test_root_returns_html(self, client):
        """GET / 应返回 HTML（状态 200，content-type text/html）。"""
        resp = client.get("/")
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/html" in content_type

    def test_nonexistent_session_returns_404(self, client):
        """GET /api/sessions/nonexistent 应返回 404。"""
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404


# ============================================================================
# 3. 记忆持久化集成测试
# ============================================================================


class TestMemoryPersistence:
    """验证"补充字段 → 保存 → 重启后自动复用"的记忆持久化需求。"""

    def test_supplement_field_persists_across_restart(self):
        """补充缺失字段后保存，新实例加载时应能读到该字段值。

        模拟场景：首次投递补充身份证号 → 保存到记忆文件 →
        下次投递创建新 AgentMemory 实例从同一文件加载 → 自动复用。
        """
        # 使用临时文件避免污染项目数据
        fd, temp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            # 首次运行：补充缺失字段并保存
            memory1 = AgentMemory()
            memory1.set_field("id_number", "1234567890", reason="用户补充必填项")
            assert save_memory(memory1, temp_path) is True

            # 模拟重启：创建新实例从同一文件加载
            memory2 = load_memory(temp_path)
            # 验证字段已加载并可复用
            assert memory2.get_field("id_number") == "1234567890"
            assert "id_number" in memory2.learned_fields
            assert memory2.field_metadata["id_number"]["reason"] == "用户补充必填项"
        finally:
            os.unlink(temp_path)


# ============================================================================
# 4. 邮件通知配置测试
# ============================================================================


@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    """隔离 settings_store 文件路径、环境变量与 Settings 单例，测试后还原。"""
    import job_application_agent_langchain.web.settings_store as store
    from job_application_agent_langchain.config import Settings

    env_keys = [
        "EMAIL_NOTIFICATION_ENABLED",
        "SMTP_SERVER",
        "SMTP_PORT",
        "SMTP_USE_TLS",
        "SMTP_SENDER_EMAIL",
        "SMTP_SENDER_PASSWORD",
        "SMTP_RECIPIENT_EMAIL",
    ]
    saved_env = {k: os.environ.get(k) for k in env_keys}

    s = Settings()
    saved_attrs = {
        "email_notification_enabled": s.email_notification_enabled,
        "smtp_server": s.smtp_server,
        "smtp_port": s.smtp_port,
        "smtp_use_tls": s.smtp_use_tls,
        "smtp_sender_email": s.smtp_sender_email,
        "smtp_sender_password": s.smtp_sender_password,
        "smtp_recipient_email": s.smtp_recipient_email,
    }

    # 重定向 settings 文件到临时路径
    temp_settings_file = tmp_path / "notification_settings.json"
    monkeypatch.setattr(store, "SETTINGS_FILE", temp_settings_file)

    yield temp_settings_file

    # 还原环境变量
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    # 还原 Settings 单例属性
    for k, v in saved_attrs.items():
        setattr(s, k, v)


class TestNotificationSettings:
    """验证 save_settings / load_settings 的往返一致性。"""

    def test_settings_round_trip(self, isolated_settings):
        """保存通知设置后重新加载，值应保持一致。"""
        settings = NotificationSettings(
            email_enabled=True,
            smtp_server="smtp.test.com",
            smtp_port=465,
            smtp_use_tls=False,
            smtp_sender_email="sender@test.com",
            smtp_sender_password="secret",
            smtp_recipient_email="test@test.com",
        )

        assert save_settings(settings) is True
        # 验证文件确实写到了临时路径
        assert isolated_settings.exists()

        loaded = load_settings()
        assert loaded.email_enabled is True
        assert loaded.smtp_server == "smtp.test.com"
        assert loaded.smtp_port == 465
        assert loaded.smtp_use_tls is False
        assert loaded.smtp_sender_email == "sender@test.com"
        assert loaded.smtp_sender_password == "secret"
        assert loaded.smtp_recipient_email == "test@test.com"
