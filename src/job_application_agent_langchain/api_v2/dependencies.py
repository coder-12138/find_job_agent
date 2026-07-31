"""FastAPI dependencies for infrastructure-backed v2 services."""

from pathlib import Path

from job_application_agent_langchain.application.file_resources import (
    FileResourceService,
)
from job_application_agent_langchain.application.applications import ApplicationService
from job_application_agent_langchain.application.profiles import ProfileService
from job_application_agent_langchain.application.resume_extractions import (
    ResumeExtractionService,
)
from job_application_agent_langchain.core import get_core_runtime
from job_application_agent_langchain.browser_runtime import BrowserCoordinator
from job_application_agent_langchain.infrastructure.file_store import (
    EncryptedContentStore,
)
from job_application_agent_langchain.infrastructure.security import (
    SensitiveJsonCodec,
    WindowsDpapiKeyProvider,
)


def get_file_resource_service() -> FileResourceService:
    runtime = get_core_runtime()
    key_provider = WindowsDpapiKeyProvider(
        runtime.settings.data_dir / "master-key.dpapi"
    )
    store = EncryptedContentStore(runtime.settings.file_store_dir, key_provider)
    return FileResourceService(runtime.database, store)


def get_profile_service() -> ProfileService:
    runtime = get_core_runtime()
    key_provider = WindowsDpapiKeyProvider(
        runtime.settings.data_dir / "master-key.dpapi"
    )
    return ProfileService(runtime.database, SensitiveJsonCodec(key_provider))


def get_resume_extraction_service() -> ResumeExtractionService:
    runtime = get_core_runtime()
    key_provider = WindowsDpapiKeyProvider(
        runtime.settings.data_dir / "master-key.dpapi"
    )
    return ResumeExtractionService(runtime.database, SensitiveJsonCodec(key_provider))


def get_application_service() -> ApplicationService:
    runtime = get_core_runtime()
    key_provider = WindowsDpapiKeyProvider(
        runtime.settings.data_dir / "master-key.dpapi"
    )
    return ApplicationService(runtime.database, SensitiveJsonCodec(key_provider))


_browser_coordinators: dict[str, BrowserCoordinator] = {}


def get_browser_coordinator() -> BrowserCoordinator:
    runtime = get_core_runtime()
    key = str(Path(runtime.settings.database_path).resolve())
    existing = _browser_coordinators.get(key)
    if existing is not None:
        return existing
    coordinator = BrowserCoordinator(
        get_application_service(),
        get_file_resource_service(),
        runtime.settings.managed_browser_dir,
    )
    _browser_coordinators[key] = coordinator
    return coordinator


async def shutdown_browser_coordinators() -> None:
    coordinators = list(_browser_coordinators.values())
    _browser_coordinators.clear()
    for coordinator in coordinators:
        await coordinator.close()
