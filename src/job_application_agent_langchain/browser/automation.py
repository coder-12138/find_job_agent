import asyncio
import base64
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from uuid import uuid4

from playwright.async_api import async_playwright, Page, BrowserContext, Locator


class BrowserAutomation:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self, headless: bool = False, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.operation_lock = asyncio.Lock()
        self.last_navigation_error = ""

    @classmethod
    async def get_shared(cls, headless: bool = False, timeout: int = 30000) -> "BrowserAutomation":
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(headless=headless, timeout=timeout)
            if cls._instance._page is None:
                await cls._instance.start()
            return cls._instance

    @classmethod
    async def close_shared(cls):
        if cls._instance is not None:
            await cls._instance.close()
            cls._instance = None

    async def start(self) -> Page:
        if self._page is not None:
            return self._page
        self._playwright = await async_playwright().start()
        
        launch_args = ["--disable-blink-features=AutomationControlled"]
        context_size_options: dict[str, Any]
        if self.headless:
            context_size_options = {"viewport": {"width": 1440, "height": 960}}
        else:
            # Headed 模式必须跟随真实窗口尺寸。固定 viewport 会让招聘站的
            # 内部滚动容器按虚假高度布局，窗口缩小时底部被裁掉且无法滚动。
            launch_args.append("--start-maximized")
            context_size_options = {"no_viewport": True}
        
        from job_application_agent_langchain.core import get_core_runtime

        profile_dir = get_core_runtime().settings.managed_browser_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=self.headless,
            locale="zh-CN",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            args=launch_args,
            **context_size_options,
        )
        
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        self._context.set_default_timeout(self.timeout)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self._page

    async def close(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None

    async def capture_manual_interaction_proposals(self) -> int:
        """Store value-free Feishu locator proposals for later human review."""

        if self._page is None or "jobs.feishu.cn" not in (self._page.url or ""):
            return 0
        from job_application_agent_langchain.browser_runtime.feishu import (
            FeishuRecruitingAdapter,
        )
        from job_application_agent_langchain.core import get_core_runtime

        adapter = FeishuRecruitingAdapter()
        hints = await adapter.collect_manual_hints(self._page)
        if not hints:
            return 0
        fingerprint = await adapter.fingerprint(self._page)
        now = datetime.now(timezone.utc).isoformat()
        database = get_core_runtime().database
        with database.connect() as connection:
            for hint in hints:
                connection.execute(
                    """
                    INSERT INTO interaction_hints(
                        id, platform, page_fingerprint, field_key,
                        locator_strategy, locator_value, success_count,
                        failure_count, review_status, created_at, updated_at
                    ) VALUES (?, 'feishu_recruiting', ?, ?, ?, ?, 1, 0, 'candidate', ?, ?)
                    ON CONFLICT(
                        platform, page_fingerprint, field_key,
                        locator_strategy, locator_value
                    ) DO UPDATE SET
                        success_count = success_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (
                        uuid4().hex,
                        fingerprint,
                        hint["field_key"],
                        hint["locator_strategy"],
                        hint["locator_value"],
                        now,
                        now,
                    ),
                )
            connection.commit()
        return len(hints)

    async def inspect_submission_outcome(self) -> tuple[str, str]:
        """Inspect a Feishu receipt without turning a button click into success."""

        if self._page is None or "jobs.feishu.cn" not in (self._page.url or ""):
            return "outcome_unknown", "当前站点没有正式回执适配器，无法验证提交结果"
        from job_application_agent_langchain.browser_runtime.feishu import (
            FeishuRecruitingAdapter,
        )

        await self.wait_for_page_settle(timeout_ms=4000)
        inspection = await FeishuRecruitingAdapter().inspect(self._page)
        if inspection.kind == "submitted":
            return "submitted", inspection.message
        return "outcome_unknown", inspection.message or "未观察到可验证的投递成功回执"

    async def prepare_application_form(
        self,
        position_url: str,
        *,
        position_name: str = "",
        source_list_url: str = "",
        current_only: bool = False,
    ) -> dict[str, Any]:
        """Restore the selected job and verify that its application form is open."""

        from job_application_agent_langchain.browser_runtime.feishu import (
            FeishuRecruitingAdapter,
        )

        target = self.resolve_url(position_url)
        if not target:
            return {
                "ready": False,
                "kind": "invalid_position_url",
                "url": self.page.url,
                "message": "所选岗位没有有效的申请地址",
            }
        adapter = FeishuRecruitingAdapter()
        attempts: list[dict[str, str]] = []

        async def wait_for_application_outcome(
            before_pages: list[Page], timeout_seconds: float = 12.0
        ) -> dict[str, Any]:
            """Wait for a popup, SPA form, or login page after one apply click."""

            deadline = asyncio.get_running_loop().time() + timeout_seconds
            adopted: set[int] = set()
            last_inspection = None
            while asyncio.get_running_loop().time() < deadline:
                if self._context is not None:
                    new_pages = [
                        page for page in self._context.pages if page not in before_pages
                    ]
                    if new_pages:
                        candidate = new_pages[-1]
                        self._page = candidate
                        if id(candidate) not in adopted:
                            adopted.add(id(candidate))
                            try:
                                await candidate.wait_for_load_state(
                                    "domcontentloaded", timeout=5000
                                )
                            except Exception:
                                pass
                            await adapter.install_learning_probe(candidate)
                try:
                    last_inspection = await adapter.inspect(self.page)
                    if last_inspection.kind in {
                        "application_form",
                        "login_required",
                    }:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.5)

            if last_inspection is None:
                last_inspection = await adapter.inspect(self.page)
            attempts.append(
                {
                    "stage": "application_click_outcome",
                    "kind": last_inspection.kind,
                    "url": last_inspection.url,
                    "message": last_inspection.message,
                }
            )
            return {
                "ready": last_inspection.kind == "application_form",
                "kind": last_inspection.kind,
                "url": last_inspection.url,
                "message": last_inspection.message,
                "attempts": attempts,
            }

        async def inspect(stage: str) -> dict[str, Any]:
            await self.wait_for_page_settle(timeout_ms=5000)
            inspection = await adapter.inspect(self.page)
            attempts.append(
                {
                    "stage": stage,
                    "kind": inspection.kind,
                    "url": inspection.url,
                    "message": inspection.message,
                }
            )
            return {
                "ready": inspection.kind == "application_form",
                "kind": inspection.kind,
                "url": inspection.url,
                "message": inspection.message,
                "attempts": attempts,
            }

        def derived_list_url() -> str:
            parsed = urlparse(target)
            match = re.match(r"^(.*?/position)/[^/]+/detail/?$", parsed.path)
            if not match:
                return ""
            return parsed._replace(path=match.group(1), query="", fragment="").geturl()

        try:
            # 上一次点击产生的新页可能晚于等待窗口出现。重试前先扫描现有受管页，
            # 发现表单或登录页就直接接管，绝不再次点击申请制造重复页面。
            if self._context is not None:
                for candidate in reversed(self._context.pages):
                    if candidate is self._page or candidate.is_closed():
                        continue
                    try:
                        candidate_inspection = await adapter.inspect(candidate)
                    except Exception:
                        continue
                    if candidate_inspection.kind not in {
                        "application_form",
                        "login_required",
                    }:
                        continue
                    self._page = candidate
                    await adapter.install_learning_probe(candidate)
                    attempts.append(
                        {
                            "stage": "existing_managed_page",
                            "kind": candidate_inspection.kind,
                            "url": candidate_inspection.url,
                            "message": candidate_inspection.message,
                        }
                    )
                    return {
                        "ready": candidate_inspection.kind == "application_form",
                        "kind": candidate_inspection.kind,
                        "url": candidate_inspection.url,
                        "message": candidate_inspection.message,
                        "attempts": attempts,
                    }

            # 用户可能已在受管窗口中手动进入表单；先检查，不能把它导航走。
            current = await inspect("current_page")
            if current["ready"]:
                return current
            if current["kind"] == "login_required" or current_only:
                if current_only and current["kind"] != "login_required":
                    current["kind"] = "waiting_current_page"
                    current["message"] = (
                        "正在等待当前受管页面出现申请表单；未再次点击申请，"
                        "也未回退岗位列表"
                    )
                return current

            before_pages = list(self._context.pages if self._context else [])
            navigation = await adapter.navigate_to_application(self.page, target)
            if navigation.get("action") == "application_clicked":
                direct = await wait_for_application_outcome(before_pages)
                if direct["ready"] or direct["kind"] == "login_required":
                    return direct
                # 已在正确岗位点击过申请。此时回列表只会破坏页面并可能重复开窗；
                # 保持当前页，交给同一受管窗口继续检测。
                direct["kind"] = "application_action_pending"
                direct["message"] = (
                    f"已在所选岗位点击“{navigation.get('text') or '申请'}”，"
                    "但尚未识别到申请表单；已保持当前页面，不回退岗位列表"
                )
                return direct
            direct = await inspect("selected_position_url")
            if direct["ready"] or direct["kind"] == "login_required":
                return direct

            list_urls = list(
                dict.fromkeys(
                    url
                    for url in (self.resolve_url(source_list_url), derived_list_url())
                    if url
                )
            )
            for list_url in list_urls:
                await self.page.goto(
                    list_url, wait_until="domcontentloaded", timeout=45_000
                )
                await self.wait_for_page_settle(timeout_ms=6000)
                job_links = self.page.locator(
                    'a[href*="/position/"][href*="/detail"]'
                )
                if position_name:
                    job_links = job_links.filter(has_text=position_name)
                clicked = False
                for index in range(min(await job_links.count(), 100)):
                    job_link = job_links.nth(index)
                    href = self.resolve_url(await job_link.get_attribute("href") or "")
                    if not await job_link.is_visible():
                        continue
                    if position_name or href == target:
                        before_pages = list(
                            self._context.pages if self._context else []
                        )
                        await job_link.click()
                        await wait_for_application_outcome(
                            before_pages, timeout_seconds=6.0
                        )
                        clicked = True
                        break
                attempts.append(
                    {
                        "stage": "position_list_lookup",
                        "kind": "clicked" if clicked else "position_not_found",
                        "url": list_url,
                        "message": (
                            f"已按岗位名称进入：{position_name}"
                            if clicked
                            else f"岗位列表中未找到：{position_name or target}"
                        ),
                    }
                )
                if not clicked:
                    continue
                detail_url = self.page.url
                before_pages = list(self._context.pages if self._context else [])
                navigation = await adapter.navigate_to_application(
                    self.page, detail_url
                )
                if navigation.get("action") == "application_clicked":
                    recovered = await wait_for_application_outcome(before_pages)
                    if recovered["ready"] or recovered["kind"] == "login_required":
                        return recovered
                    recovered["kind"] = "application_action_pending"
                    recovered["message"] = (
                        f"已在恢复的岗位详情页点击“{navigation.get('text') or '申请'}”，"
                        "但尚未识别到申请表单；已保持当前页面，不再次回退岗位列表"
                    )
                    return recovered
                recovered = await inspect("position_name_and_apply")
                if recovered["ready"] or recovered["kind"] == "login_required":
                    return recovered

            result = await inspect("recovery_exhausted")
            result["message"] = (
                "已尝试岗位详情地址、原岗位列表和岗位名称，但仍未识别到申请表单"
            )
            return result
        except Exception as exc:
            return {
                "ready": False,
                "kind": "navigation_failed",
                "url": self.page.url,
                "message": f"打开所选岗位申请表单失败：{exc}",
                "attempts": attempts,
            }

    async def prefill_application_form(
        self,
        user_info: Any,
        *,
        reviewed_resume: dict[str, Any] | None = None,
        resume_path: str = "",
    ) -> dict[str, Any]:
        """Prefill the verified form from the confirmed candidate profile."""

        from job_application_agent_langchain.browser_runtime.feishu import (
            FeishuRecruitingAdapter,
        )

        profile = (
            user_info.model_dump()
            if hasattr(user_info, "model_dump")
            else dict(user_info or {})
        )
        inspection = await FeishuRecruitingAdapter().fill_profile(
            self.page,
            profile,
            reviewed_resume=reviewed_resume or {},
            resume_path=resume_path,
        )
        return {
            "ready": inspection.kind in {
                "application_form",
                "ready_for_user_submit",
            },
            "kind": inspection.kind,
            "url": inspection.url,
            "message": inspection.message,
            "filled_fields": inspection.filled_fields,
            "skipped_fields": inspection.skipped_fields,
            "evidence": inspection.evidence,
        }

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    async def navigate(
        self,
        url: str,
        max_retries: int = 2,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> bool:
        """导航到指定 URL；致命网络错误快速失败，其余错误有限重试。"""
        self.last_navigation_error = ""
        url = self.resolve_url(url)
        if not url:
            self.last_navigation_error = "无效 URL：无法根据当前页面补全链接"
            if progress_callback is not None:
                await progress_callback(self.last_navigation_error)
            return False
        fatal_network_errors = (
            "ERR_CONNECTION_CLOSED",
            "ERR_CONNECTION_RESET",
            "ERR_CONNECTION_REFUSED",
            "ERR_NAME_NOT_RESOLVED",
            "ERR_NETWORK_CHANGED",
            "ERR_INTERNET_DISCONNECTED",
        )

        async def report(message: str) -> None:
            if progress_callback is not None:
                await progress_callback(message)

        for attempt in range(max_retries):
            await report(f"正在访问 {url}（第 {attempt + 1}/{max_retries} 次）")
            try:
                response = await self.page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout
                )
                if response:
                    if response.status >= 400:
                        self.last_navigation_error = f"HTTP {response.status}"
                        await report(f"页面返回 HTTP {response.status}: {url}")
                        if response.status >= 500 and attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        return False
                current_url = self.page.url
                if not self.navigation_reached_target(current_url, url):
                    self.last_navigation_error = (
                        f"导航结束后未到达目标站点，当前仍为 {current_url}"
                    )
                    await report(self.last_navigation_error)
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return False
                return True
            except Exception as e:
                error_msg = str(e)
                self.last_navigation_error = error_msg
                if any(code in error_msg for code in fatal_network_errors):
                    print(f"[浏览器] 网站不可达，快速失败: {e}")
                    await report(f"网站不可达：{url}（{next(code for code in fatal_network_errors if code in error_msg)}）")
                    return False
                if "Timeout" in error_msg or "timeout" in error_msg:
                    try:
                        current_url = self.page.url
                        if self.navigation_reached_target(current_url, url):
                            body_text = await self.page.locator("body").inner_text(
                                timeout=2000
                            )
                            if len(body_text.strip()) >= 80:
                                await report(
                                    "页面加载事件超时，但目标站点正文已经渲染，继续处理"
                                )
                                return True
                    except Exception:
                        pass
                if "ERR_ABORTED" in error_msg:
                    await asyncio.sleep(1)
                    try:
                        current_url = self.page.url
                        if self.navigation_reached_target(current_url, url):
                            print(f"[浏览器] 页面已加载 (URL: {current_url})")
                            return True
                        await report(
                            f"导航被中止且仍停留在其他站点：{current_url or '空白页'}"
                        )
                    except Exception:
                        pass

                print(f"[浏览器] 导航失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    await report(f"访问失败，将在 {wait_time} 秒后重试：{url}")
                    print(f"[浏览器] 等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    await report(f"访问失败，已停止重试：{url}")
                    return False
        return False

    def resolve_url(self, url: str) -> str:
        """把岗位页返回的相对链接补全为当前站点的绝对 HTTP(S) URL。"""
        url = (url or "").strip()
        if not url:
            return ""
        current_url = getattr(self._page, "url", "") or ""
        resolved = urljoin(current_url, url)
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return resolved

    @staticmethod
    def navigation_reached_target(current_url: str, target_url: str) -> bool:
        """ERR_ABORTED 只能在确实到达目标站点时视为成功，防止沿用上一家公司页面。"""
        try:
            current = urlparse(current_url)
            target = urlparse(target_url)
        except Exception:
            return False
        return (
            current.scheme in {"http", "https"}
            and target.scheme in {"http", "https"}
            and current.hostname
            and target.hostname
            and current.hostname.lower() == target.hostname.lower()
        )

    async def get_page_content(self) -> str:
        return await self.page.content()

    async def get_page_text(self) -> str:
        return await self.page.inner_text("body")

    async def get_current_url(self) -> str:
        return self.page.url

    async def wait_for_page_settle(self, timeout_ms: int = 6000) -> None:
        """给 SPA/异步接口留出渲染时间，但不无限等待持续网络请求。"""
        timeout_ms = max(500, timeout_ms)
        await asyncio.sleep(min(1.0, timeout_ms / 1000))
        try:
            await self.page.wait_for_load_state(
                "networkidle",
                timeout=max(500, timeout_ms - 1000),
            )
        except Exception:
            # 招聘站常有埋点、长轮询，networkidle 超时不代表页面不可用。
            pass
        try:
            await self.page.wait_for_function(
                """() => document.body &&
                    document.body.innerText.trim().length >= 80""",
                timeout=1000,
            )
        except Exception:
            pass

    async def detect_page_problem(self) -> str:
        """识别返回 200 但正文实际是错误页、失效页或拦截页的情况。"""
        current_url = getattr(self.page, "url", "")
        if self.is_obvious_error_url(current_url):
            return f"链接指向错误路由：{current_url}"
        try:
            title = await self.page.title()
        except Exception:
            title = ""
        try:
            body = await self.get_page_text()
        except Exception:
            body = ""

        sample = " ".join(f"{title}\n{body[:3500]}".lower().split())
        problem_markers = {
            "页面已经被移走": "页面已被移走",
            "您请求的页面不存在": "请求的页面不存在",
            "您访问的站点出错": "目标站点返回错误页",
            "如果您看见该页，可能有以下几个原因": "目标站点返回通用错误页",
            "页面不存在": "页面不存在",
            "找不到该页面": "找不到页面",
            "网页无法访问": "网页无法访问",
            "page not found": "Page Not Found",
            "the page you requested was not found": "Page Not Found",
            "access denied": "访问被拒绝",
            "request blocked": "请求被拦截",
            "service unavailable": "服务暂不可用",
            "bad gateway": "网关错误",
            "internal server error": "服务器内部错误",
        }
        for marker, reason in problem_markers.items():
            if marker in sample:
                return reason

        # 只有在页面内容很短时，才把孤立的状态码标题视为错误，避免误判正文里的岗位编号。
        if len(body.strip()) < 1200:
            short_markers = ("404", "403 forbidden", "502", "503", "error!")
            if any(marker in sample for marker in short_markers):
                return f"疑似错误页（{title.strip() or body.strip()[:80]}）"
        return ""

    @staticmethod
    def is_obvious_error_url(url: str) -> bool:
        """通过 URL 路径识别明确的 404/error/not-found 路由。"""
        try:
            path = urlparse(url).path.lower().rstrip("/")
        except Exception:
            return False
        if not path:
            return False
        segments = [segment for segment in path.split("/") if segment]
        return any(
            segment in {"404", "403", "error", "not-found", "not_found", "page-not-found"}
            for segment in segments
        )

    @staticmethod
    def normalize_search_result_url(href: str) -> str:
        """解开常见搜索引擎跳转链接，并过滤搜索引擎自身页面。"""
        href = (href or "").strip()
        if href.startswith("//"):
            href = f"https:{href}"
        if not href.startswith(("http://", "https://")):
            return ""

        parsed = urlparse(href)
        host = parsed.netloc.lower().split(":")[0]
        query = parse_qs(parsed.query)

        if host in {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com"}:
            target = query.get("uddg", [""])[0]
            if target:
                href = unquote(target)
                parsed = urlparse(href)
                host = parsed.netloc.lower().split(":")[0]

        if host in {"bing.com", "www.bing.com", "cn.bing.com"}:
            encoded = query.get("u", [""])[0]
            if encoded.startswith("a1"):
                try:
                    payload = encoded[2:]
                    payload += "=" * (-len(payload) % 4)
                    href = base64.urlsafe_b64decode(payload).decode("utf-8")
                    parsed = urlparse(href)
                    host = parsed.netloc.lower().split(":")[0]
                except Exception:
                    return ""

        blocked_hosts = {
            "bing.com",
            "www.bing.com",
            "cn.bing.com",
            "duckduckgo.com",
            "www.duckduckgo.com",
            "html.duckduckgo.com",
            "go.microsoft.com",
        }
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or host in blocked_hosts
            or BrowserAutomation.is_obvious_error_url(href)
        ):
            return ""
        return href

    async def get_search_result_links(self) -> list[dict[str, str]]:
        """提取 Bing/DuckDuckGo 的真实结果链接，跳过导航和跟踪链接。"""
        selectors = (
            "li.b_algo h2 a, "
            "a.result__a, "
            "[data-testid='result-title-a']"
        )
        locator = self.page.locator(selectors)
        if await locator.count() == 0:
            return []

        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for i in range(min(await locator.count(), 40)):
            element = locator.nth(i)
            href = self.normalize_search_result_url(
                await element.get_attribute("href") or ""
            )
            text = (await element.inner_text()).strip()
            if href and text and href not in seen:
                seen.add(href)
                results.append({"text": text, "href": href})
            if len(results) >= 12:
                break
        return results

    async def fill_text(self, selector: str, value: str) -> bool:
        try:
            locator = self.page.locator(selector)
            await locator.fill("")
            await locator.fill(value)
            return True
        except Exception as e:
            print(f"[浏览器] 填写文本失败 ({selector}): {e}")
            return False

    async def type_text(self, selector: str, value: str) -> bool:
        try:
            locator = self.page.locator(selector)
            await locator.click()
            await locator.type(value, delay=50)
            return True
        except Exception as e:
            print(f"[浏览器] 输入文本失败 ({selector}): {e}")
            return False

    async def select_option(self, selector: str, value: str = "", label: str = "") -> bool:
        try:
            locator = self.page.locator(selector)
            if label:
                await locator.select_option(label=label)
            elif value:
                await locator.select_option(value=value)
            return True
        except Exception as e:
            print(f"[浏览器] 选择下拉选项失败 ({selector}): {e}")
            return False

    async def click_radio(self, selector: str, label_text: str = "") -> bool:
        try:
            if label_text:
                radio = self.page.locator(f'{selector} >> text="{label_text}"')
                if await radio.count() > 0:
                    await radio.click()
                    return True
            locator = self.page.locator(selector)
            await locator.click()
            return True
        except Exception as e:
            print(f"[浏览器] 点击单选按钮失败 ({selector}): {e}")
            return False

    async def click_checkbox(self, selector: str) -> bool:
        try:
            locator = self.page.locator(selector)
            await locator.click()
            return True
        except Exception as e:
            print(f"[浏览器] 勾选复选框失败 ({selector}): {e}")
            return False

    async def click_button(self, selector: str) -> bool:
        try:
            locator = self.page.locator(selector)
            await locator.click()
            return True
        except Exception as e:
            print(f"[浏览器] 点击按钮失败 ({selector}): {e}")
            return False

    async def select_date_from_calendar(
        self,
        selector: str,
        year: str = "",
        month: str = "",
        day: str = "",
    ) -> bool:
        try:
            locator = self.page.locator(selector)
            await locator.click()

            await asyncio.sleep(0.5)

            if year:
                year_selectors = [
                    '.ant-picker-header-year-btn',
                    '.el-date-picker__header-year',
                    '[class*="year"]',
                    'select[class*="year"]',
                ]
                for ys in year_selectors:
                    year_el = self.page.locator(ys)
                    if await year_el.count() > 0:
                        await year_el.first.click()
                        target = self.page.locator(f'text="{year}"').first
                        if await target.count() > 0:
                            await target.click()
                        break

            if month:
                month_selectors = [
                    '.ant-picker-header-month-btn',
                    '.el-date-picker__header-month',
                    '[class*="month"]',
                ]
                for ms in month_selectors:
                    month_el = self.page.locator(ms)
                    if await month_el.count() > 0:
                        await month_el.first.click()
                        target = self.page.locator(f'text="{int(month)}月"').first
                        if await target.count() > 0:
                            await target.click()
                        break

            if day:
                day_cell = self.page.locator(
                    f'td:not([class*="disabled"]):not([class*="outside"]) >> text="{day}"'
                )
                if await day_cell.count() > 0:
                    await day_cell.first.click()

            return True
        except Exception as e:
            print(f"[浏览器] 日历选择失败 ({selector}): {e}")
            return False

    async def upload_file(self, selector: str, file_path: str) -> bool:
        try:
            if not os.path.exists(file_path):
                print(f"[浏览器] 文件不存在: {file_path}")
                return False
            locator = self.page.locator(selector)
            await locator.set_input_files(file_path)
            return True
        except Exception as e:
            print(f"[浏览器] 文件上传失败 ({selector}): {e}")
            return False

    async def find_elements(self, selector: str) -> list[Locator]:
        locator = self.page.locator(selector)
        count = await locator.count()
        return [locator.nth(i) for i in range(count)]

    async def get_element_text(self, selector: str) -> str:
        try:
            locator = self.page.locator(selector)
            return await locator.inner_text()
        except Exception:
            return ""

    async def get_element_attribute(self, selector: str, attr: str) -> str:
        try:
            locator = self.page.locator(selector)
            return await locator.get_attribute(attr) or ""
        except Exception:
            return ""

    async def is_element_visible(self, selector: str) -> bool:
        try:
            locator = self.page.locator(selector)
            return await locator.is_visible()
        except Exception:
            return False

    async def wait_for_element(self, selector: str, timeout: int = 10000) -> bool:
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def take_screenshot(self, path: str = "") -> str:
        if not path:
            path = os.path.join(tempfile.gettempdir(), "job_agent_screenshot.png")
        await self.page.screenshot(path=path, full_page=False)
        return path

    async def search_and_navigate(
        self,
        query: str,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """使用搜索引擎搜索并返回页面文本"""
        from urllib.parse import quote
        encoded_query = quote(query)
        
        search_engines = [
            f"https://www.bing.com/search?q={encoded_query}",
            f"https://html.duckduckgo.com/html/?q={encoded_query}",
        ]
        
        for i, search_url in enumerate(search_engines):
            print(f"[浏览器] 使用搜索引擎 {i+1}: {search_url[:60]}...")
            if progress_callback is not None:
                engine = "Bing" if i == 0 else "DuckDuckGo"
                await progress_callback(f"正在尝试搜索引擎 {i + 1}/2：{engine}")
            success = await self.navigate(
                search_url,
                max_retries=1,
                progress_callback=progress_callback,
            )
            if success:
                await self.wait_for_page_settle()
                page_text = await self.get_page_text()
                page_problem = await self.detect_page_problem()
                if page_problem:
                    print(f"[浏览器] 搜索引擎返回错误页: {page_problem}")
                    continue
                result_links = await self.get_search_result_links()
                if not result_links:
                    print("[浏览器] 搜索页未返回真实结果，尝试下一个搜索引擎...")
                    if progress_callback is not None:
                        await progress_callback(
                            "当前搜索引擎未返回真实结果，正在切换备用搜索源"
                        )
                    continue
                if "验证码" in page_text or "captcha" in page_text.lower():
                    print("[浏览器] 检测到验证码，尝试下一个搜索引擎...")
                    continue
                if "访问被拒绝" in page_text or "access denied" in page_text.lower():
                    print("[浏览器] 访问被拒绝，尝试下一个搜索引擎...")
                    continue
                return page_text
            
        print("[浏览器] 所有搜索引擎都失败")
        return ""

    async def find_links(self, text_pattern: str = "") -> list[dict[str, str]]:
        links = []
        try:
            if text_pattern:
                locator = self.page.locator(f'a:has-text("{text_pattern}")')
            else:
                locator = self.page.locator("a")

            count = await locator.count()
            for i in range(min(count, 20)):
                el = locator.nth(i)
                href = self.resolve_url(await el.get_attribute("href") or "")
                text = await el.inner_text()
                if href and text.strip():
                    links.append({"text": text.strip(), "href": href})
        except Exception as e:
            print(f"[浏览器] 查找链接失败: {e}")
        return links

    @staticmethod
    def _split_filter_terms(value: str) -> list[str]:
        return [
            item.strip()
            for item in re.split(r"[\s,，、;；/|]+", value or "")
            if item.strip() and item.strip() not in {"不限", "无"}
        ]

    @classmethod
    def _title_keyword_tokens(cls, job_keywords: str) -> tuple[list[str], bool]:
        """生成适合岗位标题匹配的领域词；返回是否应执行标题硬筛选。"""
        terms = cls._split_filter_terms(job_keywords)
        tokens = list(terms)
        domain_detected = False
        alias_groups = (
            (
                ("算法", "机器学习", "深度学习"),
                ("算法", "机器学习", "深度学习", "大模型", "感知", "规划"),
            ),
            (
                ("agent", "智能体"),
                ("Agent", "智能体", "大模型"),
            ),
            (
                ("软件", "software"),
                ("软件", "后端", "前端", "全栈"),
            ),
            (
                ("数据", "data"),
                ("数据", "数据库"),
            ),
            (
                ("机器人", "robot"),
                ("机器人", "具身智能"),
            ),
        )
        joined = " ".join(terms).lower()
        for markers, aliases in alias_groups:
            if any(marker.lower() in joined for marker in markers):
                domain_detected = True
                tokens.extend(aliases)
        # 单独填写 AI/人工智能时允许宽匹配；若同时指定“算法”，则不能仅凭
        # 标题里的 AI（如“AI 芯片编译器”）混入算法/Agent 候选。
        has_algorithm_intent = any(
            marker in joined for marker in ("算法", "机器学习", "深度学习")
        )
        if not has_algorithm_intent and any(
            marker in joined for marker in ("ai", "人工智能")
        ):
            domain_detected = True
            tokens.extend(("AI", "人工智能", "大模型", "机器学习", "算法"))
        return list(dict.fromkeys(token for token in tokens if token)), domain_detected

    @classmethod
    def parse_job_card(
        cls,
        text: str,
        href: str,
        preferred_cities: str = "",
        job_keywords: str = "",
    ) -> dict[str, Any] | None:
        """把招聘站岗位卡片转成稳定字段，并按地区做硬筛选、按关键词排序。"""
        lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
        if not lines or not href:
            return None

        cities = cls._split_filter_terms(preferred_cities)
        keywords = cls._split_filter_terms(job_keywords)
        searchable = "\n".join(lines)
        title = lines[0][:160]
        matched_cities = [city for city in cities if city.lower() in searchable.lower()]
        if cities and not matched_cities:
            return None

        body_keyword_matches = [
            keyword for keyword in keywords if keyword.lower() in searchable.lower()
        ]
        title_tokens, require_title_match = cls._title_keyword_tokens(job_keywords)
        title_keyword_matches = [
            token for token in title_tokens if token.lower() in title.lower()
        ]
        if keywords:
            if require_title_match and not title_keyword_matches:
                return None
            if not require_title_match and not body_keyword_matches:
                return None
        matched_keywords = list(
            dict.fromkeys(title_keyword_matches + body_keyword_matches)
        )
        location = "、".join(matched_cities)
        if not location and len(lines) > 1:
            location = lines[1][:100]

        reason_parts = []
        if matched_cities:
            reason_parts.append(f"地区匹配：{'、'.join(matched_cities)}")
        if matched_keywords:
            reason_parts.append(f"关键词匹配：{'、'.join(matched_keywords)}")
        if not reason_parts:
            reason_parts.append("招聘页中的可投递岗位")

        return {
            "name": title,
            "title": title,
            "location": location,
            "url": href,
            "jd": searchable[:1800],
            "reason": "；".join(reason_parts),
            "_score": (
                len(matched_cities) * 100
                + len(title_keyword_matches) * 30
                + len(body_keyword_matches) * 10
            ),
        }

    async def click_exact_text(self, text: str, timeout_ms: int = 4000) -> bool:
        """点击第一个完全匹配且可见的文本，适用于飞书招聘的城市筛选项。"""
        try:
            locator = self.page.get_by_text(text, exact=True)
            for index in range(min(await locator.count(), 20)):
                element = locator.nth(index)
                if await element.is_visible():
                    await element.click(timeout=max(500, timeout_ms))
                    await self.wait_for_page_settle()
                    return True
        except Exception as exc:
            print(f"[浏览器] 点击精确文本失败 ({text}): {exc}")
        return False

    async def select_city_filter(
        self,
        city: str,
        timeout_ms: int = 4000,
    ) -> dict[str, Any]:
        """选中飞书招聘城市复选框，并验证真实 checked 状态后才返回成功。"""
        try:
            container = self.page.locator('[data-test="TreeFilterCity"]')
            if await container.count() == 0:
                try:
                    await self.page.wait_for_selector(
                        '[data-test="TreeFilterCity"]',
                        state="visible",
                        timeout=15000,
                    )
                except Exception:
                    pass
            if await container.count() == 0:
                current_url = self.page.url
                current_host = (urlparse(current_url).hostname or "").lower()
                if current_host.endswith("jobs.feishu.cn"):
                    try:
                        await self.page.reload(
                            wait_until="domcontentloaded",
                            timeout=self.timeout,
                        )
                        await self.wait_for_page_settle(timeout_ms=8000)
                        await self.page.wait_for_selector(
                            '[data-test="TreeFilterCity"]',
                            state="visible",
                            timeout=15000,
                        )
                    except Exception:
                        pass
            if await container.count() == 0:
                return {
                    "success": False,
                    "selected": False,
                    "error": (
                        "等待并重载后仍没有飞书城市筛选控件；"
                        f"当前URL={self.page.url}"
                    ),
                }
            labels = container.get_by_text(city, exact=True)
            for index in range(min(await labels.count(), 20)):
                label = labels.nth(index)
                if not await label.is_visible():
                    continue
                row = label.locator("xpath=ancestor::li[1]")
                if await row.count() == 0:
                    continue
                classes = await row.get_attribute("class") or ""
                if "atsx-tree-treenode-checkbox-checked" in classes:
                    return {"success": True, "selected": True, "already_selected": True}

                checkbox = row.locator(".atsx-tree-checkbox")
                if await checkbox.count():
                    await checkbox.click(timeout=max(500, timeout_ms))
                else:
                    await label.click(timeout=max(500, timeout_ms))

                try:
                    await self.page.wait_for_function(
                        """({selector, city}) => {
                            const root = document.querySelector(selector);
                            if (!root) return false;
                            return [...root.querySelectorAll('li')].some(li =>
                                li.textContent.trim() === city &&
                                li.classList.contains('atsx-tree-treenode-checkbox-checked')
                            );
                        }""",
                        arg={"selector": '[data-test="TreeFilterCity"]', "city": city},
                        timeout=max(500, timeout_ms),
                    )
                except Exception:
                    pass
                classes = await row.get_attribute("class") or ""
                selected = "atsx-tree-treenode-checkbox-checked" in classes
                if selected:
                    await self.wait_for_page_settle(timeout_ms=3500)
                return {
                    "success": selected,
                    "selected": selected,
                    "already_selected": False,
                    "error": "" if selected else f"点击后未检测到“{city}”选中状态",
                }
            return {
                "success": False,
                "selected": False,
                "error": f"城市筛选中未找到“{city}”",
            }
        except Exception as exc:
            return {"success": False, "selected": False, "error": str(exc)}

    async def enter_oppo_campus_section(
        self,
        recruitment_type: str = "校招",
        timeout_ms: int = 5000,
    ) -> dict[str, Any]:
        """悬停 OPPO 校招类型卡片并点击该卡片自己的“马上启程”。"""
        section_title = (
            "实习生"
            if "实习" in (recruitment_type or "")
            else "应届生"
        )
        expected = "Intern" if section_title == "实习生" else "Graduate"
        target_url = (
            "https://careers.oppo.com/university/oppo/campus/post"
            f"?recruitType={expected}"
        )

        async def open_target_route() -> bool:
            """OPPO 长连接会卡住 DOMContentLoaded；只等导航提交，再等岗位卡片。"""
            for attempt in range(2):
                try:
                    await self.page.goto(
                        target_url,
                        wait_until="commit",
                        timeout=15000,
                    )
                except Exception:
                    if not self.navigation_reached_target(self.page.url, target_url):
                        if attempt == 0:
                            continue
                        return False
                try:
                    await self.page.wait_for_selector(
                        ".job__item",
                        state="visible",
                        timeout=25000,
                    )
                    return True
                except Exception:
                    if await self.page.locator(".job__item").count() > 0:
                        return True
                    if attempt == 0:
                        continue
            return False

        try:
            try:
                consent = self.page.get_by_text("同意", exact=True)
                for index in range(min(await consent.count(), 5)):
                    if await consent.nth(index).is_visible():
                        await consent.nth(index).click(timeout=2000)
                        break
            except Exception:
                pass
            try:
                await self.page.wait_for_selector(
                    ".types .item",
                    state="visible",
                    timeout=15000,
                )
            except Exception:
                pass
            cards = self.page.locator(".types .item").filter(has_text=section_title)
            for index in range(min(await cards.count(), 10)):
                card = cards.nth(index)
                if not await card.is_visible():
                    continue
                title = card.locator(".item__title")
                if await title.count() == 0 or (
                    await title.first.inner_text()
                ).strip() != section_title:
                    continue
                await card.scroll_into_view_if_needed(timeout=max(1000, timeout_ms))
                await card.hover(timeout=max(500, timeout_ms))
                await asyncio.sleep(0.6)
                button = card.get_by_text("马上启程", exact=True)
                if await button.count() == 0:
                    return {
                        "success": False,
                        "error": f"{section_title}卡片中没有“马上启程”",
                    }
                try:
                    await button.first.click(timeout=max(1000, timeout_ms))
                except Exception:
                    await button.first.click(
                        timeout=max(1000, timeout_ms),
                        force=True,
                    )
                try:
                    await self.page.wait_for_url(
                        re.compile(r"/campus/post\?recruitType="),
                        timeout=6000,
                    )
                except Exception:
                    pass
                await self.wait_for_page_settle(timeout_ms=5000)
                current_url = self.page.url
                success = (
                    "/campus/post" in current_url
                    and f"recruitType={expected}" in current_url
                )
                used_fallback = False
                if not success:
                    # OPPO 卡片由前端事件路由；网络慢或动画层拦截时直接访问
                    # 点击所对应的确定性路由，避免停留在 campus 首页。
                    used_fallback = True
                    success = await open_target_route()
                    current_url = self.page.url
                if success:
                    try:
                        await self.page.wait_for_selector(
                            ".job__item",
                            state="visible",
                            timeout=20000,
                        )
                    except Exception:
                        success = await self.page.locator(".job__item").count() > 0
                return {
                    "success": success,
                    "section": section_title,
                    "url": current_url,
                    "used_fallback": used_fallback,
                    "error": "" if success else "点击后未进入对应岗位列表",
                }
            # 卡片本身未及时渲染时，同样使用对应的确定性岗位路由。
            success = await open_target_route()
            if success:
                try:
                    await self.page.wait_for_selector(
                        ".job__item",
                        state="visible",
                        timeout=20000,
                    )
                except Exception:
                    success = await self.page.locator(".job__item").count() > 0
            return {
                "success": success,
                "section": section_title,
                "url": self.page.url,
                "used_fallback": True,
                "error": "" if success else f"未找到{section_title}卡片且直达岗位列表失败",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def select_oppo_checkbox(
        self,
        label_text: str,
        timeout_ms: int = 4000,
    ) -> dict[str, Any]:
        """点击 OPPO 岗位列表筛选项，并验证内部 input.checked。"""
        try:
            labels = self.page.locator("label.el-checkbox").filter(has_text=label_text)
            for index in range(min(await labels.count(), 30)):
                label = labels.nth(index)
                if not await label.is_visible():
                    continue
                visible_text = " ".join((await label.inner_text()).split())
                if label_text not in visible_text:
                    continue
                checkbox = label.locator('input[type="checkbox"]')
                if await checkbox.count() == 0:
                    continue
                if await checkbox.is_checked():
                    return {"success": True, "selected": True, "already_selected": True}
                await label.click(timeout=max(500, timeout_ms))
                try:
                    await checkbox.wait_for(state="attached", timeout=max(500, timeout_ms))
                except Exception:
                    pass
                selected = await checkbox.is_checked()
                if selected:
                    await self.wait_for_page_settle(timeout_ms=3500)
                return {
                    "success": selected,
                    "selected": selected,
                    "already_selected": False,
                    "error": "" if selected else f"点击后“{label_text}”未选中",
                }
            return {"success": False, "selected": False, "error": f"未找到筛选项“{label_text}”"}
        except Exception as exc:
            return {"success": False, "selected": False, "error": str(exc)}

    async def extract_oppo_job_cards(
        self,
        job_keywords: str = "",
        preferred_cities: str = "",
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """提取 OPPO campus/post 页面中已经展开显示完整 JD 的岗位卡片。"""
        locator = self.page.locator(".job__item")
        cards: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            for index in range(min(await locator.count(), 150)):
                element = locator.nth(index)
                title_locator = element.locator(".job_code")
                if await title_locator.count() == 0:
                    continue
                title = " ".join((await title_locator.first.inner_text()).split())
                if not title or title in seen:
                    continue
                text = await element.inner_text()
                synthetic_url = (
                    self.page.url.split("#", 1)[0]
                    + f"#job-title={quote(title, safe='')}"
                )
                card = self.parse_job_card(
                    text,
                    synthetic_url,
                    preferred_cities=preferred_cities,
                    job_keywords=job_keywords,
                )
                if card is not None:
                    seen.add(title)
                    cards.append(card)
        except Exception as exc:
            print(f"[浏览器] 提取 OPPO 岗位失败: {exc}")
        cards.sort(key=lambda item: item["_score"], reverse=True)
        for card in cards:
            card.pop("_score", None)
        return cards[: max(1, limit)]

    async def extract_matching_job_cards(
        self,
        job_keywords: str = "",
        preferred_cities: str = "",
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """从飞书等招聘列表页批量提取岗位，避免 Agent 逐页盲目打开岗位详情。"""
        selectors = (
            'a[href*="/position/"][href*="/detail"], '
            'a[href*="/jobs/"][href], '
            'a[href*="/job/"][href]'
        )
        locator = self.page.locator(selectors)
        cards: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            count = await locator.count()
            for index in range(min(count, 150)):
                element = locator.nth(index)
                href = self.resolve_url(await element.get_attribute("href") or "")
                if not href or href in seen:
                    continue
                text = await element.inner_text()
                card = self.parse_job_card(
                    text,
                    href,
                    preferred_cities=preferred_cities,
                    job_keywords=job_keywords,
                )
                if card is not None:
                    card["source_list_url"] = self.page.url
                    seen.add(href)
                    cards.append(card)
        except Exception as exc:
            print(f"[浏览器] 结构化提取岗位失败: {exc}")

        cards.sort(key=lambda item: item["_score"], reverse=True)
        for card in cards:
            card.pop("_score", None)
        return cards[: max(1, limit)]

    async def click_element_by_text(
        self,
        text: str,
        timeout_ms: int = 4000,
    ) -> dict:
        """查找并点击文本包含指定内容的可点击元素（button/a/[role=button]/input[type=button]）。
        取第一个可见元素进行点击。
        """
        try:
            locator = self.page.locator(
                f'button:has-text("{text}"), a:has-text("{text}"), '
                f'[role="button"]:has-text("{text}"), '
                f'input[type="button"][value*="{text}"]'
            )
            count = await locator.count()
            if count == 0:
                return {"success": False, "error": f"未找到文本包含 '{text}' 的可点击元素"}

            clicked = False
            for i in range(count):
                el = locator.nth(i)
                if await el.is_visible():
                    await el.click(timeout=max(500, timeout_ms))
                    clicked = True
                    break

            if not clicked:
                return {"success": False, "error": f"未找到可见的文本包含 '{text}' 的可点击元素"}

            await self.wait_for_page_settle()

            new_url = await self.get_current_url()
            try:
                page_text = await self.get_page_text()
                page_text_summary = page_text[:500]
            except Exception:
                page_text_summary = ""

            return {
                "success": True,
                "new_url": new_url,
                "page_text_summary": page_text_summary,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_visible_buttons(self) -> list[dict]:
        """获取页面所有可见可点击元素列表（button/a[href]/[role=button]/input[type=button]/input[type=submit]）。
        最多返回 30 个。
        """
        buttons: list[dict] = []
        try:
            locator = self.page.locator(
                "button, a[href], [role='button'], input[type='button'], input[type='submit']"
            )
            elements = await locator.all()
            for el in elements:
                if len(buttons) >= 30:
                    break
                try:
                    if not await el.is_visible():
                        continue
                    tag = await el.evaluate("el => el.tagName.toLowerCase()")
                    text = ""
                    if tag == "input":
                        text = await el.get_attribute("value") or ""
                    else:
                        try:
                            text = await el.inner_text()
                        except Exception:
                            text = await el.get_attribute("value") or await el.get_attribute("aria-label") or ""
                    text = (text or "").strip()
                    if not text:
                        continue
                    href = await el.get_attribute("href") or ""
                    role = await el.get_attribute("role") or ""
                    buttons.append({
                        "text": text,
                        "tag": tag,
                        "href": href,
                        "role": role,
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"[浏览器] 获取可见按钮失败: {e}")
        return buttons

    async def check_login_status(self) -> dict:
        """检测当前页面的登录状态。
        判断依据：登录/注册按钮、URL 关键词、用户头像/用户名等登录态元素。
        """
        indicators: list[str] = []
        logged_in = True

        try:
            page_text = await self.get_page_text()
        except Exception:
            page_text = ""

        try:
            current_url = await self.get_current_url()
        except Exception:
            current_url = ""

        # 1. 检查 URL 是否为登录/注册页面
        url_lower = current_url.lower()
        if any(kw in url_lower for kw in ["login", "signin", "register", "signup"]):
            indicators.append(f"URL含登录页标识: {current_url}")
            logged_in = False

        # 2. 检查页面是否含登录/注册按钮（未登录标识）
        login_button_keywords = ["登录", "注册", "login", "sign in", "sign in", "log in"]
        has_login_button = any(kw in page_text.lower() for kw in [k.lower() for k in login_button_keywords])
        if has_login_button:
            indicators.append("页面含登录/注册按钮文本")

        # 3. 检查是否存在用户头像/用户名等登录态元素
        logged_in_selectors = [
            ".avatar",
            ".user-name",
            "[class*='user-info']",
            "[class*='avatar']",
            "[class*='username']",
        ]
        has_user_element = False
        for sel in logged_in_selectors:
            try:
                if await self.is_element_visible(sel):
                    has_user_element = True
                    indicators.append(f"存在登录态元素: {sel}")
                    break
            except Exception:
                continue

        # 综合判断：有登录按钮且无登录态元素 => 未登录
        if has_login_button and not has_user_element:
            logged_in = False

        if not indicators:
            if logged_in:
                indicators.append("未检测到登录页/登录按钮，默认视为已登录")
            else:
                indicators.append("检测到登录页或登录按钮")

        return {
            "logged_in": logged_in,
            "indicators": indicators,
            "current_url": current_url,
        }

    async def get_form_fields(self) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        try:
            controls = self.page.locator(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), '
                'textarea, select, [role="combobox"], [contenteditable="true"]'
            )
            for index in range(min(await controls.count(), 160)):
                el = controls.nth(index)
                if not await el.is_visible():
                    continue
                metadata = await el.evaluate(
                    """el => {
                      const id = el.id || '';
                      const labels = [];
                      if (el.labels) labels.push(...[...el.labels].map(x => x.innerText));
                      if (id) {
                        const linked = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                        if (linked) labels.push(linked.innerText);
                      }
                      let section = '';
                      let parent = el.parentElement;
                      for (let depth = 0; parent && depth < 4; depth++, parent = parent.parentElement) {
                        const cls = String(parent.className || '');
                        if (/form|field|item|control|section/i.test(cls)) {
                          section = String(parent.innerText || '').replace(/\\s+/g, ' ').slice(0, 240);
                          if (section) break;
                        }
                      }
                      return {
                        tag: el.tagName.toLowerCase(),
                        type: el.type || el.getAttribute('role') || el.tagName.toLowerCase(),
                        id,
                        name: el.name || '',
                        placeholder: el.placeholder || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        data_field_key: el.getAttribute('data-field-key') || '',
                        label: labels.filter(Boolean).join(' / '),
                        section,
                        required: Boolean(el.required || el.getAttribute('aria-required') === 'true'),
                        value: el.type === 'file' ? (el.files && el.files.length ? el.files[0].name : '') : (el.value || el.innerText || '')
                      };
                    }"""
                )
                tag = metadata.get("tag") or "input"
                field_id = metadata.get("id") or ""
                name = metadata.get("name") or ""
                data_key = metadata.get("data_field_key") or ""
                if data_key:
                    selector = f'[data-field-key={json.dumps(data_key)}]'
                elif field_id:
                    selector = f'[id={json.dumps(field_id)}]'
                elif name:
                    selector = f'{tag}[name={json.dumps(name)}]'
                else:
                    runtime_key = f"field-{index}"
                    await el.evaluate(
                        "(node, value) => node.setAttribute('data-findjob-field-id', value)",
                        runtime_key,
                    )
                    selector = f'[data-findjob-field-id="{runtime_key}"]'
                options = (
                    await el.locator("option").all_inner_texts()
                    if tag == "select"
                    else []
                )
                fields.append(
                    {
                        **metadata,
                        "selector": selector,
                        "options": options,
                    }
                )
        except Exception as e:
            print(f"[浏览器] 获取表单字段失败: {e}")
        return fields
