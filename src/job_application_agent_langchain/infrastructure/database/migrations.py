"""Small, explicit SQLite migration runner.

Applied migrations are checksummed.  Editing an already-applied SQL file is a
hard error instead of an implicit production schema rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import sqlite3


class MigrationDriftError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str


class MigrationRunner:
    def discover(self) -> list[Migration]:
        directory = files(
            "job_application_agent_langchain.infrastructure.database.sql"
        )
        migrations: list[Migration] = []
        for resource in directory.iterdir():
            if not resource.name.endswith(".sql"):
                continue
            prefix, _, _ = resource.name.partition("_")
            if not prefix.isdigit():
                continue
            sql = resource.read_text(encoding="utf-8")
            migrations.append(
                Migration(
                    version=int(prefix),
                    name=resource.name,
                    sql=sql,
                    checksum=sha256(sql.encode("utf-8")).hexdigest(),
                )
            )
        return sorted(migrations, key=lambda migration: migration.version)

    def apply(self, connection: sqlite3.Connection) -> int:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()

        applied = {
            int(row["version"]): row
            for row in connection.execute(
                "SELECT version, name, checksum FROM schema_migrations"
            )
        }

        for migration in self.discover():
            prior = applied.get(migration.version)
            if prior is not None:
                if (
                    prior["name"] != migration.name
                    or prior["checksum"] != migration.checksum
                ):
                    raise MigrationDriftError(
                        f"migration {migration.version} no longer matches "
                        "the applied checksum"
                    )
                continue

            try:
                connection.executescript(migration.sql)
                connection.execute(
                    """
                    INSERT INTO schema_migrations(version, name, checksum)
                    VALUES (?, ?, ?)
                    """,
                    (migration.version, migration.name, migration.checksum),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        row = connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        return int(row["version"])
