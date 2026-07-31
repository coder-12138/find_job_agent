"""Application service for immutable encrypted file resources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from job_application_agent_langchain.infrastructure.database import Database
from job_application_agent_langchain.infrastructure.file_store import (
    EncryptedContentStore,
)


@dataclass(frozen=True, slots=True)
class FileResourceResult:
    resource_id: str
    content_sha256: str
    byte_size: int
    media_type: str
    original_name: str
    storage_key: str
    created: bool


class FileResourceService:
    def __init__(self, database: Database, store: EncryptedContentStore):
        self.database = database
        self.store = store

    def save(
        self,
        content: bytes,
        *,
        original_name: str,
        media_type: str,
    ) -> FileResourceResult:
        stored = self.store.put(content)
        created_at = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO file_resources(
                    id,
                    content_sha256,
                    media_type,
                    byte_size,
                    original_name,
                    storage_key,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.content_sha256,
                    stored.content_sha256,
                    media_type,
                    stored.byte_size,
                    original_name,
                    stored.storage_key,
                    created_at,
                ),
            )
            connection.commit()
            metadata_created = cursor.rowcount == 1
            row = connection.execute(
                """
                SELECT id, content_sha256, media_type, byte_size,
                       original_name, storage_key
                FROM file_resources
                WHERE content_sha256 = ?
                """,
                (stored.content_sha256,),
            ).fetchone()

        return FileResourceResult(
            resource_id=row["id"],
            content_sha256=row["content_sha256"],
            byte_size=int(row["byte_size"]),
            media_type=row["media_type"],
            original_name=row["original_name"],
            storage_key=row["storage_key"],
            created=stored.created and metadata_created,
        )

    def read(self, resource_id: str) -> bytes:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT content_sha256 FROM file_resources WHERE id = ?",
                (resource_id,),
            ).fetchone()
        if row is None:
            raise KeyError(resource_id)
        return self.store.get(row["content_sha256"])

    def get_metadata(self, resource_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, content_sha256, media_type, byte_size,
                       original_name, created_at
                FROM file_resources
                WHERE id = ?
                """,
                (resource_id,),
            ).fetchone()
        if row is None:
            raise KeyError(resource_id)
        return dict(row)

    def list_resources(self, *, media_type: str | None = None) -> list[dict[str, object]]:
        query = (
            "SELECT id, content_sha256, media_type, byte_size, "
            "original_name, created_at FROM file_resources"
        )
        params: tuple[object, ...] = ()
        if media_type:
            query += " WHERE media_type = ?"
            params = (media_type,)
        query += " ORDER BY created_at DESC"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]
