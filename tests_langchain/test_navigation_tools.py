"""导航工具、快速失败与登录检测工具测试。"""

import asyncio
import inspect
import pytest

from job_application_agent_langchain.agents.search import (
    get_search_tools,
    search_company_website,
    navigate_and_find_positions,
    extract_matching_positions,
    click_element_by_text_tool,
    get_visible_buttons_tool,
    check_login_status_tool,
)
from job_application_agent_langchain.context import CompanyState


def test_search_tools_include_new_tools():
    """get_search_tools 应包含三个新工具。"""
    tools = get_search_tools()
    tool_names = [t.name for t in tools]
    assert "click_element_by_text_tool" in tool_names
    assert "get_visible_buttons_tool" in tool_names
    assert "check_login_status_tool" in tool_names
    assert "extract_matching_positions" in tool_names


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


def test_fatal_network_error_fails_without_retry():
    """连接重置等致命网络错误应立即停止，不消耗全部重试时间。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    class FailingPage:
        def __init__(self):
            self.calls = 0

        async def goto(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("Page.goto: net::ERR_CONNECTION_RESET")

    async def scenario():
        browser = BrowserAutomation()
        page = FailingPage()
        browser._page = page
        progress = []

        async def report(message):
            progress.append(message)

        success = await browser.navigate(
            "https://example.test/jobs",
            max_retries=3,
            progress_callback=report,
        )
        return browser, page, progress, success

    browser, page, progress, success = asyncio.run(scenario())
    assert success is False
    assert page.calls == 1
    assert "ERR_CONNECTION_RESET" in browser.last_navigation_error
    assert any("网站不可达" in message for message in progress)


def test_relative_position_url_is_resolved_before_navigation():
    """飞书招聘返回相对岗位链接时，应基于当前站点补全后再导航。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    class Page:
        def __init__(self):
            self.url = "https://xiaopeng.jobs.feishu.cn/398875"
            self.visited = []

        async def goto(self, url, **kwargs):
            self.visited.append(url)
            self.url = url
            return None

    async def scenario():
        browser = BrowserAutomation()
        page = Page()
        browser._page = page
        success = await browser.navigate(
            "/398875/position/7667137566747724083/detail",
            max_retries=1,
        )
        return success, page.visited

    success, visited = asyncio.run(scenario())
    assert success is True
    assert visited == [
        "https://xiaopeng.jobs.feishu.cn/398875/position/7667137566747724083/detail"
    ]


def test_err_aborted_does_not_reuse_previous_company_page():
    """跨公司导航被中止时，不能把上一家公司的页面误判为目标页加载成功。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    class Page:
        url = "https://careers.oppo.com/university/oppo/campus"

        async def goto(self, *args, **kwargs):
            raise RuntimeError("Page.goto: net::ERR_ABORTED")

    async def scenario():
        browser = BrowserAutomation()
        browser._page = Page()
        success = await browser.navigate(
            "https://xiaopeng.jobs.feishu.cn/398875",
            max_retries=1,
        )
        return success, browser.last_navigation_error

    success, error = asyncio.run(scenario())
    assert success is False
    assert "ERR_ABORTED" in error
    assert BrowserAutomation.navigation_reached_target(
        "https://xiaopeng.jobs.feishu.cn/398875/position/1/detail",
        "https://xiaopeng.jobs.feishu.cn/398875",
    )
    assert not BrowserAutomation.navigation_reached_target(
        "https://careers.oppo.com/university/oppo/campus",
        "https://xiaopeng.jobs.feishu.cn/398875",
    )


def test_navigation_timeout_can_continue_when_target_body_is_rendered():
    """招聘站长连接导致 load 超时时，目标域和正文都已就绪则不应重复导航。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    class Body:
        async def inner_text(self, timeout=0):
            return "已渲染的招聘岗位正文 " * 20

    class Page:
        url = "https://careers.oppo.com/university/oppo/campus"

        def __init__(self):
            self.calls = 0

        async def goto(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("Page.goto: Timeout 30000ms exceeded.")

        def locator(self, selector):
            assert selector == "body"
            return Body()

    async def scenario():
        browser = BrowserAutomation()
        page = Page()
        browser._page = page
        success = await browser.navigate(page.url, max_retries=2)
        return success, page.calls

    success, calls = asyncio.run(scenario())
    assert success is True
    assert calls == 1


def test_job_card_parser_filters_city_and_scores_keywords():
    """岗位卡片必须符合地区；关键词命中应被保留在推荐理由中。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    text = "智能驾驶算法工程师\n上海 | 校招 | 技术研发\n负责感知算法开发"
    card = BrowserAutomation.parse_job_card(
        text,
        "https://xiaopeng.jobs.feishu.cn/398875/position/1/detail",
        preferred_cities="上海,广州",
        job_keywords="算法 Python",
    )
    rejected = BrowserAutomation.parse_job_card(
        text,
        "https://xiaopeng.jobs.feishu.cn/398875/position/1/detail",
        preferred_cities="北京",
        job_keywords="算法",
    )

    assert card is not None
    assert card["location"] == "上海"
    assert "算法" in card["reason"]
    assert rejected is None


def test_job_card_parser_rejects_unrelated_title_even_if_jd_mentions_algorithm():
    """方向关键词应约束岗位标题，避免半导体岗位因正文偶然出现算法而混入。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    unrelated = BrowserAutomation.parse_job_card(
        "【27届校招】半导体工艺工程师\n上海 | 校招 | 芯片板块\n"
        "使用 Python 和算法分析芯片工艺数据",
        "https://xiaopeng.jobs.feishu.cn/398875/position/2/detail",
        preferred_cities="上海",
        job_keywords="AI算法 Agent开发",
    )

    assert unrelated is None

    ai_chip = BrowserAutomation.parse_job_card(
        "【27届校招】AI芯片编译器研发工程师\n上海 | 校招 | 芯片板块\n"
        "负责半导体编译器和 Python 工具链开发",
        "https://xiaopeng.jobs.feishu.cn/398875/position/3/detail",
        preferred_cities="上海",
        job_keywords="AI算法 Agent开发",
    )
    assert ai_chip is None


def test_manual_application_url_skips_search_engine(monkeypatch):
    """手动招聘链接存在时，即使 Agent 调用搜索工具也不应访问搜索引擎。"""
    from job_application_agent_langchain.agents import company_agent

    company = CompanyState(
        company_name="测试公司",
        application_url="https://example.test/careers",
    )
    monkeypatch.setattr(company_agent, "get_company_state", lambda: company)
    result = asyncio.run(
        search_company_website.coroutine(
            company_name=company.company_name,
            recruitment_type="校招",
        )
    )

    assert "跳过搜索引擎" not in result
    assert company.application_url in result


def test_detects_http_200_error_page():
    """正文为失效提示时，即使 HTTP 状态正常也应识别为错误页。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    class ErrorPage:
        async def title(self):
            return "Error!"

        async def inner_text(self, selector):
            return (
                "如果您看见该页，可能有以下几个原因：\n"
                "您访问的站点出错\n页面已经被移走\n您请求的页面不存在"
            )

    browser = BrowserAutomation()
    browser._page = ErrorPage()
    problem = asyncio.run(browser.detect_page_problem())

    assert problem
    assert "错误页" in problem or "移走" in problem


def test_search_redirect_urls_are_unwrapped():
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    duck_url = (
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fcareers.example.com%2Fcampus"
    )
    assert (
        BrowserAutomation.normalize_search_result_url(duck_url)
        == "https://careers.example.com/campus"
    )
    assert (
        BrowserAutomation.normalize_search_result_url(
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fcareers.oppo.com%2F"
        )
        == "https://careers.oppo.com/"
    )
    assert BrowserAutomation.normalize_search_result_url(
        "https://www.bing.com/search?q=test"
    ) == ""
    assert BrowserAutomation.normalize_search_result_url(
        "https://careers.oppo.com/university/oppo/404"
    ) == ""


def test_bad_candidate_page_automatically_falls_back(monkeypatch):
    """第一个候选为 200 错误页时，应自动尝试第二个招聘链接。"""
    from job_application_agent_langchain.agents import company_agent, search as search_module

    bad_url = "https://bad.example.test/jobs"
    good_url = "https://careers.example.test/jobs"
    company = CompanyState(
        company_name="测试公司",
        candidate_urls=[bad_url, good_url],
    )

    class FakeBrowser:
        def __init__(self):
            self.calls = []
            self.current_url = ""
            self.last_navigation_error = ""

        async def navigate(self, url, **kwargs):
            self.calls.append(url)
            self.current_url = url
            return True

        def is_obvious_error_url(self, url):
            return url.endswith("/404")

        async def detect_page_problem(self):
            return "页面不存在" if self.current_url == bad_url else ""

        async def wait_for_page_settle(self, timeout_ms=6000):
            return None

        async def get_page_text(self):
            return "校园招聘 软件工程师 北京"

        async def get_current_url(self):
            return self.current_url

        async def click_element_by_text(self, text):
            return {"success": False}

        async def get_visible_buttons(self):
            return []

        async def find_links(self, text=""):
            return []

    fake_browser = FakeBrowser()

    async def get_browser():
        return fake_browser

    monkeypatch.setattr(search_module, "_get_browser", get_browser)
    monkeypatch.setattr(company_agent, "get_company_state", lambda: company)
    result = asyncio.run(
        navigate_and_find_positions.coroutine(
            website_url=bad_url,
            job_keywords="软件工程师",
            preferred_cities="北京",
            recruitment_type="校招",
        )
    )

    assert fake_browser.calls == [bad_url, good_url]
    assert good_url in result
    assert bad_url in company.rejected_urls
