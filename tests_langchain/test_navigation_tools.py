"""导航工具与登录检测工具测试。"""

import inspect
import pytest

from job_application_agent_langchain.agents.search import (
    get_search_tools,
    click_element_by_text_tool,
    get_visible_buttons_tool,
    check_login_status_tool,
)


def test_search_tools_include_new_tools():
    """get_search_tools 应包含三个新工具。"""
    tools = get_search_tools()
    tool_names = [t.name for t in tools]
    assert "click_element_by_text_tool" in tool_names
    assert "get_visible_buttons_tool" in tool_names
    assert "check_login_status_tool" in tool_names


def test_click_element_by_text_tool_is_async():
    """click_element_by_text_tool 应为 async 函数。"""
    assert inspect.iscoroutinefunction(click_element_by_text_tool.coroutine)


def test_get_visible_buttons_tool_is_async():
    """get_visible_buttons_tool 应为 async 函数。"""
    assert inspect.iscoroutinefunction(get_visible_buttons_tool.coroutine)


def test_check_login_status_tool_is_async():
    """check_login_status_tool 应为 async 函数。"""
    assert inspect.iscoroutinefunction(check_login_status_tool.coroutine)


def test_browser_automation_has_new_methods():
    """BrowserAutomation 应有新增的方法。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    assert hasattr(BrowserAutomation, "click_element_by_text")
    assert hasattr(BrowserAutomation, "get_visible_buttons")
    assert hasattr(BrowserAutomation, "check_login_status")


def test_request_user_login_in_tools():
    """request_user_login 应在 company agent 工具列表中。"""
    from job_application_agent_langchain.agents.company_agent import get_company_agent_tools
    tools = get_company_agent_tools()
    tool_names = [t.name for t in tools]
    assert "request_user_login" in tool_names


def test_request_user_login_in_emitter():
    """AgentEventEmitter 应有 request_user_login 方法。"""
    from job_application_agent_langchain.agent_events import AgentEventEmitter, CLIEmitter
    assert hasattr(AgentEventEmitter, "request_user_login")
    assert hasattr(CLIEmitter, "request_user_login")
