from langchain_core.tools import tool

from job_application_agent_langchain.context import RECRUITMENT_TYPE_KEYWORDS
from job_application_agent_langchain.tools.notify import notify_user
from job_application_agent_langchain.utils import sanitize_agent_name


async def _get_browser():
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    from job_application_agent_langchain.config import Settings

    settings = Settings()
    return await BrowserAutomation.get_shared(
        headless=settings.browser_headless,
        timeout=settings.browser_timeout,
    )


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
        browser = await _get_browser()
        search_query = f"{company_name} {recruitment_type} 官网 招聘"

        page_text = await browser.search_and_navigate(search_query)

        if not page_text:
            return "搜索失败: 无法访问搜索引擎"

        keywords = RECRUITMENT_TYPE_KEYWORDS.get(recruitment_type, ["招聘"])
        all_keywords = keywords + ["招聘", "career", "job"]

        links = await browser.find_links("招聘")
        results = []
        for link in links[:10]:
            text = link.get("text", "")
            href = link.get("href", "")
            if any(kw in text.lower() or kw in href.lower() for kw in all_keywords):
                results.append(f"- {text}: {href}")

        if not results:
            all_links = await browser.find_links()
            for link in all_links[:10]:
                text = link.get("text", "")
                href = link.get("href", "")
                results.append(f"- {text}: {href}")

        return f"搜索到以下链接:\n" + "\n".join(results) if results else "未找到相关链接"
    except Exception as e:
        return f"搜索失败: {e}"


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
        browser = await _get_browser()
        await browser.navigate(website_url)
        await browser.page.wait_for_load_state("domcontentloaded")

        page_text = await browser.get_page_text()
        page_url = await browser.get_current_url()

        # 自动尝试点击常见入口按钮
        ENTRY_BUTTON_TEXTS = [
            "即刻投递", "开始投递", "投递简历", "查看职位", "开始找工作",
            "校招岗位", "校园招聘", "进入投递", "我要投递", "投递入口",
            "搜索职位", "职位搜索", "校招入口", "网申入口",
        ]
        clicked_button = ""
        for btn_text in ENTRY_BUTTON_TEXTS:
            try:
                result = await browser.click_element_by_text(btn_text)
                if result["success"]:
                    clicked_button = btn_text
                    break
            except Exception:
                continue

        # 如果自动点击成功，重新获取页面信息
        if clicked_button:
            page_text = await browser.get_page_text()
            page_url = await browser.get_current_url()

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
        return (
            f"当前页面: {page_url}\n"
            f"投递类型: {type_label}\n"
            f"{entry_info}"
            f"页面内容摘要: {page_text[:2000]}\n"
            f"{type_label}相关链接:\n{link_info if link_info else f'未找到{type_label}入口链接'}"
        )
    except Exception as e:
        return f"导航失败: {e}"


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
                await browser.navigate(links[0]["href"])
                found_faq = True
                break

        if not found_faq:
            await browser.navigate(website_url)

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
        await browser.navigate(position_url)
        await browser.page.wait_for_load_state("domcontentloaded")

        page_text = await browser.get_page_text()
        page_url = await browser.get_current_url()

        return f"岗位详情页: {page_url}\n\n内容:\n{page_text[:3000]}"
    except Exception as e:
        return f"获取岗位详情失败: {e}"


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
        find_max_positions,
        get_position_details,
        click_element_by_text_tool,
        get_visible_buttons_tool,
        check_login_status_tool,
        notify_user,
    ]
