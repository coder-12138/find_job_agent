from agents import Agent, function_tool, RunContextWrapper

from job_application_agent.context import AppContext
from job_application_agent.tools.notify import notify_user
from job_application_agent.utils import sanitize_agent_name


async def _get_browser():
    from job_application_agent.browser.automation import BrowserAutomation
    from job_application_agent.config import Settings

    settings = Settings()
    return await BrowserAutomation.get_shared(
        headless=settings.browser_headless,
        timeout=settings.browser_timeout,
    )


@function_tool
async def search_company_website(
    ctx: RunContextWrapper[AppContext],
    company_name: str,
) -> str:
    """搜索公司的校招官网。使用搜索引擎查找目标公司的招聘官方网站。

    Args:
        company_name: 公司名称
    """
    try:
        browser = await _get_browser()
        search_query = f"{company_name} 校招 官网 招聘"
        search_url = f"https://www.bing.com/search?q={search_query}"
        await browser.navigate(search_url)
        await browser.page.wait_for_load_state("domcontentloaded")

        links = await browser.find_links("招聘")
        results = []
        for link in links[:10]:
            text = link.get("text", "")
            href = link.get("href", "")
            if any(kw in text.lower() or kw in href.lower() for kw in ["招聘", "campus", "career", "job", "校招"]):
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


@function_tool
async def navigate_and_find_positions(
    ctx: RunContextWrapper[AppContext],
    website_url: str,
    job_keywords: str,
    preferred_cities: str,
) -> str:
    """导航到招聘官网，查找符合条件的岗位信息。

    Args:
        website_url: 招聘官网URL
        job_keywords: 岗位关键词（如：AI算法、agent开发）
        preferred_cities: 期望工作城市，多个城市用逗号分隔
    """
    try:
        browser = await _get_browser()
        await browser.navigate(website_url)
        await browser.page.wait_for_load_state("domcontentloaded")

        page_text = await browser.get_page_text()
        page_url = await browser.get_current_url()

        campus_links = await browser.find_links("校招")
        if not campus_links:
            campus_links = await browser.find_links("校园招聘")
        if not campus_links:
            campus_links = await browser.find_links("campus")

        link_info = ""
        for link in campus_links[:5]:
            link_info += f"- {link['text']}: {link['href']}\n"

        return (
            f"当前页面: {page_url}\n"
            f"页面内容摘要: {page_text[:2000]}\n"
            f"校招相关链接:\n{link_info if link_info else '未找到校招入口链接'}"
        )
    except Exception as e:
        return f"导航失败: {e}"


@function_tool
async def find_max_positions(
    ctx: RunContextWrapper[AppContext],
    website_url: str,
) -> str:
    """查找该公司校招可投递的最大岗位数。通常在招聘官网的FAQ或说明页面中。

    Args:
        website_url: 招聘官网URL
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

        return (
            f"页面内容:\n{page_text[:3000]}\n\n"
            "请根据以上页面内容，分析该公司校招最多可投递几个岗位。"
            "如果未找到明确信息，请返回'未知'。"
        )
    except Exception as e:
        return f"查找失败: {e}"


@function_tool
async def get_position_details(
    ctx: RunContextWrapper[AppContext],
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


def create_search_agent(company_name: str) -> Agent[AppContext]:
    safe_name = sanitize_agent_name(company_name)
    return Agent[AppContext](
        name=f"Search_{safe_name}",
        instructions=f"""你是{company_name}的岗位搜索Agent。你的任务是：

1. 使用 search_company_website 工具搜索{company_name}的校招官网
2. 使用 navigate_and_find_positions 工具导航到官网并查找岗位
3. 使用 find_max_positions 工具查找该公司校招可投递的最大岗位数n（返回结果中会包含n的具体数字）
4. 根据发现的n计算推荐岗位数：
   - 如果找到了n，则推荐 2*n 个岗位
   - 如果未找到n（返回"未知"），则默认推荐 6 个岗位
5. 使用 get_position_details 工具获取每个候选岗位的详细信息
6. 从所有候选岗位中，筛选出最匹配的岗位（基于用户简历和岗位要求）

重要提醒：
- 必须先完成步骤3获取n的值，才能确定推荐岗位数量
- 如果n=3，则推荐6个岗位；如果n=5，则推荐10个岗位
- 如果官网未说明n，则按6个岗位进行推荐

每个推荐岗位必须包含：
- 岗位名称
- 工作地点
- 完整 Job Description
- 推荐理由（基于用户简历和岗位要求的匹配度分析，从高到低排序）

用户信息摘要：
{{user_info_summary}}

遇到任何问题（如找不到官网、需要注册才能查看JD等），立即使用 notify_user 工具通知用户并等待用户指示。

完成搜索后，使用 notify_user 工具将推荐岗位列表发送给用户，让用户选择要投递的岗位和志愿顺序。""",
        tools=[
            search_company_website,
            navigate_and_find_positions,
            find_max_positions,
            get_position_details,
            notify_user,
        ],
    )
