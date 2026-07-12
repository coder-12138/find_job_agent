import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Locator


class BrowserAutomation:
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @classmethod
    async def get_shared(cls, headless: bool = True, timeout: int = 30000) -> "BrowserAutomation":
        if cls._instance is None:
            cls._instance = cls(headless=headless, timeout=timeout)
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
        
        launch_args = []
        if self.headless:
            launch_args.append("--disable-blink-features=AutomationControlled")
        
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=launch_args
        )
        
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        self._context.set_default_timeout(self.timeout)
        self._page = await self._context.new_page()
        return self._page

    async def close(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    async def navigate(self, url: str) -> bool:
        """导航到指定URL，带重试机制"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await self.page.goto(
                    url, 
                    wait_until="load",
                    timeout=self.timeout
                )
                if response:
                    if response.status >= 400:
                        print(f"[浏览器] 页面返回错误状态码: {response.status}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        return False
                return True
            except Exception as e:
                error_msg = str(e)
                if "ERR_ABORTED" in error_msg:
                    await asyncio.sleep(1)
                    try:
                        current_url = self.page.url
                        if current_url and current_url != "about:blank":
                            print(f"[浏览器] 页面已加载 (URL: {current_url})")
                            return True
                    except:
                        pass
                
                print(f"[浏览器] 导航失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[浏览器] 等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    return False
        return False

    async def get_page_content(self) -> str:
        return await self.page.content()

    async def get_page_text(self) -> str:
        return await self.page.inner_text("body")

    async def get_current_url(self) -> str:
        return self.page.url

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

    async def search_and_navigate(self, query: str) -> str:
        """使用搜索引擎搜索并返回页面文本"""
        from urllib.parse import quote
        encoded_query = quote(query)
        
        search_engines = [
            f"https://www.bing.com/search?q={encoded_query}",
            f"https://duckduckgo.com/html/?q={encoded_query}",
        ]
        
        for i, search_url in enumerate(search_engines):
            print(f"[浏览器] 使用搜索引擎 {i+1}: {search_url[:60]}...")
            success = await self.navigate(search_url)
            if success:
                await asyncio.sleep(2)
                page_text = await self.get_page_text()
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
                href = await el.get_attribute("href") or ""
                text = await el.inner_text()
                if href and text.strip():
                    links.append({"text": text.strip(), "href": href})
        except Exception as e:
            print(f"[浏览器] 查找链接失败: {e}")
        return links

    async def get_form_fields(self) -> list[dict[str, Any]]:
        fields = []
        try:
            inputs = self.page.locator("input:not([type='hidden']):not([type='submit']):not([type='button'])")
            input_count = await inputs.count()
            for i in range(input_count):
                el = inputs.nth(i)
                input_type = await el.get_attribute("type") or "text"
                name = await el.get_attribute("name") or ""
                placeholder = await el.get_attribute("placeholder") or ""
                label_text = ""
                if name:
                    label = self.page.locator(f'label[for="{name}"]')
                    if await label.count() > 0:
                        label_text = await label.inner_text()
                fields.append({
                    "type": input_type,
                    "name": name,
                    "placeholder": placeholder,
                    "label": label_text,
                    "selector": f'input[name="{name}"]' if name else f'input[type="{input_type}"]:nth-of-type({i+1})',
                })

            selects = self.page.locator("select")
            select_count = await selects.count()
            for i in range(select_count):
                el = selects.nth(i)
                name = await el.get_attribute("name") or ""
                label_text = ""
                if name:
                    label = self.page.locator(f'label[for="{name}"]')
                    if await label.count() > 0:
                        label_text = await label.inner_text()
                options = await el.locator("option").all_inner_texts()
                fields.append({
                    "type": "select",
                    "name": name,
                    "label": label_text,
                    "options": options,
                    "selector": f'select[name="{name}"]' if name else f'select:nth-of-type({i+1})',
                })

            textareas = self.page.locator("textarea")
            textarea_count = await textareas.count()
            for i in range(textarea_count):
                el = textareas.nth(i)
                name = await el.get_attribute("name") or ""
                placeholder = await el.get_attribute("placeholder") or ""
                fields.append({
                    "type": "textarea",
                    "name": name,
                    "placeholder": placeholder,
                    "selector": f'textarea[name="{name}"]' if name else f'textarea:nth-of-type({i+1})',
                })
        except Exception as e:
            print(f"[浏览器] 获取表单字段失败: {e}")
        return fields
