"""Encrypted, reusable extraction records for immutable resume resources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from job_application_agent_langchain.infrastructure.database import Database
from job_application_agent_langchain.infrastructure.security import SensitiveJsonCodec
from job_application_agent_langchain.resume_ingestion import ResumeExtractor


EXTRACTOR_VERSION = "local-pdf-v1"


class ResumeExtractionService:
    def __init__(self, database: Database, codec: SensitiveJsonCodec):
        self.database = database
        self.codec = codec

    def get(self, file_resource_id: str) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM resume_extractions WHERE file_resource_id = ?",
                (file_resource_id,),
            ).fetchone()
        if row is None:
            return None
        return self.codec.decode(
            row["extraction_ciphertext"],
            context=self._context(file_resource_id, row["extractor_version"]),
        )

    def save(
        self,
        file_resource_id: str,
        extraction: dict[str, Any],
        *,
        extractor_version: str = EXTRACTOR_VERSION,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        ciphertext = self.codec.encode(
            extraction,
            context=self._context(file_resource_id, extractor_version),
        )
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM file_resources WHERE id = ?", (file_resource_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(file_resource_id)
            connection.execute(
                """
                INSERT INTO resume_extractions(
                    file_resource_id, extractor_version,
                    extraction_ciphertext, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_resource_id) DO UPDATE SET
                    extractor_version = excluded.extractor_version,
                    extraction_ciphertext = excluded.extraction_ciphertext,
                    updated_at = excluded.updated_at
                """,
                (file_resource_id, extractor_version, ciphertext, now, now),
            )
            connection.commit()

    def get_or_extract(
        self, file_resource_id: str, pdf_bytes: bytes
    ) -> tuple[dict[str, Any], bool]:
        saved = self.get(file_resource_id)
        if saved is not None:
            return saved, False
        extraction = ResumeExtractor().extract(pdf_bytes).to_dict()
        self.save(file_resource_id, extraction)
        return extraction, True

    @staticmethod
    def plain_text(extraction: dict[str, Any]) -> str:
        return "\n\n".join(
            str(page.get("text") or "").strip()
            for page in extraction.get("pages", [])
            if str(page.get("text") or "").strip()
        ).strip()

    @staticmethod
    def _context(file_resource_id: str, extractor_version: str) -> str:
        return f"resume-extraction:{file_resource_id}:{extractor_version}"
