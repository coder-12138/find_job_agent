"""Single-owner Playwright coordinator with persistent, dedicated login state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from job_application_agent_langchain.application.applications import (
    ApplicationConflictError,
    ApplicationService,
)
from job_application_agent_langchain.application.file_resources import FileResourceService
from job_application_agent_langchain.browser_runtime.feishu import (
    FeishuRecruitingAdapter,
    PageInspection,
)


@dataclass(frozen=True, slots=True)
class BrowserTaskResult:
    application_id: str
    task_id: str
    state: str
    message: str
    page_url: str | None
    page_fingerprint: str | None
    filled_fields: list[str]
    skipped_fields: list[str]


class BrowserCoordinator:
    """Own exactly one persistent browser context for the whole process."""

    def __init__(
        self,
        applications: ApplicationService,
        files: FileResourceService,
        profile_dir: Path,
        *,
        adapter: FeishuRecruitingAdapter | None = None,
        headless: bool | None = None,
    ):
        self.applications = applications
        self.files = files
        self.profile_dir = profile_dir
        self.adapter = adapter or FeishuRecruitingAdapter()
        self.headless = (
            os.getenv("JOB_AGENT_BROWSER_HEADLESS", "0") == "1"
            if headless is None
            else headless
        )
        self._lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._pages: dict[str, Page] = {}

    async def open_application(self, application_id: str) -> BrowserTaskResult:
        async with self._lock:
            application = self.applications.get_application(application_id)
            if application.state != "awaiting_login":
                raise ApplicationConflictError("请先核对申请材料并确认进入登录阶段")
            page = await self._page(application_id)
            await self.adapter.install_learning_probe(page)
            task_id = self._start_task(application_id)
            try:
                await self.adapter.navigate_to_application(page, application.source_url)
                inspection = await self.adapter.inspect(page)
                if inspection.kind == "application_form":
                    inspection = await self._fill(application_id, page)
                result = self._finish_task(task_id, application_id, inspection)
                return result
            except Exception as exc:
                self._fail_task(task_id, str(exc))
                raise

    async def continue_after_takeover(self, application_id: str) -> BrowserTaskResult:
        async with self._lock:
            application = self.applications.get_application(application_id)
            if application.state != "awaiting_login":
                raise ApplicationConflictError("当前申请不在等待登录/人工导航阶段")
            page = self._pages.get(application_id)
            if page is None or page.is_closed():
                page = await self._page(application_id)
                await self.adapter.navigate_to_application(page, application.source_url)
            await self._capture_manual_hints(application_id, page)
            inspection = await self.adapter.inspect(page)
            if inspection.kind == "application_form":
                inspection = await self._fill(application_id, page)
            task_id = self._start_task(application_id)
            return self._finish_task(task_id, application_id, inspection)

    async def observe_submission(self, application_id: str) -> BrowserTaskResult:
        async with self._lock:
            application = self.applications.get_application(application_id)
            if application.state != "awaiting_user_submit":
                raise ApplicationConflictError("当前申请不在等待最终提交阶段")
            page = self._pages.get(application_id)
            if page is None or page.is_closed():
                inspection = PageInspection(
                    "outcome_unknown",
                    application.source_url,
                    "browser-closed",
                    "受管浏览器已关闭，无法验证提交回执。",
                    evidence={"summary": "浏览器关闭，未观察到可验证回执"},
                )
            else:
                await self._capture_manual_hints(application_id, page)
                inspection = await self.adapter.inspect(page)
            task_id = self._start_task(application_id)
            if inspection.kind in {"submitted", "outcome_unknown", "failed"}:
                application = self.applications.record_submission_outcome(
                    application_id,
                    outcome=inspection.kind,
                    evidence=inspection.evidence
                    or {"summary": inspection.message, "url": inspection.url},
                    expected_version=application.row_version,
                )
                result = self._finish_task(task_id, application_id, inspection, completed=True)
                await self._close_page(application_id)
                return result
            inspection.message = "尚未发现提交回执；请在受管窗口完成提交后再次检查。"
            return self._finish_task(task_id, application_id, inspection)

    def list_hints(self, *, review_status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM interaction_hints"
        params: tuple[Any, ...] = ()
        if review_status:
            query += " WHERE review_status = ?"
            params = (review_status,)
        query += " ORDER BY updated_at DESC"
        with self.applications.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def review_hint(self, hint_id: str, *, status: str) -> dict[str, Any]:
        if status not in {"approved", "disabled"}:
            raise ValueError("hint status must be approved or disabled")
        with self.applications.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE interaction_hints SET review_status = ?, updated_at = ? WHERE id = ?",
                (status, self._now(), hint_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(hint_id)
            connection.commit()
            return dict(
                connection.execute(
                    "SELECT * FROM interaction_hints WHERE id = ?", (hint_id,)
                ).fetchone()
            )

    async def close(self) -> None:
        async with self._lock:
            if self._context is not None:
                await self._context.close()
                self._context = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
            self._pages.clear()

    async def _fill(self, application_id: str, page: Page) -> PageInspection:
        application = self.applications.get_application(application_id)
        hints = self._approved_hints(await self.adapter.fingerprint(page))
        resume = self._resume_payload(application_id)
        inspection = await self.adapter.fill_reviewed_values(
            page,
            application.form_values or {},
            approved_hints=hints,
            resume=resume,
        )
        if inspection.kind == "ready_for_user_submit":
            self.applications.transition(
                application_id,
                to_state="awaiting_user_submit",
                reason=inspection.message,
                expected_version=application.row_version,
                actor_type="browser_worker",
            )
        return inspection

    async def _page(self, application_id: str) -> Page:
        await self._ensure_context()
        existing = self._pages.get(application_id)
        if existing is not None and not existing.is_closed():
            return existing
        page = await self._context.new_page()
        self._pages[application_id] = page
        return page

    async def _ensure_context(self) -> None:
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        size_options = (
            {"viewport": {"width": 1440, "height": 960}}
            if self.headless
            else {"no_viewport": True}
        )
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if not self.headless:
            launch_args.append("--start-maximized")
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            args=launch_args,
            **size_options,
        )

    def _resume_payload(self, application_id: str) -> tuple[str, bytes] | None:
        with self.applications.database.connect() as connection:
            row = connection.execute(
                """
                SELECT f.id, f.original_name
                FROM application_materials m
                JOIN file_resources f ON f.id = m.file_resource_id
                WHERE m.application_id = ? AND m.kind = 'original_resume'
                """,
                (application_id,),
            ).fetchone()
        if row is None:
            return None
        return row["original_name"], self.files.read(row["id"])

    def _approved_hints(self, fingerprint: str) -> list[dict[str, str]]:
        with self.applications.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT field_key, locator_strategy, locator_value
                FROM interaction_hints
                WHERE platform = 'feishu_recruiting'
                  AND page_fingerprint = ? AND review_status = 'approved'
                """,
                (fingerprint,),
            ).fetchall()
        return [dict(row) for row in rows]

    async def _capture_manual_hints(self, application_id: str, page: Page) -> None:
        hints = await self.adapter.collect_manual_hints(page)
        if not hints:
            return
        fingerprint = await self.adapter.fingerprint(page)
        now = self._now()
        with self.applications.database.connect() as connection:
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
        with self.applications.database.connect() as connection:
            self.applications._audit(
                connection=connection,
                application_id=application_id,
                event_type="browser.manual_interactions_observed",
                payload={"hint_count": len(hints), "page_fingerprint": fingerprint},
                actor_type="browser_observer",
            )
            connection.commit()

    def _start_task(self, application_id: str) -> str:
        task_id = uuid4().hex
        now = self._now()
        with self.applications.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO browser_tasks(id, application_id, state, created_at, updated_at)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (task_id, application_id, now, now),
            )
            connection.commit()
        return task_id

    def _finish_task(
        self,
        task_id: str,
        application_id: str,
        inspection: PageInspection,
        *,
        completed: bool = False,
    ) -> BrowserTaskResult:
        state = "completed" if completed else "waiting_user"
        with self.applications.database.connect() as connection:
            connection.execute(
                """
                UPDATE browser_tasks
                SET state = ?, page_url = ?, page_fingerprint = ?, message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    state,
                    inspection.url,
                    inspection.fingerprint,
                    inspection.message,
                    self._now(),
                    task_id,
                ),
            )
            connection.commit()
        return BrowserTaskResult(
            application_id,
            task_id,
            state,
            inspection.message,
            inspection.url,
            inspection.fingerprint,
            inspection.filled_fields,
            inspection.skipped_fields,
        )

    def _fail_task(self, task_id: str, message: str) -> None:
        with self.applications.database.connect() as connection:
            connection.execute(
                "UPDATE browser_tasks SET state = 'failed', message = ?, updated_at = ? WHERE id = ?",
                (message, self._now(), task_id),
            )
            connection.commit()

    async def _close_page(self, application_id: str) -> None:
        page = self._pages.pop(application_id, None)
        if page is not None and not page.is_closed():
            await page.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
