"""Defensive Feishu Recruiting page adapter.

The adapter may navigate, inspect, and fill reviewed values.  It deliberately
contains no method that clicks a final-submit control.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Locator, Page


@dataclass(slots=True)
class PageInspection:
    kind: str
    url: str
    fingerprint: str
    message: str
    filled_fields: list[str] = field(default_factory=list)
    skipped_fields: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


FIELD_PATTERNS: dict[str, list[str]] = {
    "full_name": ["姓名", "名字", "name"],
    "email": ["邮箱", "电子邮件", "email", "mail"],
    "phone": ["手机", "电话", "phone", "mobile"],
    "gender": ["性别", "gender"],
    "birthday": ["出生日期", "生日", "birthday"],
    "current_city": ["现居住城市", "当前城市", "现居地", "current city"],
    "address": ["详细地址", "通讯地址", "联系地址", "address"],
    "wechat": ["微信号", "微信", "wechat"],
    "school": ["学校名称", "毕业院校", "学校", "院校", "school"],
    "degree": ["学历", "学位", "degree"],
    "major": ["专业名称", "所学专业", "专业", "major"],
    "college": ["学院名称", "学院", "college"],
    "gpa": ["绩点", "GPA"],
    "company": ["公司名称", "单位名称", "实习单位", "company"],
    "position": ["职位名称", "岗位名称", "担任职位", "position"],
    "department": ["部门名称", "所在部门", "department"],
    "project_name": ["项目名称", "project name"],
    "project_role": ["项目角色", "担任角色", "project role"],
    "project_description": ["项目描述", "项目内容", "project description"],
    "self_introduction": ["自我介绍", "个人总结", "自我评价", "self introduction"],
    "skills_text": ["专业技能", "技能描述", "技能", "skills"],
}


class FeishuRecruitingAdapter:
    async def install_learning_probe(self, page: Page) -> None:
        script = """
        (() => {
          if (window.__findjobProbeInstalled) return;
          window.__findjobProbeInstalled = true;
          try {
            window.__findjobManualInteractions = JSON.parse(sessionStorage.getItem('__findjobManualInteractions') || '[]');
          } catch (_) {
            window.__findjobManualInteractions = [];
          }
          document.addEventListener('change', (event) => {
            const el = event.target;
            if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement)) return;
            let strategy = '';
            let locator = '';
            if (el.getAttribute('data-field-key')) {
              strategy = 'data-field-key'; locator = el.getAttribute('data-field-key');
            } else if (el.name) {
              strategy = 'name'; locator = el.name;
            } else if (el.getAttribute('aria-label')) {
              strategy = 'aria-label'; locator = el.getAttribute('aria-label');
            } else if (el.placeholder) {
              strategy = 'placeholder'; locator = el.placeholder;
            }
            if (!strategy || !locator) return;
            const label = el.labels && el.labels.length ? el.labels[0].innerText : '';
            window.__findjobManualInteractions.push({
              strategy, locator, signal: [label, el.name, el.placeholder, el.getAttribute('aria-label')].filter(Boolean).join(' ')
            });
            sessionStorage.setItem('__findjobManualInteractions', JSON.stringify(window.__findjobManualInteractions));
          }, true);
        })();
        """
        await page.add_init_script(script)
        await page.evaluate(script)

    async def collect_manual_hints(self, page: Page) -> list[dict[str, str]]:
        interactions = await page.evaluate(
            "() => { const items = window.__findjobManualInteractions || []; window.__findjobManualInteractions = []; sessionStorage.removeItem('__findjobManualInteractions'); return items; }"
        )
        result: list[dict[str, str]] = []
        for item in interactions:
            result.append(
                {
                    "field_key": self._infer_field_key(item.get("signal", "")),
                    "locator_strategy": item["strategy"],
                    "locator_value": item["locator"],
                }
            )
        return result

    async def navigate_to_application(
        self, page: Page, source_url: str
    ) -> dict[str, Any]:
        if page.url != source_url:
            await page.goto(source_url, wait_until="domcontentloaded", timeout=45_000)
        if await self._is_application_form(page):
            return {"action": "already_form", "url": page.url}
        if await self._is_login(page):
            return {"action": "login_required", "url": page.url}
        apply_links = page.locator(
            'a[href*="apply"], button:has-text("申请"), button:has-text("投递"), '
            'button:has-text("应聘"), a:has-text("申请"), a:has-text("投递"), '
            'a:has-text("应聘"), [role="button"]:has-text("申请"), '
            '[role="button"]:has-text("投递"), [role="button"]:has-text("应聘")'
            ', [class*="btn"]:has-text("申请"), [class*="btn"]:has-text("投递")'
            ', [class*="button"]:has-text("申请"), [class*="button"]:has-text("投递")'
        )
        for index in range(min(await apply_links.count(), 30)):
            candidate = apply_links.nth(index)
            if not await candidate.is_visible():
                continue
            text = " ".join((await candidate.inner_text()).split())
            if (
                not text
                or len(text) > 18
                or not re.search(r"(申请|投递|应聘)", text)
                or re.search(r"(记录|进度|状态|历史)", text)
            ):
                continue
            await candidate.click()
            return {
                "action": "application_clicked",
                "url": page.url,
                "text": text,
            }
        return {"action": "application_action_not_found", "url": page.url}

    async def inspect(self, page: Page) -> PageInspection:
        fingerprint = await self.fingerprint(page)
        state = page.locator("[data-submission-state]")
        if await state.count():
            value = await state.first.get_attribute("data-submission-state")
            text = (await state.first.inner_text()).strip()
            kind = {"submitted": "submitted", "unknown": "outcome_unknown", "rejected": "failed"}.get(
                value or "", "outcome_unknown"
            )
            receipt = page.locator("[data-submission-receipt]")
            receipt_text = (await receipt.first.inner_text()).strip() if await receipt.count() else None
            return PageInspection(
                kind,
                page.url,
                fingerprint,
                text or kind,
                evidence={"summary": text or kind, "url": page.url, "receipt": receipt_text},
            )
        if await self._is_login(page):
            return PageInspection(
                "login_required",
                page.url,
                fingerprint,
                "请在此受管浏览器窗口完成登录；不要复制到其他浏览器，登录状态保存在这个专用档案中。",
            )
        if await self._is_application_form(page):
            return PageInspection(
                "application_form",
                page.url,
                fingerprint,
                "已识别申请表单，可以填入已核对字段。",
            )
        return PageInspection(
            "blocked",
            page.url,
            fingerprint,
            "未识别到登录页或申请表单，需要人工在受管窗口导航到申请表单后继续。",
        )

    async def fill_reviewed_values(
        self,
        page: Page,
        values: dict[str, Any],
        *,
        approved_hints: list[dict[str, str]] | None = None,
        resume: tuple[str, bytes] | None = None,
    ) -> PageInspection:
        inspection = await self.inspect(page)
        if inspection.kind != "application_form":
            return inspection
        filled: list[str] = []
        skipped: list[str] = []
        hints_by_field: dict[str, list[dict[str, str]]] = {}
        for hint in approved_hints or []:
            hints_by_field.setdefault(hint["field_key"], []).append(hint)
        for key, value in values.items():
            if value is None or value == "" or isinstance(value, (dict, list)):
                continue
            locator = await self._field_locator(page, key, hints_by_field.get(key, []))
            if locator is None:
                skipped.append(key)
                continue
            try:
                await self._fill_locator_value(page, locator, str(value))
                filled.append(key)
            except Exception:
                skipped.append(key)
        if resume:
            upload = page.locator('input[type="file"]')
            if await upload.count():
                await upload.first.set_input_files(
                    {"name": resume[0], "mimeType": "application/pdf", "buffer": resume[1]}
                )
                filled.append("resume")
        return PageInspection(
            "ready_for_user_submit",
            page.url,
            await self.fingerprint(page),
            "字段已填入。请逐项核对并由你亲自点击最终提交；系统不会代点提交按钮。",
            filled_fields=sorted(set(filled)),
            skipped_fields=sorted(set(skipped)),
        )

    async def fill_profile(
        self,
        page: Page,
        profile: dict[str, Any],
        *,
        reviewed_resume: dict[str, Any] | None = None,
        resume_path: str = "",
    ) -> PageInspection:
        """Upload once, wait for site parsing, then deterministically prefill known fields."""

        inspection = await self.inspect(page)
        if inspection.kind != "application_form":
            return inspection

        uploaded = False
        upload = page.locator('input[type="file"]')
        if resume_path and await upload.count():
            target_upload = upload.first
            try:
                existing = await target_upload.input_value()
            except Exception:
                existing = ""
            if not existing:
                await target_upload.set_input_files(resume_path)
                uploaded = True
                await self._wait_for_form_stability(page)

        personal = profile.get("personal_info") or {}
        education = (profile.get("education") or [{}])[0] or {}
        work = (profile.get("work_experience") or [{}])[0] or {}
        project = (profile.get("project_experience") or [{}])[0] or {}
        reviewed = reviewed_resume or {}
        reviewed_projects = reviewed.get("project_highlights") or []
        reviewed_work = reviewed.get("work_highlights") or []
        if reviewed_projects and isinstance(reviewed_projects[0], dict):
            project = {**project, **reviewed_projects[0]}
        if reviewed_work and isinstance(reviewed_work[0], dict):
            work = {**work, **reviewed_work[0]}

        added_sections: list[str] = []
        if education and any(education.values()):
            if await self._ensure_structured_section(
                page, "school", re.compile(r"(添加|新增).*(教育|学历)|(教育|学历).*(添加|新增)")
            ):
                added_sections.append("education")
        if work and any(work.values()):
            if await self._ensure_structured_section(
                page, "company", re.compile(r"(添加|新增).*(工作|实习)|(工作|实习).*(添加|新增)")
            ):
                added_sections.append("work_experience")
        if project and any(project.values()):
            if await self._ensure_structured_section(
                page, "project_name", re.compile(r"(添加|新增).*项目|项目.*(添加|新增)")
            ):
                added_sections.append("project_experience")

        skills = profile.get("skills") or []
        skill_names = [
            str(item.get("name") or item.get("skill") or "").strip()
            for item in skills
            if isinstance(item, dict)
        ]
        values = {
            "full_name": personal.get("name") or personal.get("full_name"),
            "email": personal.get("email"),
            "phone": personal.get("phone"),
            "gender": personal.get("gender"),
            "birthday": personal.get("birthday"),
            "current_city": personal.get("current_city") or personal.get("city"),
            "address": personal.get("address"),
            "wechat": personal.get("wechat"),
            "school": education.get("school"),
            "degree": education.get("degree"),
            "major": education.get("major"),
            "college": education.get("college"),
            "gpa": education.get("gpa"),
            "company": work.get("company"),
            "position": work.get("position"),
            "department": work.get("department"),
            "project_name": project.get("name"),
            "project_role": project.get("role"),
            "project_description": project.get("description"),
            "self_introduction": reviewed.get("self_introduction")
            or profile.get("self_introduction"),
            "skills_text": "、".join(filter(None, skill_names)),
        }
        result = await self.fill_reviewed_values(page, values)
        if uploaded:
            result.filled_fields.append("resume")
            result.filled_fields = sorted(set(result.filled_fields))
        result.evidence.update(
            {
                "resume_uploaded": uploaded,
                "known_value_count": sum(
                    value not in (None, "") for value in values.values()
                ),
                "visible_control_count": await self._visible_control_count(page),
                "added_sections": added_sections,
            }
        )
        return result

    async def fingerprint(self, page: Page) -> str:
        signature = await page.evaluate(
            """() => Array.from(document.querySelectorAll('input,textarea,select,button'))
              .map(el => [el.tagName, el.getAttribute('name'), el.getAttribute('type'), el.getAttribute('data-field-key'), el.getAttribute('aria-label'), el.getAttribute('placeholder')])"""
        )
        parsed = urlparse(page.url)
        stable = json.dumps(
            {"host": parsed.hostname, "path": parsed.path, "controls": signature},
            ensure_ascii=False,
            sort_keys=True,
        )
        return sha256(stable.encode("utf-8")).hexdigest()

    async def _field_locator(
        self, page: Page, field_key: str, hints: list[dict[str, str]]
    ) -> Locator | None:
        candidates: list[Locator] = [
            page.locator(f'[data-field-key="{field_key}"]'),
            page.locator(f'[name="{field_key}"]'),
        ]
        for hint in hints:
            strategy = hint["locator_strategy"]
            value = hint["locator_value"]
            if strategy == "data-field-key":
                candidates.append(page.locator(f'[data-field-key="{value}"]'))
            elif strategy == "name":
                candidates.append(page.locator(f'[name="{value}"]'))
            elif strategy == "aria-label":
                candidates.append(page.get_by_label(value, exact=True))
            elif strategy == "placeholder":
                candidates.append(page.get_by_placeholder(value, exact=True))
        for pattern in FIELD_PATTERNS.get(field_key, [field_key]):
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
            candidates.extend(
                [
                    page.get_by_label(regex),
                    page.get_by_placeholder(regex),
                    page.locator(
                        f'input[name*="{pattern}" i], textarea[name*="{pattern}" i], select[name*="{pattern}" i]'
                    ),
                ]
            )
        for candidate in candidates:
            try:
                if await candidate.count() and await candidate.first.is_visible():
                    return candidate.first
            except Exception:
                continue
        patterns = FIELD_PATTERNS.get(field_key, [field_key])
        controls = page.locator(
            'input:not([type="hidden"]):not([type="file"]), textarea, select, '
            '[contenteditable="true"], [role="combobox"]'
        )
        for index in range(min(await controls.count(), 120)):
            candidate = controls.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                signal = await candidate.evaluate(
                    """el => {
                      const parts = [el.name, el.id, el.placeholder,
                        el.getAttribute('aria-label'), el.getAttribute('data-field-key')];
                      if (el.labels) parts.push(...[...el.labels].map(x => x.innerText));
                      if (el.id) {
                        const linked = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (linked) parts.push(linked.innerText);
                      }
                      let parent = el.parentElement;
                      for (let depth = 0; parent && depth < 4; depth++, parent = parent.parentElement) {
                        const cls = String(parent.className || '');
                        if (/form|field|item|control|section/i.test(cls)) {
                          parts.push(String(parent.innerText || '').slice(0, 240));
                        }
                      }
                      return parts.filter(Boolean).join(' ');
                    }"""
                )
                lowered = str(signal).lower()
                if any(pattern.lower() in lowered for pattern in patterns):
                    return candidate
            except Exception:
                continue
        return None

    async def _fill_locator_value(
        self, page: Page, locator: Locator, value: str
    ) -> None:
        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await locator.get_attribute("type") or "").lower()
        role = (await locator.get_attribute("role") or "").lower()
        readonly = await locator.get_attribute("readonly")
        if tag == "select":
            try:
                await locator.select_option(label=value)
            except Exception:
                await locator.select_option(value=value)
            return
        if input_type in {"radio", "checkbox"}:
            container = locator.locator(
                "xpath=ancestor::*[contains(@class,'form') or contains(@class,'field') or contains(@class,'item')][1]"
            )
            choices = (
                container.get_by_text(value, exact=True)
                if await container.count()
                else page.get_by_text(value, exact=True)
            )
            for index in range(min(await choices.count(), 20)):
                if await choices.nth(index).is_visible():
                    await choices.nth(index).click()
                    return
            await locator.check()
            return
        if role == "combobox" or readonly is not None:
            await locator.click()
            choices = page.get_by_text(value, exact=True)
            for index in range(min(await choices.count(), 30)):
                if await choices.nth(index).is_visible():
                    await choices.nth(index).click()
                    return
            if readonly is None:
                await locator.fill(value)
                await locator.press("ArrowDown")
                await locator.press("Enter")
                return
            raise ValueError(f"下拉字段没有找到选项：{value}")
        if tag == "input" or tag == "textarea":
            await locator.fill(value)
            return
        await locator.fill(value)

    async def _ensure_structured_section(
        self, page: Page, field_key: str, add_pattern: re.Pattern[str]
    ) -> bool:
        if await self._field_locator(page, field_key, []) is not None:
            return False
        actions = page.locator("button, a, [role='button']").filter(
            has_text=add_pattern
        )
        for index in range(min(await actions.count(), 30)):
            action = actions.nth(index)
            try:
                if not await action.is_visible():
                    continue
                await action.click()
                await page.wait_for_timeout(800)
                return True
            except Exception:
                continue
        return False

    async def _wait_for_form_stability(
        self, page: Page, timeout_seconds: float = 20.0
    ) -> None:
        started = asyncio.get_running_loop().time()
        previous = None
        stable_rounds = 0
        while asyncio.get_running_loop().time() - started < timeout_seconds:
            await page.wait_for_timeout(1000)
            signature = await page.evaluate(
                """() => Array.from(document.querySelectorAll('input,textarea,select,[role="combobox"]'))
                  .map(el => [el.name, el.id, el.placeholder, el.type, el.value]).flat().join('|')"""
            )
            if signature == previous:
                stable_rounds += 1
            else:
                stable_rounds = 0
                previous = signature
            elapsed = asyncio.get_running_loop().time() - started
            if elapsed >= 5 and stable_rounds >= 2:
                return

    @staticmethod
    async def _visible_control_count(page: Page) -> int:
        controls = page.locator(
            'input:not([type="hidden"]), textarea, select, [role="combobox"]'
        )
        visible = 0
        for index in range(min(await controls.count(), 200)):
            try:
                visible += int(await controls.nth(index).is_visible())
            except Exception:
                continue
        return visible

    async def _is_login(self, page: Page) -> bool:
        path = urlparse(page.url).path.lower()
        if "login" in path or "passport" in path:
            return True
        passwords = page.locator('input[type="password"]')
        login_buttons = page.locator('button:has-text("登录"), button:has-text("Sign in")')
        return bool(await passwords.count() or await login_buttons.count())

    async def _is_application_form(self, page: Page) -> bool:
        final = page.locator(
            '[data-final-submit="true"], button:has-text("提交申请"), '
            'button:has-text("确认投递"), button:has-text("投递简历"), '
            'button:has-text("保存简历"), button:has-text("下一步")'
        )
        if await final.count():
            return True
        inputs = page.locator("form input, form textarea, form select")
        if await inputs.count() >= 2:
            return True

        # 飞书招聘的部分申请页由 React 组件组成，不一定存在原生 form 标签。
        path = urlparse(page.url).path.lower()
        route_signal = any(
            token in path for token in ("/apply", "/resume", "/application")
        )
        upload = page.locator('input[type="file"]')
        controls = page.locator(
            'input:not([type="hidden"]):not([type="search"]), textarea, select'
        )
        visible_controls = 0
        for index in range(min(await controls.count(), 30)):
            try:
                if await controls.nth(index).is_visible():
                    visible_controls += 1
            except Exception:
                continue
        body_text = " ".join((await page.locator("body").inner_text()).split())
        field_signals = sum(
            signal in body_text
            for signal in ("姓名", "手机号", "邮箱", "教育经历", "工作经历", "上传简历")
        )
        return bool(
            (route_signal and visible_controls >= 2)
            or (await upload.count() and visible_controls >= 1)
            or (visible_controls >= 3 and field_signals >= 2)
        )

    @staticmethod
    def _infer_field_key(signal: str) -> str:
        lowered = signal.lower()
        for key, patterns in FIELD_PATTERNS.items():
            if any(pattern.lower() in lowered for pattern in patterns):
                return key
        return "unclassified"
