"""Configuration boundary for the rebuilt core.

The legacy ``Settings`` singleton mixes model, browser, file and workflow
configuration.  The new core starts with filesystem-only configuration and has
no dependency on model credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class CoreSettings:
    """Paths owned by the rebuilt core.

    Directory creation is explicit through :meth:`ensure_directories`, so
    importing domain modules never mutates the filesystem.
    """

    data_dir: Path
    database_path: Path
    file_store_dir: Path
    managed_browser_dir: Path

    @classmethod
    def from_env(cls) -> "CoreSettings":
        configured = os.getenv("JOB_AGENT_CORE_DATA_DIR", "").strip()
        data_dir = (
            Path(configured).expanduser()
            if configured
            else PROJECT_ROOT / "data" / "core"
        ).resolve()
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "job-assistant.sqlite3",
            file_store_dir=data_dir / "files",
            managed_browser_dir=data_dir / "browser-profile",
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_store_dir.mkdir(parents=True, exist_ok=True)
        self.managed_browser_dir.mkdir(parents=True, exist_ok=True)
