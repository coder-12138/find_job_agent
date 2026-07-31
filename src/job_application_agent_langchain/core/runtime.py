"""Lifecycle for the rebuilt core."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from job_application_agent_langchain.core.config import CoreSettings
from job_application_agent_langchain.infrastructure.database import (
    Database,
    MigrationRunner,
)


@dataclass(frozen=True, slots=True)
class CoreRuntime:
    settings: CoreSettings
    database: Database
    schema_version: int


_runtime: CoreRuntime | None = None
_runtime_lock = Lock()


def initialize_core_runtime(settings: CoreSettings | None = None) -> CoreRuntime:
    """Create core directories and apply versioned database migrations once."""

    global _runtime
    with _runtime_lock:
        if _runtime is not None and settings is None:
            return _runtime

        resolved = settings or CoreSettings.from_env()
        resolved.ensure_directories()
        database = Database(resolved.database_path)
        with database.connect() as connection:
            schema_version = MigrationRunner().apply(connection)

        runtime = CoreRuntime(
            settings=resolved,
            database=database,
            schema_version=schema_version,
        )
        if settings is None:
            _runtime = runtime
        return runtime


def get_core_runtime() -> CoreRuntime:
    return _runtime or initialize_core_runtime()
