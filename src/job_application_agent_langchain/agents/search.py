import asyncio
import json
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from job_application_agent_langchain.context import RECRUITMENT_TYPE_KEYWORDS
from job_application_agent_langchain.tools.notify import notify_user
from job_application_agent_langchain.utils import sanitize_agent_name


class _DuckDuckGoResultParser(HTMLParser):
    """只提取 DuckDuckGo HTML 结果标题链接，不执行页面脚本。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href = ""
        self._text_parts: list[str] = []
        self._inside_result = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if "result__a" in classes:
            self._inside_result = True
            self._href = attributes.get("href") or ""
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._inside_result:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._inside_result:
            return
        text = " ".join("".join(self._text_parts).split())
        if self._href and text:
            self.results.append({"text": text, "href": self._href})
        self._inside_result = False
        self._href = ""
        self._text_parts = []


async def _search_links_via_http(query: str) -> list[dict[str, str]]:
    """用轻量 HTTP 获取搜索结果，避开浏览器自动化页面的降级与验证码。"""
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        timeout=httpx.Timeout(12),
    ) as client:
        response = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
        )
        response.raise_for_status()

    parser = _DuckDuckGoResultParser()
    parser.feed(response.text)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in parser.results:
        href = BrowserAutomation.normalize_search_result_url(link["href"])
        if href and href not in seen:
            seen.add(href)
            results.append({"text": link["text"], "href": href})
        if len(results) >= 12:
            break
    return results


def _candidate_score(
    link: dict[str, str],
    company_name: str,
    recruitment_keywords: list[str],
) -> int:
    """只给有明确招聘信号的搜索结果打分，避免退化到普通公司主页。"""
    text = link.get("text", "")
    href = link.get("href", "")
    blob = f"{text} {href}".lower()
    host = urlparse(href).netloc.lower()
    signals = [
        *recruitment_keywords,
        "招聘", "职位", "岗位", "加入我们",
        "career", "careers", "job", "jobs", "join us", "campus", "recruit",
    ]
    matched = [signal for signal in signals if signal.lower() in blob]
    if not matched:
        return -1

    score = min(len(matched), 4) * 3
    company_token = company_name.lower().strip()
    if company_token and company_token in host:
        score += 8
    elif company_token and company_token in blob:
        score += 3
    if any(token in host for token in ("career", "job", "recruit", "campus")):
        score += 5
    return score


def _looks_like_recruitment_page(
    url: str,
    page_text: str,
    recruitment_type: str,
) -> bool:
    """拒绝被搜索结果误导到普通品牌官网首页。"""
    host = urlparse(url).netloc.lower()
    sample = f"{url} {page_text[:3500]}".lower()
    signals = [
        *RECRUITMENT_TYPE_KEYWORDS.get(recruitment_type, []),
        "招聘", "职位", "岗位", "加入我们",
        "career", "careers", "job", "jobs", "join us", "campus", "recruit",
    ]
    return (
        any(token in host for token in ("career", "job", "recruit", "campus"))
        or any(signal.lower() in sample for signal in signals)
    )


async def _get_browser():
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    from job_application_agent_langchain.config import Settings

    settings = Settings()
    return await BrowserAutomation.get_shared(
        headless=settings.browser_headless,
        timeout=settings.browser_timeout,
    )


async def _emit_search_progress(message: str) -> None:
    """把浏览器搜索/重试状态实时推送到 CLI 或 Web UI。"""
    from job_application_agent_langchain.agents.company_agent import (
        get_company_emitter,
        get_company_state,
    )

    emitter = get_company_emitter()
    company = get_company_state()
    if emitter is not None:
        await emitter.emit_progress(
            "search",
            message,
            company.company_name if company else "",
        )


async def _abort_search(reason: str) -> str:
    """记录不可恢复的搜索错误，阻止 LLM 反复搜索。"""
    from job_application_agent_langchain.agents.company_agent import get_company_state

    company = get_company_state()
    if company is not None:
        company.status = "search_failed"
        company.error_message = reason
    await _emit_search_progress(f"搜索已停止：{reason}")
    return f"SEARCH_ABORTED|{reason}"


@tool
async def search_company_website(
    company_name: str,
    recruitment_type: str = "校招",
) -> str:
    """搜索公司的招聘官网。使用搜索引擎查找目标公司的招聘官方网站。

    Args:
        company_name: 公司名称
        recruitment_type: 投递类型（校招/社招/日常实习/暑期实习（转正实习）），默认校招
    """
    try:
        from job_application_agent_langchain.agents.company_agent import get_company_state
        from job_application_agent_langchain.config import Settings

        company = get_company_state()
        if company is not None and company.status == "search_failed":
            return f"SEARCH_ABORTED|{company.error_message or '本次搜索已经失败，不再重试'}"
        if company is not None and company.application_url:
            await _emit_search_progress(
                f"已使用手动招聘链接，跳过搜索引擎：{company.application_url}"
            )
            return f"已提供招聘链接，请直接访问：\n- {company.company_name}: {company.application_url}"
        if company is not None and company.candidate_urls:
            available = [
                url for url in company.candidate_urls
                if url not in company.rejected_urls
            ]
            if available:
                await _emit_search_progress("复用本次已找到的招聘候选链接")
                return "已缓存以下招聘链接，请勿重复搜索：\n" + "\n".join(
                    f"- {url}" for url in available
                )

        settings = Settings()
        search_query = f"{company_name} {recruitment_type} 官网 招聘"
        await _emit_search_progress(
            f"正在搜索「{company_name}」招聘官网，最长等待 {settings.search_total_timeout} 秒"
        )

        links: list[dict[str, str]] = []
        browser = None
        try:
            async with asyncio.timeout(settings.search_total_timeout):
                await _emit_search_progress("正在通过轻量搜索接口获取招聘链接")
                try:
                    links = await _search_links_via_http(search_query)
                except Exception as exc:
                    await _emit_search_progress(
                        f"轻量搜索接口不可用（{type(exc).__name__}），切换浏览器搜索"
                    )
                if not links:
                    browser = await _get_browser()
                    page_text = await browser.search_and_navigate(
                        search_query,
                        progress_callback=_emit_search_progress,
                    )
                    if page_text:
                        links = await browser.get_search_result_links()
        except TimeoutError:
            return await _abort_search(
                f"搜索招聘官网超过 {settings.search_total_timeout} 秒"
            )

        if not links:
            detail = (
                browser.last_navigation_error
                if browser is not None and browser.last_navigation_error
                else "搜索源没有返回真实结果"
            )
            return await _abort_search(detail)

        keywords = RECRUITMENT_TYPE_KEYWORDS.get(recruitment_type, ["招聘"])
        if company is not None:
            links = [
                link for link in links
                if link.get("href", "") not in company.rejected_urls
            ]
        scored_links = [
            (_candidate_score(link, company_name, keywords), link)
            for link in links
        ]
        selected_links = [
            link
            for score, link in sorted(
                scored_links,
                key=lambda item: item[0],
                reverse=True,
            )
            if score >= 0
        ][:8]
        if company is not None:
            company.candidate_urls = [
                link["href"]
                for link in selected_links
                if link["href"] not in company.rejected_urls
            ]

        if not selected_links:
            return await _abort_search(
                "搜索引擎没有返回带明确招聘标识的链接；为避免误入普通官网，请手动填写招聘网址"
            )
        results = [
            f"- {link.get('text', '')}: {link.get('href', '')}"
            for link in selected_links
        ]
        await _emit_search_progress(f"已找到 {len(results)} 个候选招聘链接")
        return "搜索到以下链接:\n" + "\n".join(results)
    except Exception as e:
        return await _abort_search(str(e))


@tool
async def navigate_and_find_positions(
    website_url: str,
    job_keywords: str,
    preferred_cities: str,
    recruitment_type: str = "校招",
) -> str:
    """导航到招聘官网，查找符合条件的岗位信息。根据投递类型进入对应入口。

    Args:
        website_url: 招聘官网URL
        job_keywords: 岗位关键词（如：AI算法、agent开发）
        preferred_cities: 期望工作城市，多个城市用逗号分隔
        recruitment_type: 投递类型（校招/社招/日常实习/暑期实习（转正实习）），默认校招
    """
    try:
        from job_application_agent_langchain.agents.company_agent import get_company_state
        from job_application_agent_langchain.config import Settings

        company = get_company_state()
        if company is not None and company.status == "search_failed":
            return f"SEARCH_ABORTED|{company.error_message or '本次搜索已经失败，不再重试'}"

        if not website_url.startswith(("http://", "https://")):
            return await _abort_search(f"招聘链接格式无效：{website_url}")

        browser = await _get_browser()
        settings = Settings()
        manual_url = (company.application_url.strip() if company else "")
        candidates = [manual_url] if manual_url else [website_url]
        if company is not None and not manual_url:
            candidates.extend(company.candidate_urls)
        candidates = list(
            dict.fromkeys(
                url for url in candidates
                if url.startswith(("http://", "https://"))
                and (company is None or url not in company.rejected_urls)
                and not browser.is_obvious_error_url(url)
            )
        )[:3]

        selected_url = ""
        failure_reasons = []
        try:
            async with asyncio.timeout(settings.search_total_timeout):
                for index, candidate_url in enumerate(candidates, 1):
                    await _emit_search_progress(
                        f"正在打开招聘页面（候选 {index}/{len(candidates)}）：{candidate_url}"
                    )
                    success = await browser.navigate(
                        candidate_url,
                        progress_callback=_emit_search_progress,
                    )
                    problem = ""
                    if success:
                        await _emit_search_progress(
                            f"页面已打开，等待动态内容加载（最多 {settings.page_settle_timeout / 1000:g} 秒）"
                        )
                        await browser.wait_for_page_settle(
                            settings.page_settle_timeout
                        )
                        problem = await browser.detect_page_problem()
                        if not problem:
                            landed_url = await browser.get_current_url()
                            landed_text = await browser.get_page_text()
                            if not _looks_like_recruitment_page(
                                landed_url,
                                landed_text,
                                recruitment_type,
                            ):
                                problem = (
                                    "页面缺少招聘、职位或加入我们等标识，"
                                    "疑似普通品牌官网"
                                )
                    if success and not problem:
                        selected_url = candidate_url
                        break

                    detail = problem or browser.last_navigation_error or "页面无法访问"
                    failure_reasons.append(f"{candidate_url}（{detail}）")
                    if company is not None and candidate_url not in company.rejected_urls:
                        company.rejected_urls.append(candidate_url)
                    await _emit_search_progress(
                        f"候选链接不可用：{detail}，将尝试下一个链接"
                    )
        except TimeoutError:
            return await _abort_search(
                f"尝试招聘页面超过 {settings.search_total_timeout} 秒"
            )
        if not selected_url:
            prefix = "手动提供的招聘链接不可用" if manual_url else "候选招聘链接均不可用"
            details = "；".join(failure_reasons) or website_url
            return await _abort_search(f"{prefix}：{details}")

        page_text = await browser.get_page_text()
        page_url = await browser.get_current_url()

        # 自动尝试点击常见入口按钮
        ENTRY_BUTTON_TEXTS = [
            "即刻投递", "开始投递", "投递简历", "查看职位", "开始找工作",
            "校招岗位", "校园招聘", "进入投递", "我要投递", "投递入口",
            "搜索职位", "职位搜索", "校招入口", "网申入口",
        ]
        clicked_button = ""
        current_host = (urlparse(page_url).hostname or "").lower()
        current_path = urlparse(page_url).path.rstrip("/")
        if current_host == "careers.oppo.com" and current_path.endswith("/campus"):
            await _emit_search_progress(
                "正在悬停目标招聘类型卡片并点击该卡片的“马上启程”"
            )
            oppo_entry = await browser.enter_oppo_campus_section(
                recruitment_type,
                timeout_ms=settings.browser_interaction_timeout,
            )
            if oppo_entry.get("success"):
                clicked_button = f"{oppo_entry.get('section', '应届生')} - 马上启程"
                if oppo_entry.get("used_fallback"):
                    await _emit_search_progress(
                        "悬停点击未及时完成路由切换，已使用该入口对应的岗位列表地址并验证成功"
                    )
            else:
                return await _abort_search(
                    f"OPPO 校招入口点击失败：{oppo_entry.get('error', '未知错误')}"
                )
        else:
            try:
                async with asyncio.timeout(15):
                    for btn_text in ENTRY_BUTTON_TEXTS:
                        try:
                            result = await browser.click_element_by_text(
                                btn_text,
                                timeout_ms=settings.browser_interaction_timeout,
                            )
                            if result["success"]:
                                clicked_button = btn_text
                                break
                        except Exception:
                            continue
            except TimeoutError:
                await _emit_search_progress("自动查找招聘入口超过 15 秒，停止继续点击")

        # 如果自动点击成功，重新获取页面信息
        if clicked_button:
            click_problem = await browser.detect_page_problem()
            if click_problem:
                return await _abort_search(
                    f"点击「{clicked_button}」后进入无效页面：{click_problem}"
                )
            page_text = await browser.get_page_text()
            page_url = await browser.get_current_url()
            await _emit_search_progress(f"已进入招聘入口：{clicked_button}")

        # 飞书招聘等列表页会一次返回大量岗位卡片。先确定性地按地区筛选并按
        # 关键词排序，避免让 LLM 逐个打开详情页导致循环或耗尽搜索看门狗。
        structured_positions = []
        if hasattr(browser, "extract_matching_job_cards"):
            cities = browser._split_filter_terms(preferred_cities)
            clicked_cities = []
            current_host = (urlparse(page_url).hostname or "").lower()
            if (
                current_host == "careers.oppo.com"
                and "/campus/post" in urlparse(page_url).path
                and hasattr(browser, "extract_oppo_job_cards")
            ):
                for city in cities:
                    city_label = city if city.endswith("市") else f"{city}市"
                    await _emit_search_progress(f"正在勾选并验证 OPPO 城市筛选：{city_label}")
                    selection = await browser.select_oppo_checkbox(
                        city_label,
                        timeout_ms=settings.browser_interaction_timeout,
                    )
                    if selection.get("selected"):
                        clicked_cities.append(city)
                    else:
                        await _emit_search_progress(
                            f"OPPO 城市筛选未生效：{city_label}（{selection.get('error', '未知原因')}）"
                        )
                keyword_text = (job_keywords or "").lower()
                category = ""
                if any(
                    marker in keyword_text
                    for marker in ("算法", "ai", "人工智能", "大模型", "agent", "智能体")
                ):
                    category = "AI/算法类"
                elif any(
                    marker in keyword_text
                    for marker in ("软件", "开发", "后端", "前端")
                ):
                    category = "软件类"
                if category:
                    await _emit_search_progress(f"正在勾选并验证 OPPO 职位类别：{category}")
                    category_result = await browser.select_oppo_checkbox(
                        category,
                        timeout_ms=settings.browser_interaction_timeout,
                    )
                    if not category_result.get("selected"):
                        await _emit_search_progress(
                            f"OPPO 职位类别筛选未生效：{category}"
                        )
                if clicked_cities:
                    await _emit_search_progress(
                        f"已确认 OPPO 城市复选框选中：{'、'.join(clicked_cities)}"
                    )
                structured_positions = await browser.extract_oppo_job_cards(
                    job_keywords=job_keywords,
                    preferred_cities=preferred_cities,
                    limit=12,
                )
            else:
                if cities and hasattr(browser, "select_city_filter"):
                    for city in cities:
                        await _emit_search_progress(f"正在勾选并验证城市筛选：{city}")
                        selection = await browser.select_city_filter(
                            city,
                            timeout_ms=settings.browser_interaction_timeout,
                        )
                        if selection.get("selected"):
                            clicked_cities.append(city)
                        else:
                            await _emit_search_progress(
                                f"城市筛选未生效：{city}（{selection.get('error', '未知原因')}）"
                            )
                    if clicked_cities:
                        await _emit_search_progress(
                            f"已确认城市复选框选中：{'、'.join(clicked_cities)}"
                        )
                structured_positions = await browser.extract_matching_job_cards(
                    job_keywords=job_keywords,
                    preferred_cities=preferred_cities,
                    limit=12,
                )
            if structured_positions:
                await _emit_search_progress(
                    f"已按地区和岗位方向严格筛出 {len(structured_positions)} 个岗位"
                )

        # 构造入口按钮点击说明
        if clicked_button:
            entry_info = f"已自动点击入口按钮: {clicked_button}\n"
        else:
            entry_info = "未找到常见入口按钮\n"
            # 如果未点击成功，列出所有可见按钮
            try:
                visible_buttons = await browser.get_visible_buttons()
                if visible_buttons:
                    entry_info += "页面可见按钮:\n"
                    for btn in visible_buttons[:10]:
                        entry_info += f"- [{btn['tag']}] {btn['text']}\n"
            except Exception:
                pass

        type_keywords = RECRUITMENT_TYPE_KEYWORDS.get(recruitment_type, ["校招"])
        entry_links = []
        for keyword in type_keywords:
            found = await browser.find_links(keyword)
            entry_links.extend(found)
            if entry_links:
                break

        link_info = ""
        for link in entry_links[:5]:
            link_info += f"- {link['text']}: {link['href']}\n"

        type_label = recruitment_type
        positions_info = ""
        if structured_positions:
            positions_info = (
                "\n结构化匹配岗位（可直接用于 report_recommended_positions，"
                "无需逐个打开详情）：\n"
                + json.dumps(structured_positions, ensure_ascii=False)
                + "\n"
            )
        elif preferred_cities:
            positions_info = (
                f"\n未在当前岗位列表中找到地区为“{preferred_cities}”的岗位。"
                "不要推荐其他地区；可向用户说明当前无地区匹配结果。\n"
            )
        return (
            f"当前页面: {page_url}\n"
            f"投递类型: {type_label}\n"
            f"{entry_info}"
            f"页面内容摘要: {page_text[:2000]}\n"
            f"{type_label}相关链接:\n{link_info if link_info else f'未找到{type_label}入口链接'}"
            f"{positions_info}"
        )
    except Exception as e:
        return await _abort_search(str(e))


@tool
async def find_max_positions(
    website_url: str,
    recruitment_type: str = "校招",
) -> str:
    """查找该公司可投递的最大岗位数。通常在招聘官网的FAQ或说明页面中。

    Args:
        website_url: 招聘官网URL
        recruitment_type: 投递类型（校招/社招/日常实习/暑期实习（转正实习）），默认校招
    """
    try:
        browser = await _get_browser()

        faq_keywords = ["FAQ", "常见问题", "帮助", "说明", "指南"]
        found_faq = False
        for keyword in faq_keywords:
            links = await browser.find_links(keyword)
            if links:
                success = await browser.navigate(
                    links[0]["href"],
                    max_retries=1,
                    progress_callback=_emit_search_progress,
                )
                if not success:
                    return f"查找失败: {browser.last_navigation_error or 'FAQ 页面不可达'}"
                found_faq = True
                break

        if not found_faq:
            success = await browser.navigate(
                website_url,
                max_retries=1,
                progress_callback=_emit_search_progress,
            )
            if not success:
                return f"查找失败: {browser.last_navigation_error or '招聘页面不可达'}"

        page_text = await browser.get_page_text()

        type_label = recruitment_type
        return (
            f"页面内容:\n{page_text[:3000]}\n\n"
            f"请根据以上页面内容，分析该公司{type_label}最多可投递几个岗位。"
            f"如果未找到明确信息，请返回'未知'。"
        )
    except Exception as e:
        return f"查找失败: {e}"


@tool
async def get_position_details(
    position_url: str,
) -> str:
    """获取岗位的详细信息，包括工作地点、JD等。

    Args:
        position_url: 岗位详情页URL
    """
    try:
        browser = await _get_browser()
        success = await browser.navigate(
            position_url,
            max_retries=1,
            progress_callback=_emit_search_progress,
        )
        if not success:
            return f"获取岗位详情失败: {browser.last_navigation_error or '岗位页面不可达'}"

        page_text = await browser.get_page_text()
        page_url = await browser.get_current_url()

        return f"岗位详情页: {page_url}\n\n内容:\n{page_text[:3000]}"
    except Exception as e:
        return f"获取岗位详情失败: {e}"


@tool
async def extract_matching_positions(
    job_keywords: str,
    preferred_cities: str,
    limit: int = 12,
) -> str:
    """从当前招聘列表页批量提取岗位，按期望地区硬筛选并按关键词排序。

    Args:
        job_keywords: 岗位关键词，多个关键词可用逗号或空格分隔
        preferred_cities: 期望工作城市，多个城市可用逗号分隔
        limit: 最多返回岗位数
    """
    try:
        browser = await _get_browser()
        positions = await browser.extract_matching_job_cards(
            job_keywords=job_keywords,
            preferred_cities=preferred_cities,
            limit=min(max(limit, 1), 30),
        )
        if not positions:
            return (
                f"当前页面没有找到地区为“{preferred_cities or '不限'}”的岗位。"
                "不要推荐不符合地区条件的岗位。"
            )
        return json.dumps(positions, ensure_ascii=False)
    except Exception as e:
        return f"结构化提取岗位失败: {e}"


@tool
async def click_element_by_text_tool(button_text: str) -> str:
    """点击页面中文本包含指定内容的可点击元素（按钮/链接）。
    用于点击"即刻投递"、"开始找工作"等入口按钮。

    Args:
        button_text: 按钮文本内容（如"即刻投递"）
    """
    try:
        browser = await _get_browser()
        result = await browser.click_element_by_text(button_text)
        if result["success"]:
            return f"点击成功。新页面URL: {result['new_url']}\n页面内容摘要: {result['page_text_summary']}"
        else:
            return f"点击失败: {result.get('error', '未知错误')}"
    except Exception as e:
        return f"点击失败: {e}"


@tool
async def get_visible_buttons_tool() -> str:
    """获取当前页面所有可见的可点击元素（按钮/链接）列表。
    当页面没有职位信息时调用此工具，查看有哪些可点击的入口按钮。
    """
    try:
        browser = await _get_browser()
        buttons = await browser.get_visible_buttons()
        if not buttons:
            return "当前页面无可点击的按钮/链接"
        lines = []
        for i, btn in enumerate(buttons, 1):
            lines.append(f"{i}. [{btn['tag']}] {btn['text']} (href: {btn.get('href', '-')}, role: {btn.get('role', '-')})")
        return "当前页面可点击元素:\n" + "\n".join(lines)
    except Exception as e:
        return f"获取按钮失败: {e}"


@tool
async def check_login_status_tool() -> str:
    """检测当前页面的登录状态。判断用户是否已登录。
    """
    try:
        browser = await _get_browser()
        result = await browser.check_login_status()
        status = "已登录" if result["logged_in"] else "未登录"
        indicators = "; ".join(result.get("indicators", []))
        return f"登录状态: {status}\n当前URL: {result['current_url']}\n检测指标: {indicators}"
    except Exception as e:
        return f"检测失败: {e}"


def get_search_tools():
    """返回 Search Agent 使用的所有工具"""
    return [
        search_company_website,
        navigate_and_find_positions,
        extract_matching_positions,
        find_max_positions,
        get_position_details,
        click_element_by_text_tool,
        get_visible_buttons_tool,
        check_login_status_tool,
        notify_user,
    ]
