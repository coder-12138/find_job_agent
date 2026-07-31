"""Persistent job-application aggregate and explicit lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from job_application_agent_langchain.infrastructure.database import Database
from job_application_agent_langchain.infrastructure.security import SensitiveJsonCodec


class ApplicationNotFoundError(KeyError):
    pass


class ApplicationConflictError(RuntimeError):
    pass


class UnsupportedJobUrlError(ValueError):
    pass


TERMINAL_STATES = {"submitted", "outcome_unknown", "failed", "cancelled"}
TRANSITIONS = {
    "draft": {"ready_for_review", "cancelled"},
    "ready_for_review": {"awaiting_login", "draft", "cancelled"},
    "awaiting_login": {"awaiting_user_submit", "failed", "cancelled"},
    "awaiting_user_submit": {"submitted", "outcome_unknown", "failed", "cancelled"},
    "submitted": set(),
    "outcome_unknown": set(),
    "failed": set(),
    "cancelled": set(),
}


@dataclass(frozen=True, slots=True)
class ApplicationView:
    id: str
    platform: str
    job_snapshot_id: str
    profile_version_id: str
    state: str
    state_reason: str | None
    row_version: int
    source_url: str
    title: str | None
    company: str | None
    created_at: str
    updated_at: str
    submitted_at: str | None
    form_values: dict[str, Any] | None = None


class ApplicationService:
    def __init__(
        self,
        database: Database,
        codec: SensitiveJsonCodec,
        *,
        allowed_hosts: set[str] | None = None,
    ):
        self.database = database
        self.codec = codec
        self.allowed_hosts = allowed_hosts or {"jobs.feishu.cn"}

    def create_application(
        self,
        *,
        source_url: str,
        profile_version_id: str,
        title: str | None = None,
        company: str | None = None,
        description: str | None = None,
        idempotency_key: str | None = None,
    ) -> ApplicationView:
        host = (urlparse(source_url).hostname or "").lower()
        if host not in self.allowed_hosts:
            raise UnsupportedJobUrlError("首个正式版本只允许 jobs.feishu.cn 职位链接")
        application_id = uuid4().hex
        snapshot_id = uuid4().hex
        now = self._now()
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if idempotency_key:
                    existing = connection.execute(
                        "SELECT resource_id FROM idempotency_keys WHERE scope = 'application.create' AND idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing:
                        connection.commit()
                        return self._get_with_connection(connection, existing["resource_id"])
                profile = connection.execute(
                    "SELECT * FROM profile_versions WHERE id = ?", (profile_version_id,)
                ).fetchone()
                if profile is None:
                    raise ApplicationNotFoundError(profile_version_id)
                if profile["status"] == "archived":
                    raise ApplicationConflictError("归档档案版本不能创建新申请")
                snapshot = {
                    "source_url": source_url,
                    "title": title,
                    "company": company,
                    "description": description,
                }
                connection.execute(
                    """
                    INSERT INTO job_snapshots(
                        id, platform, source_url, title, company,
                        snapshot_ciphertext, created_at
                    ) VALUES (?, 'feishu_recruiting', ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        source_url,
                        title,
                        company,
                        self.codec.encode(snapshot, context=f"job-snapshot:{snapshot_id}"),
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO applications(
                        id, platform, job_snapshot_id, profile_version_id,
                        state, row_version, created_at, updated_at
                    ) VALUES (?, 'feishu_recruiting', ?, ?, 'draft', 1, ?, ?)
                    """,
                    (application_id, snapshot_id, profile_version_id, now, now),
                )
                if profile["source_file_resource_id"]:
                    connection.execute(
                        """
                        INSERT INTO application_materials(application_id, kind, file_resource_id, created_at)
                        VALUES (?, 'original_resume', ?, ?)
                        """,
                        (application_id, profile["source_file_resource_id"], now),
                    )
                if idempotency_key:
                    connection.execute(
                        "INSERT INTO idempotency_keys(scope, idempotency_key, resource_id, created_at) VALUES ('application.create', ?, ?, ?)",
                        (idempotency_key, application_id, now),
                    )
                self._audit(
                    connection,
                    application_id,
                    "application.created",
                    {"job_snapshot_id": snapshot_id, "profile_version_id": profile_version_id},
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_application(application_id)

    def list_applications(self) -> list[ApplicationView]:
        with self.database.connect() as connection:
            rows = connection.execute(self._select_sql() + " ORDER BY a.updated_at DESC").fetchall()
            return [self._view(connection, row) for row in rows]

    def get_application(self, application_id: str) -> ApplicationView:
        with self.database.connect() as connection:
            return self._get_with_connection(connection, application_id)

    def change_profile_version(
        self,
        application_id: str,
        *,
        profile_version_id: str,
        expected_version: int,
    ) -> ApplicationView:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = self._require_application(connection, application_id)
                self._require_expected_version(current, expected_version)
                if current["state"] not in {"draft", "ready_for_review"}:
                    raise ApplicationConflictError("浏览器流程开始后不能切换档案版本")
                profile = connection.execute(
                    "SELECT * FROM profile_versions WHERE id = ?", (profile_version_id,)
                ).fetchone()
                if profile is None or profile["status"] == "archived":
                    raise ApplicationNotFoundError(profile_version_id)
                now = self._now()
                connection.execute(
                    """
                    UPDATE applications
                    SET profile_version_id = ?, state = 'draft', state_reason = NULL,
                        row_version = row_version + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (profile_version_id, now, application_id),
                )
                connection.execute(
                    "DELETE FROM application_form_snapshots WHERE application_id = ?",
                    (application_id,),
                )
                connection.execute(
                    "DELETE FROM application_materials WHERE application_id = ? AND kind = 'original_resume'",
                    (application_id,),
                )
                if profile["source_file_resource_id"]:
                    connection.execute(
                        "INSERT INTO application_materials(application_id, kind, file_resource_id, created_at) VALUES (?, 'original_resume', ?, ?)",
                        (application_id, profile["source_file_resource_id"], now),
                    )
                self._audit(
                    connection,
                    application_id,
                    "application.profile_version_changed",
                    {"profile_version_id": profile_version_id},
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_application(application_id)

    def prepare_for_review(
        self,
        application_id: str,
        *,
        form_values: dict[str, Any],
        expected_version: int,
    ) -> ApplicationView:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = self._require_application(connection, application_id)
                self._require_expected_version(row, expected_version)
                if row["state"] not in {"draft", "ready_for_review"}:
                    raise ApplicationConflictError("当前状态不能重新生成待核对表单")
                now = self._now()
                ciphertext = self.codec.encode(
                    form_values, context=f"application-form:{application_id}"
                )
                connection.execute(
                    """
                    INSERT INTO application_form_snapshots(
                        application_id, values_ciphertext, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(application_id) DO UPDATE SET
                        values_ciphertext = excluded.values_ciphertext,
                        updated_at = excluded.updated_at
                    """,
                    (application_id, ciphertext, now, now),
                )
                self._transition_locked(
                    connection,
                    row,
                    "ready_for_review",
                    reason="请核对表单和原始简历后再打开受管浏览器",
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_application(application_id)

    def approve_review(
        self, application_id: str, *, expected_version: int
    ) -> ApplicationView:
        return self.transition(
            application_id,
            to_state="awaiting_login",
            reason="等待在受管浏览器中登录飞书招聘",
            expected_version=expected_version,
        )

    def transition(
        self,
        application_id: str,
        *,
        to_state: str,
        reason: str | None,
        expected_version: int,
        actor_type: str = "local_user",
    ) -> ApplicationView:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = self._require_application(connection, application_id)
                self._require_expected_version(row, expected_version)
                self._transition_locked(
                    connection, row, to_state, reason=reason, actor_type=actor_type
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_application(application_id)

    def record_submission_outcome(
        self,
        application_id: str,
        *,
        outcome: str,
        evidence: dict[str, Any],
        expected_version: int,
    ) -> ApplicationView:
        state = {
            "submitted": "submitted",
            "outcome_unknown": "outcome_unknown",
            "failed": "failed",
        }.get(outcome)
        if state is None:
            raise ValueError("unsupported submission outcome")
        receipt_id = uuid4().hex
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = self._require_application(connection, application_id)
                self._require_expected_version(row, expected_version)
                if row["state"] != "awaiting_user_submit":
                    raise ApplicationConflictError("只有等待用户最终提交时才能记录投递结果")
                observed_at = self._now()
                connection.execute(
                    """
                    INSERT INTO submission_receipts(
                        id, application_id, outcome, evidence_ciphertext, observed_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        application_id,
                        outcome,
                        self.codec.encode(
                            evidence, context=f"submission-receipt:{receipt_id}"
                        ),
                        observed_at,
                    ),
                )
                self._transition_locked(
                    connection,
                    row,
                    state,
                    reason=evidence.get("summary") or outcome,
                    actor_type="browser_observer",
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get_application(application_id)

    def list_audit_events(self, application_id: str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            self._require_application(connection, application_id)
            rows = connection.execute(
                """
                SELECT sequence, event_type, actor_type, payload_json, occurred_at
                FROM audit_events
                WHERE aggregate_type = 'application' AND aggregate_id = ?
                ORDER BY sequence
                """,
                (application_id,),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "event_type": row["event_type"],
                "actor_type": row["actor_type"],
                "payload": json.loads(row["payload_json"]),
                "occurred_at": row["occurred_at"],
            }
            for row in rows
        ]

    def _transition_locked(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        to_state: str,
        *,
        reason: str | None,
        actor_type: str = "local_user",
    ) -> None:
        old_state = row["state"]
        if to_state not in TRANSITIONS.get(old_state, set()):
            raise ApplicationConflictError(f"不允许从 {old_state} 转为 {to_state}")
        now = self._now()
        submitted_at = now if to_state == "submitted" else row["submitted_at"]
        connection.execute(
            """
            UPDATE applications
            SET state = ?, state_reason = ?, row_version = row_version + 1,
                updated_at = ?, submitted_at = ?
            WHERE id = ?
            """,
            (to_state, reason, now, submitted_at, row["id"]),
        )
        self._audit(
            connection,
            row["id"],
            "application.state_changed",
            {"from": old_state, "to": to_state, "reason": reason},
            actor_type=actor_type,
        )

    def _get_with_connection(
        self, connection: sqlite3.Connection, application_id: str
    ) -> ApplicationView:
        row = connection.execute(
            self._select_sql() + " WHERE a.id = ?", (application_id,)
        ).fetchone()
        if row is None:
            raise ApplicationNotFoundError(application_id)
        return self._view(connection, row)

    def _view(self, connection: sqlite3.Connection, row: sqlite3.Row) -> ApplicationView:
        form = connection.execute(
            "SELECT values_ciphertext FROM application_form_snapshots WHERE application_id = ?",
            (row["id"],),
        ).fetchone()
        values = (
            self.codec.decode(
                form["values_ciphertext"], context=f"application-form:{row['id']}"
            )
            if form
            else None
        )
        return ApplicationView(
            id=row["id"],
            platform=row["platform"],
            job_snapshot_id=row["job_snapshot_id"],
            profile_version_id=row["profile_version_id"],
            state=row["state"],
            state_reason=row["state_reason"],
            row_version=int(row["row_version"]),
            source_url=row["source_url"],
            title=row["title"],
            company=row["company"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            submitted_at=row["submitted_at"],
            form_values=values,
        )

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT a.*, j.source_url, j.title, j.company
            FROM applications a
            JOIN job_snapshots j ON j.id = a.job_snapshot_id
        """

    @staticmethod
    def _require_application(
        connection: sqlite3.Connection, application_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if row is None:
            raise ApplicationNotFoundError(application_id)
        return row

    @staticmethod
    def _require_expected_version(row: sqlite3.Row, expected_version: int) -> None:
        if int(row["row_version"]) != expected_version:
            raise ApplicationConflictError("申请已被其他操作修改，请刷新后重试")

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        application_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor_type: str = "local_user",
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(
                event_id, aggregate_type, aggregate_id, event_type,
                actor_type, payload_json, occurred_at
            ) VALUES (?, 'application', ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                application_id,
                event_type,
                actor_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ApplicationService._now(),
            ),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
