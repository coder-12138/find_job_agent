"""Candidate profile versions and reviewed resume-change proposals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any
from uuid import uuid4

from job_application_agent_langchain.infrastructure.database import Database
from job_application_agent_langchain.infrastructure.security import SensitiveJsonCodec


class ProfileNotFoundError(KeyError):
    """Requested profile, version, proposal, or source file does not exist."""


class ProfileConflictError(RuntimeError):
    """Optimistic-concurrency or lifecycle rule was violated."""


@dataclass(frozen=True, slots=True)
class ProfileVersionView:
    id: str
    profile_id: str
    version_number: int
    status: str
    source_file_resource_id: str | None
    fields: dict[str, Any]
    created_at: str


class ProfileService:
    def __init__(self, database: Database, codec: SensitiveJsonCodec):
        self.database = database
        self.codec = codec

    def create_profile(
        self,
        fields: dict[str, Any],
        *,
        source_file_resource_id: str,
    ) -> ProfileVersionView:
        profile_id = uuid4().hex
        version_id = uuid4().hex
        created_at = self._now()
        ciphertext = self.codec.encode(fields, context=f"profile-version:{version_id}")
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._require_file(connection, source_file_resource_id)
                connection.execute(
                    "INSERT INTO candidate_profiles(id, created_at, row_version) VALUES (?, ?, 1)",
                    (profile_id, created_at),
                )
                self._insert_version(
                    connection,
                    version_id=version_id,
                    profile_id=profile_id,
                    version_number=1,
                    source_file_resource_id=source_file_resource_id,
                    ciphertext=ciphertext,
                    created_at=created_at,
                )
                connection.execute(
                    "UPDATE candidate_profiles SET active_version_id = ? WHERE id = ?",
                    (version_id, profile_id),
                )
                self._audit(
                    connection,
                    profile_id,
                    "profile.created",
                    {"profile_version_id": version_id, "version_number": 1},
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return ProfileVersionView(
            version_id, profile_id, 1, "confirmed", source_file_resource_id, fields, created_at
        )

    def list_profiles(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT p.id AS profile_id, p.row_version, p.created_at, p.archived_at,
                       p.active_version_id, v.id AS version_id, v.version_number,
                       v.status, v.source_file_resource_id, v.profile_ciphertext,
                       v.created_at AS version_created_at
                FROM candidate_profiles p
                JOIN profile_versions v
                  ON v.id = COALESCE(
                      p.active_version_id,
                      (SELECT v2.id FROM profile_versions v2
                       WHERE v2.profile_id = p.id
                       ORDER BY v2.version_number DESC LIMIT 1)
                  )
                ORDER BY p.created_at DESC
                """
            ).fetchall()
        return [
            {
                "id": row["profile_id"],
                "row_version": int(row["row_version"]),
                "created_at": row["created_at"],
                "archived_at": row["archived_at"],
                "active_version_id": row["active_version_id"],
                "active_version": self._view(row),
            }
            for row in rows
        ]

    def list_versions(self, profile_id: str) -> list[ProfileVersionView]:
        with self.database.connect() as connection:
            self._require_profile(connection, profile_id)
            rows = connection.execute(
                "SELECT * FROM profile_versions WHERE profile_id = ? ORDER BY version_number DESC",
                (profile_id,),
            ).fetchall()
        return [self._view(row) for row in rows]

    def get_version(self, version_id: str) -> ProfileVersionView:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profile_versions WHERE id = ?", (version_id,)
            ).fetchone()
        if row is None:
            raise ProfileNotFoundError(version_id)
        return self._view(row)

    def get_active_version(self, profile_id: str | None = None) -> ProfileVersionView:
        with self.database.connect() as connection:
            if profile_id:
                profile = self._require_profile(connection, profile_id)
            else:
                profile = connection.execute(
                    """
                    SELECT * FROM candidate_profiles
                    WHERE archived_at IS NULL AND active_version_id IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                    """
                ).fetchone()
                if profile is None:
                    raise ProfileNotFoundError("active-profile")
            version_id = profile["active_version_id"]
            if not version_id:
                raise ProfileNotFoundError("active-version")
            row = self._require_version(connection, profile["id"], version_id)
        return self._view(row)

    def create_version(
        self,
        profile_id: str,
        fields: dict[str, Any],
        *,
        source_file_resource_id: str,
        expected_version: int,
    ) -> ProfileVersionView:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                created = self._create_version_locked(
                    connection,
                    profile_id=profile_id,
                    fields=fields,
                    source_file_resource_id=source_file_resource_id,
                    expected_version=expected_version,
                    audit_type="profile.version_created",
                )
                connection.commit()
                return created
            except Exception:
                connection.rollback()
                raise

    def set_active_version(
        self,
        profile_id: str,
        version_id: str,
        *,
        expected_version: int,
    ) -> ProfileVersionView:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                profile = self._require_profile(connection, profile_id)
                self._require_expected_version(profile, expected_version)
                row = self._require_version(connection, profile_id, version_id)
                if row["status"] == "archived":
                    raise ProfileConflictError("归档版本不能设为当前版本，请先保留它仅作历史查看")
                connection.execute(
                    "UPDATE candidate_profiles SET active_version_id = ?, row_version = row_version + 1 WHERE id = ?",
                    (version_id, profile_id),
                )
                self._audit(
                    connection,
                    profile_id,
                    "profile.active_version_changed",
                    {"profile_version_id": version_id},
                )
                connection.commit()
                return self._view(row)
            except Exception:
                connection.rollback()
                raise

    def archive_version(
        self,
        profile_id: str,
        version_id: str,
        *,
        expected_version: int,
    ) -> ProfileVersionView:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                profile = self._require_profile(connection, profile_id)
                self._require_expected_version(profile, expected_version)
                row = self._require_version(connection, profile_id, version_id)
                if profile["active_version_id"] == version_id:
                    raise ProfileConflictError("当前使用中的版本不能归档，请先切换到其他版本")
                connection.execute(
                    "UPDATE profile_versions SET status = 'archived' WHERE id = ?",
                    (version_id,),
                )
                connection.execute(
                    "UPDATE candidate_profiles SET row_version = row_version + 1 WHERE id = ?",
                    (profile_id,),
                )
                self._audit(
                    connection,
                    profile_id,
                    "profile.version_archived",
                    {"profile_version_id": version_id},
                )
                connection.commit()
                updated = dict(row)
                updated["status"] = "archived"
                return self._view(updated)
            except Exception:
                connection.rollback()
                raise

    def delete_version(
        self,
        profile_id: str,
        version_id: str,
        *,
        expected_version: int,
    ) -> None:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                profile = self._require_profile(connection, profile_id)
                self._require_expected_version(profile, expected_version)
                self._require_version(connection, profile_id, version_id)
                if profile["active_version_id"] == version_id:
                    raise ProfileConflictError("当前使用中的版本不能删除，请先切换到其他版本")
                count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS count FROM profile_versions WHERE profile_id = ?",
                        (profile_id,),
                    ).fetchone()["count"]
                )
                if count <= 1:
                    raise ProfileConflictError("不能删除候选人档案的唯一版本")
                if self._version_has_application_reference(connection, version_id):
                    raise ProfileConflictError("该版本已被职位申请引用，只能保留或归档")
                connection.execute(
                    "DELETE FROM profile_version_sources WHERE profile_version_id = ?",
                    (version_id,),
                )
                connection.execute("DELETE FROM profile_versions WHERE id = ?", (version_id,))
                connection.execute(
                    "UPDATE candidate_profiles SET row_version = row_version + 1 WHERE id = ?",
                    (profile_id,),
                )
                self._audit(
                    connection,
                    profile_id,
                    "profile.version_deleted",
                    {"profile_version_id": version_id},
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def create_change_proposal(
        self,
        profile_id: str,
        *,
        base_version_id: str,
        source_file_resource_id: str,
        proposed_fields: dict[str, Any],
    ) -> dict[str, Any]:
        proposal_id = uuid4().hex
        created_at = self._now()
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._require_profile(connection, profile_id)
                base = self._require_version(connection, profile_id, base_version_id)
                self._require_file(connection, source_file_resource_id)
                current = self._decode_version(base)
                changes = {
                    key: {"old": current.get(key), "new": value}
                    for key, value in proposed_fields.items()
                    if current.get(key) != value
                }
                payload = self.codec.encode(changes, context=f"profile-proposal:{proposal_id}")
                connection.execute(
                    """
                    INSERT INTO profile_change_proposals(
                        id, profile_id, base_version_id, source_file_resource_id,
                        status, proposed_fields_ciphertext, created_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        proposal_id,
                        profile_id,
                        base_version_id,
                        source_file_resource_id,
                        payload,
                        created_at,
                    ),
                )
                self._audit(
                    connection,
                    profile_id,
                    "profile.change_proposed",
                    {"proposal_id": proposal_id, "changed_fields": sorted(changes)},
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {
            "id": proposal_id,
            "profile_id": profile_id,
            "base_version_id": base_version_id,
            "source_file_resource_id": source_file_resource_id,
            "status": "pending",
            "changes": changes,
            "created_at": created_at,
            "resolved_at": None,
        }

    def get_change_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM profile_change_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise ProfileNotFoundError(proposal_id)
        return self._proposal_view(row)

    def accept_change_proposal(
        self,
        proposal_id: str,
        *,
        selected_fields: list[str],
        expected_version: int,
    ) -> ProfileVersionView:
        """Atomically accept selected fields and create an independent version."""

        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                proposal = connection.execute(
                    "SELECT * FROM profile_change_proposals WHERE id = ?",
                    (proposal_id,),
                ).fetchone()
                if proposal is None:
                    raise ProfileNotFoundError(proposal_id)
                if proposal["status"] != "pending":
                    raise ProfileConflictError("变更提案已经处理")
                base = self._require_version(
                    connection, proposal["profile_id"], proposal["base_version_id"]
                )
                changes = self.codec.decode(
                    proposal["proposed_fields_ciphertext"],
                    context=f"profile-proposal:{proposal_id}",
                )
                unknown = sorted(set(selected_fields) - set(changes))
                if unknown:
                    raise ProfileConflictError(f"提案中不存在这些字段：{', '.join(unknown)}")
                fields = self._decode_version(base)
                for key in selected_fields:
                    fields[key] = changes[key]["new"]
                created = self._create_version_locked(
                    connection,
                    profile_id=proposal["profile_id"],
                    fields=fields,
                    source_file_resource_id=proposal["source_file_resource_id"],
                    expected_version=expected_version,
                    audit_type="profile.proposal_accepted_as_version",
                )
                resolved_at = self._now()
                cursor = connection.execute(
                    """
                    UPDATE profile_change_proposals
                    SET status = 'accepted', resolved_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (resolved_at, proposal_id),
                )
                if cursor.rowcount != 1:
                    raise ProfileConflictError("变更提案已被并发处理")
                self._audit(
                    connection,
                    proposal["profile_id"],
                    "profile.change_accepted",
                    {
                        "proposal_id": proposal_id,
                        "profile_version_id": created.id,
                        "selected_fields": sorted(selected_fields),
                    },
                )
                connection.commit()
                return created
            except Exception:
                connection.rollback()
                raise

    def discard_change_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM profile_change_proposals WHERE id = ?", (proposal_id,)
                ).fetchone()
                if row is None:
                    raise ProfileNotFoundError(proposal_id)
                if row["status"] != "pending":
                    raise ProfileConflictError("变更提案已经处理")
                resolved_at = self._now()
                connection.execute(
                    "UPDATE profile_change_proposals SET status = 'discarded', resolved_at = ? WHERE id = ?",
                    (resolved_at, proposal_id),
                )
                self._audit(
                    connection,
                    row["profile_id"],
                    "profile.change_discarded",
                    {"proposal_id": proposal_id},
                )
                connection.commit()
                result = self._proposal_view(row)
                result["status"] = "discarded"
                result["resolved_at"] = resolved_at
                return result
            except Exception:
                connection.rollback()
                raise

    def _create_version_locked(
        self,
        connection: sqlite3.Connection,
        *,
        profile_id: str,
        fields: dict[str, Any],
        source_file_resource_id: str,
        expected_version: int,
        audit_type: str,
    ) -> ProfileVersionView:
        profile = self._require_profile(connection, profile_id)
        self._require_expected_version(profile, expected_version)
        self._require_file(connection, source_file_resource_id)
        version_id = uuid4().hex
        created_at = self._now()
        number = int(
            connection.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 AS number FROM profile_versions WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()["number"]
        )
        ciphertext = self.codec.encode(fields, context=f"profile-version:{version_id}")
        self._insert_version(
            connection,
            version_id=version_id,
            profile_id=profile_id,
            version_number=number,
            source_file_resource_id=source_file_resource_id,
            ciphertext=ciphertext,
            created_at=created_at,
        )
        connection.execute(
            """
            UPDATE candidate_profiles
            SET active_version_id = ?, row_version = row_version + 1
            WHERE id = ?
            """,
            (version_id, profile_id),
        )
        self._audit(
            connection,
            profile_id,
            audit_type,
            {"profile_version_id": version_id, "version_number": number},
        )
        return ProfileVersionView(
            version_id,
            profile_id,
            number,
            "confirmed",
            source_file_resource_id,
            fields,
            created_at,
        )

    @staticmethod
    def _insert_version(
        connection: sqlite3.Connection,
        *,
        version_id: str,
        profile_id: str,
        version_number: int,
        source_file_resource_id: str,
        ciphertext: bytes,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO profile_versions(
                id, profile_id, version_number, status, profile_json,
                source_file_resource_id, profile_ciphertext, created_at
            ) VALUES (?, ?, ?, 'confirmed', 'encrypted:v1', ?, ?, ?)
            """,
            (
                version_id,
                profile_id,
                version_number,
                source_file_resource_id,
                ciphertext,
                created_at,
            ),
        )
        connection.execute(
            "INSERT INTO profile_version_sources(profile_version_id, file_resource_id) VALUES (?, ?)",
            (version_id, source_file_resource_id),
        )

    def _view(self, row: sqlite3.Row | dict[str, Any]) -> ProfileVersionView:
        keys = set(row.keys())
        joined = "version_id" in keys
        version_id = row["version_id"] if joined else row["id"]
        profile_id = row["profile_id"]
        created_at = row["version_created_at"] if joined else row["created_at"]
        return ProfileVersionView(
            id=version_id,
            profile_id=profile_id,
            version_number=int(row["version_number"]),
            status=row["status"],
            source_file_resource_id=row["source_file_resource_id"],
            fields=self.codec.decode(
                row["profile_ciphertext"], context=f"profile-version:{version_id}"
            ),
            created_at=created_at,
        )

    def _proposal_view(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "profile_id": row["profile_id"],
            "base_version_id": row["base_version_id"],
            "source_file_resource_id": row["source_file_resource_id"],
            "status": row["status"],
            "changes": self.codec.decode(
                row["proposed_fields_ciphertext"],
                context=f"profile-proposal:{row['id']}",
            ),
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }

    def _decode_version(self, row: sqlite3.Row) -> dict[str, Any]:
        return self.codec.decode(
            row["profile_ciphertext"], context=f"profile-version:{row['id']}"
        )

    @staticmethod
    def _require_profile(connection: sqlite3.Connection, profile_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM candidate_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise ProfileNotFoundError(profile_id)
        return row

    @staticmethod
    def _require_version(
        connection: sqlite3.Connection, profile_id: str, version_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM profile_versions WHERE id = ? AND profile_id = ?",
            (version_id, profile_id),
        ).fetchone()
        if row is None:
            raise ProfileNotFoundError(version_id)
        return row

    @staticmethod
    def _require_file(connection: sqlite3.Connection, resource_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM file_resources WHERE id = ?", (resource_id,)
        ).fetchone() is None:
            raise ProfileNotFoundError(resource_id)

    @staticmethod
    def _require_expected_version(profile: sqlite3.Row, expected_version: int) -> None:
        if int(profile["row_version"]) != expected_version:
            raise ProfileConflictError("候选人档案已被其他操作修改，请刷新后重试")

    @staticmethod
    def _version_has_application_reference(
        connection: sqlite3.Connection, version_id: str
    ) -> bool:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'applications'"
        ).fetchone()
        if table is None:
            return False
        return connection.execute(
            "SELECT 1 FROM applications WHERE profile_version_id = ? LIMIT 1",
            (version_id,),
        ).fetchone() is not None

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        profile_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(
                event_id, aggregate_type, aggregate_id, event_type,
                actor_type, payload_json, occurred_at
            ) VALUES (?, 'candidate_profile', ?, ?, 'local_user', ?, ?)
            """,
            (
                uuid4().hex,
                profile_id,
                event_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ProfileService._now(),
            ),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
