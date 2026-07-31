"""搜索阶段的循环上限、候选质量与事件序列化测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from job_application_agent_langchain.agents.company_agent import (
    SearchPhaseTimeoutError,
    _deterministic_presearch_url,
    _feishu_presearch_url,
    _invoke_agent_with_search_watchdog,
    _parse_structured_positions,
)
from job_application_agent_langchain.agents.search import (
    _DuckDuckGoResultParser,
    _candidate_score,
    _looks_like_recruitment_page,
    search_company_website,
)
from job_application_agent_langchain.context import CompanyState
from job_application_agent_langchain.web.session_manager import (
    SessionInfo,
    SessionManager,
)


class RecordingEmitter:
    def __init__(self):
        self.events = []

    async def emit_progress(self, phase, message, company=""):
        self.events.append((phase, message, company))


def test_feishu_navigation_result_is_parsed_without_llm():
    positions = [
        {
            "title": "大模型算法工程师",
            "location": "上海",
            "url": "https://xiaopeng.jobs.feishu.cn/398875/position/1/detail",
        }
    ]
    result = (
        "当前页面: https://xiaopeng.jobs.feishu.cn/398875\n"
        "结构化匹配岗位（可直接用于 report_recommended_positions，无需逐个打开详情）：\n"
        + __import__("json").dumps(positions, ensure_ascii=False)
        + "\n"
    )

    assert _parse_structured_positions(result) == positions


def test_xiaopeng_uses_deterministic_feishu_presearch():
    explicit = CompanyState(
        company_name="测试公司",
        application_url="https://example.jobs.feishu.cn/123",
    )
    xiaopeng = CompanyState(company_name="小鹏汽车")

    assert _feishu_presearch_url(explicit) == explicit.application_url
    assert _feishu_presearch_url(xiaopeng) == (
        "https://xiaopeng.jobs.feishu.cn/398875"
    )


def test_oppo_uses_deterministic_presearch():
    oppo = CompanyState(company_name="oppo")
    assert _deterministic_presearch_url(oppo) == (
        "https://careers.oppo.com/university/oppo/campus"
    )


def test_generic_brand_homepage_is_not_a_recruitment_candidate():
    generic = {"text": "OPPO Official Site", "href": "https://www.oppo.com/en/"}
    careers = {"text": "OPPO招聘", "href": "https://careers.oppo.com/"}

    assert _candidate_score(generic, "oppo", ["校招"]) < 0
    assert _candidate_score(careers, "oppo", ["校招"]) > 0
    assert not _looks_like_recruitment_page(
        generic["href"], "OPPO Find N Series Smartphones", "校招"
    )
    assert _looks_like_recruitment_page(
        careers["href"], "欢迎加入我们", "校招"
    )


def test_duckduckgo_html_parser_extracts_result_links_only():
    parser = _DuckDuckGoResultParser()
    parser.feed(
        """
        <a href="/settings">settings</a>
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcareers.oppo.com%2F">
          OPPO 招聘
        </a>
        """
    )
    assert parser.results == [
        {
            "text": "OPPO 招聘",
            "href": "//duckduckgo.com/l/?uddg=https%3A%2F%2Fcareers.oppo.com%2F",
        }
    ]


def test_search_tool_prefers_http_results_and_filters_generic_homepage(monkeypatch):
    from job_application_agent_langchain.agents import company_agent, search as search_module

    company = CompanyState(company_name="oppo")

    async def fake_http_search(query):
        return [
            {"text": "OPPO Official Site", "href": "https://www.oppo.com/en/"},
            {"text": "OPPO招聘 - 校园招聘", "href": "https://careers.oppo.com/campus"},
        ]

    async def browser_must_not_start():
        raise AssertionError("HTTP 搜索成功时不应启动搜索引擎浏览器")

    monkeypatch.setattr(company_agent, "get_company_state", lambda: company)
    monkeypatch.setattr(search_module, "_search_links_via_http", fake_http_search)
    monkeypatch.setattr(search_module, "_get_browser", browser_must_not_start)

    result = asyncio.run(
        search_company_website.coroutine("oppo", "校招")
    )

    assert company.candidate_urls == ["https://careers.oppo.com/campus"]
    assert "careers.oppo.com" in result
    assert "www.oppo.com/en" not in result


def test_search_watchdog_cancels_never_finishing_agent():
    class NeverAgent:
        def __init__(self):
            self.config = None
            self.cancelled = False

        async def ainvoke(self, payload, config=None):
            self.config = config
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def scenario():
        agent = NeverAgent()
        company = CompanyState(company_name="测试公司")
        emitter = RecordingEmitter()
        settings = SimpleNamespace(
            agent_recursion_limit=7,
            search_phase_timeout=0.05,
        )
        with pytest.raises(SearchPhaseTimeoutError, match="自动中断"):
            await _invoke_agent_with_search_watchdog(
                agent,
                [HumanMessage(content="start")],
                company,
                emitter,
                settings,
            )
        return agent

    agent = asyncio.run(scenario())
    assert agent.cancelled is True
    assert agent.config == {"recursion_limit": 7}


def test_websocket_events_convert_langchain_messages_to_json():
    async def scenario():
        manager = SessionManager()
        websocket = AsyncMock()
        info = SessionInfo(session_id="safe-json", emitter=AsyncMock())
        info.websocket = websocket
        manager.sessions[info.session_id] = info

        await manager.push_event(
            info.session_id,
            {
                "type": "session_complete",
                "results": {"messages": [HumanMessage(content="hello")]},
            },
        )
        return websocket

    websocket = asyncio.run(scenario())
    sent = websocket.send_json.await_args.args[0]
    assert sent["results"]["messages"] == [
        {"type": "human", "content": "hello"}
    ]
