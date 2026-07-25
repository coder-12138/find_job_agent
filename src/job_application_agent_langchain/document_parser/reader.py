"""腾讯文档读取器。

负责打开腾讯文档智能表格 URL，处理登录/反自动化检测，并提取表格数据。
剪贴板方案优先（模拟 Ctrl+A/Ctrl+C），失败时回退到 DOM 提取。

注意：BrowserAutomation 与 AgentEventEmitter 的导入延迟到函数内部执行，
避免在未安装 playwright 等重依赖的环境下，因导入本模块而失败，
从而使 matcher 子模块可独立导入与测试。
"""

import asyncio
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # 仅用于类型提示，运行时不导入
    from job_application_agent_langchain.agent_events import AgentEventEmitter
    from job_application_agent_langchain.browser.automation import BrowserAutomation


class DocumentAccessError(Exception):
    """文档访问异常（反爬/登录失败等）"""


def _generate_request_id() -> str:
    """延迟导入并生成 request_id，避免模块加载时引入额外依赖。"""
    from job_application_agent_langchain.agent_events import generate_request_id
    return generate_request_id()


# 登录页 URL 关键词
_LOGIN_URL_KEYWORDS = ("login", "signin", "passport", "account/login")

# 页面中提示需要登录的文本
_LOGIN_PAGE_TEXTS = ("登录", "QQ登录", "微信登录")

# 反自动化检测相关文本
_ANTI_AUTOMATION_TEXTS = ("验证", "环境异常", "安全验证")


async def _wait_page_render(extra_seconds: float = 4.0) -> None:
    """等待页面 JS 渲染：先等 domcontentloaded，再额外等待若干秒。"""
    # 这里的等待是为了让腾讯文档的前端 JS 完成表格渲染
    await asyncio.sleep(extra_seconds)


async def _detect_login_required(automation: "BrowserAutomation") -> tuple[bool, str]:
    """检测当前页面是否需要登录。

    Returns:
        (是否需要登录, 当前 URL)
    """
    try:
        current_url = await automation.get_current_url()
    except Exception:
        current_url = ""

    url_lower = (current_url or "").lower()
    if any(kw in url_lower for kw in _LOGIN_URL_KEYWORDS):
        return True, current_url

    try:
        page_text = await automation.get_page_text()
    except Exception:
        page_text = ""

    # 仅当页面文本较短（典型登录页）且含登录关键词时判定为需要登录，
    # 避免业务页面偶然包含"登录"二字被误判
    if any(text in page_text for text in _LOGIN_PAGE_TEXTS):
        # 简单启发式：登录页通常文本较短
        if len(page_text) < 2000:
            return True, current_url

    return False, current_url


async def _detect_anti_automation(automation: "BrowserAutomation") -> bool:
    """检测页面是否触发反自动化验证。"""
    try:
        page_text = await automation.get_page_text()
    except Exception:
        return False
    return any(text in page_text for text in _ANTI_AUTOMATION_TEXTS)


async def _request_login(
    automation: "BrowserAutomation",
    emitter: "AgentEventEmitter | None",
    current_url: str,
) -> None:
    """通过 emitter 请求用户完成登录，emitter 为 None 时抛出异常。"""
    if emitter is None:
        raise DocumentAccessError("文档需要登录")

    request_id = _generate_request_id()
    message = (
        "请在弹出的浏览器窗口中完成腾讯文档的登录。\n"
        f"当前页: {current_url}\n"
        "支持 QQ/微信扫码或账号登录，完成后请点击下方'已完成登录'按钮。"
    )
    # emitter.request_user_login 的签名是 async def request_user_login(self, login_url: str) -> str
    # 但 AgentEventEmitter 抽象类定义为 (request_id, login_url, message)，
    # 这里兼容两种签名：优先按抽象类签名调用
    try:
        await emitter.request_user_login(request_id, current_url, message)
    except TypeError:
        # 兼容只接受 login_url 的旧签名
        await emitter.request_user_login(current_url)  # type: ignore[arg-type]

    # 登录后重新等待加载
    await _wait_page_render()


async def _extract_via_clipboard(automation: "BrowserAutomation") -> list[dict[str, str]] | None:
    """剪贴板方案：模拟 Ctrl+A 全选 + Ctrl+C 复制，从 clipboard 读取文本并解析。

    成功返回行数据列表，失败返回 None。
    """
    page = automation.page
    context = page.context

    # 授权剪贴板权限
    try:
        await context.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception:
        # 某些环境下权限授予可能失败，继续尝试
        pass

    try:
        # 全选页面文本
        await page.keyboard.press("Control+A")
        await asyncio.sleep(0.5)
        # 复制到剪贴板
        await page.keyboard.press("Control+C")
        await asyncio.sleep(0.5)

        # 读取剪贴板
        clipboard_text = await page.evaluate(
            "() => navigator.clipboard.readText().catch(() => '')"
        )
    except Exception:
        return None

    if not clipboard_text:
        return None

    return _parse_clipboard_text(clipboard_text)


def _parse_clipboard_text(text: str) -> list[dict[str, str]] | None:
    """解析剪贴板文本为行数据列表。

    - 用 \\t 分列
    - 用 \\n 或 \\r\\n 分行
    - 第一行作为表头
    """
    if not text:
        return None

    # 统一换行符
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    # 过滤掉完全空白的行
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return None

    # 至少要有表头 + 一行数据
    if len(lines) < 2:
        return None

    headers = [h.strip() for h in lines[0].split("\t")]
    if not any(headers):
        return None

    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        cells = line.split("\t")
        row: dict[str, str] = {}
        for i, header in enumerate(headers):
            if not header:
                continue
            value = cells[i] if i < len(cells) else ""
            row[header] = value.strip()
        rows.append(row)

    return rows


async def _extract_via_dom(automation: "BrowserAutomation") -> list[dict[str, str]] | None:
    """DOM 提取方案：查找表格相关元素逐行提取。

    成功返回行数据列表，失败返回 None。
    """
    page = automation.page

    # 候选的表格单元格选择器
    cell_selectors = [
        ".sheet-cell",
        ".grid-cell",
        "td",
        "[class*='cell']",
    ]

    for selector in cell_selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            if count == 0:
                continue

            # 尝试找单元格所在的行容器：tr 或带 row 类的元素
            row_selectors = ["tr", "[class*='row']", "[role='row']"]
            rows_data: list[dict[str, str]] | None = None
            for row_sel in row_selectors:
                try:
                    row_locator = page.locator(row_sel)
                    row_count = await row_locator.count()
                    if row_count < 2:
                        continue
                    parsed = await _extract_rows_from_container(row_locator, row_sel, selector)
                    if parsed:
                        rows_data = parsed
                        break
                except Exception:
                    continue

            if rows_data:
                return rows_data
        except Exception:
            continue

    return None


async def _extract_rows_from_container(
    row_locator,
    row_sel: str,
    cell_sel: str,
) -> list[dict[str, str]] | None:
    """从行容器中提取单元格文本。

    Args:
        row_locator: 行元素的 locator
        row_sel: 行选择器（仅用于日志）
        cell_sel: 单元格选择器

    Returns:
        解析出的行数据列表，或 None
    """
    row_count = await row_locator.count()
    if row_count < 2:
        return None

    headers: list[str] = []
    rows: list[dict[str, str]] = []

    for i in range(row_count):
        try:
            row_el = row_locator.nth(i)
            # 在当前行内查找单元格
            cell_locator = row_el.locator(cell_sel)
            cell_count = await cell_locator.count()
            if cell_count == 0:
                # 行容器自身可能就是单元格集合，尝试取直接子元素
                cell_locator = row_el.locator(":scope > *")
                cell_count = await cell_locator.count()
                if cell_count == 0:
                    continue

            cells: list[str] = []
            for j in range(cell_count):
                try:
                    text = await cell_locator.nth(j).inner_text()
                except Exception:
                    text = ""
                cells.append((text or "").strip())
        except Exception:
            continue

        if not any(cells):
            continue

        if i == 0:
            # 第一行作为表头
            headers = cells
            continue

        row: dict[str, str] = {}
        for j, header in enumerate(headers):
            if not header:
                continue
            row[header] = cells[j] if j < len(cells) else ""
        rows.append(row)

    if not rows:
        return None
    if not headers:
        return None
    return rows


async def read_tencent_document(
    doc_url: str,
    emitter: "AgentEventEmitter | None" = None,
) -> list[dict[str, str]]:
    """读取腾讯文档智能表格，返回行数据列表（每行是 字段名->值 的 dict）。

    流程：
    1. 用 BrowserAutomation.get_shared() 打开文档 URL
    2. 等待页面加载（domcontentloaded + 额外等待 3-5 秒让 JS 渲染）
    3. 检测是否需要登录：
       - 检查 URL 是否被重定向到 login 页面
       - 检查页面是否含"登录"按钮或登录弹窗
       - 若需登录且 emitter 不为 None：调用 emitter.request_user_login() HITL
       - 若需登录且 emitter 为 None：raise DocumentAccessError("文档需要登录")
       - 登录后重新等待加载
    4. 检测反自动化：检查页面是否含 '验证' '环境异常' '安全验证' 等文本
       - 若检测到：raise DocumentAccessError("腾讯文档检测到自动化访问")
    5. 提取表格数据：
       - 优先尝试剪贴板方案
       - 剪贴板失败则尝试 DOM 提取
    6. 如果两种方案都失败，raise DocumentAccessError("无法提取表格数据")

    Args:
        doc_url: 腾讯文档 URL
        emitter: 事件发射器，None 时不进行 HITL 登录交互

    Returns:
        表格行数据列表，每个 dict 是一行数据，key 是列名

    Raises:
        DocumentAccessError: 文档需要登录、被反自动化拦截或无法提取表格数据
    """
    # 延迟导入，避免模块加载时引入 playwright 等重依赖
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    # 1. 打开文档
    automation = await BrowserAutomation.get_shared()
    # 使用 domcontentloaded 等待策略，腾讯文档 JS 较多，load 可能超时
    try:
        await automation.page.goto(doc_url, wait_until="domcontentloaded")
    except Exception as e:
        # 导航失败时检查是否已跳转
        try:
            current_url = await automation.get_current_url()
        except Exception:
            current_url = ""
        if not current_url or current_url == "about:blank":
            raise DocumentAccessError(f"打开文档失败: {e}")

    # 2. 等待页面渲染
    await _wait_page_render(extra_seconds=4.0)

    # 3. 登录检测
    need_login, current_url = await _detect_login_required(automation)
    if need_login:
        await _request_login(automation, emitter, current_url)
        # 登录后重新检测一次反自动化与登录状态
        need_login, current_url = await _detect_login_required(automation)
        if need_login:
            raise DocumentAccessError("文档仍需登录，登录失败或未完成")

    # 4. 反自动化检测
    if await _detect_anti_automation(automation):
        raise DocumentAccessError("腾讯文档检测到自动化访问")

    # 5. 提取表格数据
    # 5.1 优先剪贴板方案
    rows = await _extract_via_clipboard(automation)
    if rows:
        return rows

    # 5.2 回退 DOM 提取
    rows = await _extract_via_dom(automation)
    if rows:
        return rows

    # 6. 两种方案都失败
    raise DocumentAccessError("无法提取表格数据")
