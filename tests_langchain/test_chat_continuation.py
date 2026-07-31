"""对话续接与中断机制测试。"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from job_application_agent_langchain.agent_events import AgentEventEmitter
from job_application_agent_langchain.context import CompanyState
from job_application_agent_langchain.memory import AgentMemory
from job_application_agent_langchain.user_info.parser import UserInfo
from job_application_agent_langchain.web.session_manager import SessionManager


class MockEmitter(AgentEventEmitter):
    """测试用 MockEmitter。"""
    def __init__(self):
        self.events = []
    async def emit_progress(self, phase, message, company=""):
        self.events.append({"type": "progress", "phase": phase, "message": message})
    async def emit_screenshot(self, path, company=""):
        self.events.append({"type": "screenshot", "path": path})
    async def emit_log(self, level, message):
        self.events.append({"type": "log", "level": level, "message": message})
    async def request_confirmation(self, request_id, title, message, options):
        return options[0] if options else ""
    async def request_missing_fields(self, request_id, fields):
        return {}
    async def request_resume_review(self, request_id, original, polished):
        return polished
    async def request_position_selection(self, request_id, positions):
        return positions[:1] if positions else []
    async def request_user_login(self, request_id, login_url, message):
        return "logged_in"


def test_send_message_to_nonexistent_session():
    """发送消息到不存在的会话应返回错误。"""
    mgr = SessionManager()
    result = mgr.send_message("nonexistent", "hello")
    assert "error" in result or result.get("status") == "not_found"


def test_interrupt_nonexistent_session():
    """中断不存在的会话应返回错误。"""
    mgr = SessionManager()
    result = mgr.interrupt_and_restart("nonexistent", "hello")
    assert "error" in result or result.get("status") == "not_found"


def test_session_info_has_message_history_field():
    """SessionInfo 应有 message_history 与 pending_user_messages 字段。"""
    from job_application_agent_langchain.web.session_manager import SessionInfo
    info = SessionInfo(session_id="test", emitter=MagicMock())
    assert hasattr(info, "message_history")
    assert hasattr(info, "pending_user_messages")
    assert info.message_history == []
    assert info.pending_user_messages == []


def test_run_company_agent_accepts_message_history():
    """run_company_agent 应接受 message_history 参数。"""
    import inspect
    from job_application_agent_langchain.agents.company_agent import run_company_agent
    sig = inspect.signature(run_company_agent)
    assert "message_history" in sig.parameters


def test_cancel_session_stops_task_without_restart():
    """停止会话应取消当前任务并保留 cancelled 状态。"""
    from job_application_agent_langchain.web.emitter import WebEventEmitter
    from job_application_agent_langchain.web.session_manager import SessionInfo

    async def scenario():
        mgr = SessionManager()
        emitter = WebEventEmitter("cancel-test", mgr)
        info = SessionInfo(session_id="cancel-test", emitter=emitter)
        mgr.sessions[info.session_id] = info
        info.status = "running"
        info.task = asyncio.create_task(asyncio.sleep(60))

        result = await mgr.cancel_session(info.session_id)
        return info, result

    info, result = asyncio.run(scenario())
    assert result == {"status": "cancelled"}
    assert info.status == "cancelled"
    assert info.task.cancelled()
