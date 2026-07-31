"""Bridge confirmed profile versions into the original agent runtime.

The profile/database remains authoritative.  A plaintext PDF exists only as a
session-scoped upload file because browser file inputs require a filesystem
path; SessionManager removes it when the run ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any

from job_application_agent_langchain.api_v2.dependencies import (
    get_file_resource_service,
    get_profile_service,
    get_resume_extraction_service,
)
from job_application_agent_langchain.application.profiles import ProfileNotFoundError
from job_application_agent_langchain.application.resume_extractions import (
    ResumeExtractionService,
)
from job_application_agent_langchain.user_info.parser import UserInfo


@dataclass(frozen=True, slots=True)
class LegacyProfileSession:
    user_info: UserInfo
    profile_id: str
    profile_version_id: str
    temporary_files: tuple[str, ...]


def load_profile_for_legacy_session(
    profile_version_id: str | None = None,
) -> LegacyProfileSession:
    profiles = get_profile_service()
    version = (
        profiles.get_version(profile_version_id)
        if profile_version_id
        else profiles.get_active_version()
    )
    if version.status == "archived":
        raise ProfileNotFoundError("归档版本不能用于新投递")
    if not version.source_file_resource_id:
        raise ProfileNotFoundError("该档案版本没有来源 PDF")

    files = get_file_resource_service()
    metadata = files.get_metadata(version.source_file_resource_id)
    suffix = Path(str(metadata.get("original_name") or "resume.pdf")).suffix or ".pdf"
    source_pdf = files.read(version.source_file_resource_id)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix="findjob-resume-", suffix=suffix, delete=False
    )
    try:
        handle.write(source_pdf)
        materialized_path = handle.name
    finally:
        handle.close()

    user_info = _to_user_info(version.fields)
    try:
        extraction, extracted_now = get_resume_extraction_service().get_or_extract(
            version.source_file_resource_id, source_pdf
        )
    except Exception:
        Path(materialized_path).unlink(missing_ok=True)
        raise
    source_resume_text = ResumeExtractionService.plain_text(extraction)
    if not source_resume_text:
        Path(materialized_path).unlink(missing_ok=True)
        raise ValueError("档案版本的来源 PDF 未能提取出可用于润色的正文")
    user_info.resume_file_path = materialized_path
    user_info.extra_fields["resume_text"] = source_resume_text
    user_info.extra_fields["resume_extraction_reused"] = not extracted_now
    quality = extraction.get("quality") or {}
    user_info.extra_fields["resume_extraction_quality"] = {
        "page_count": quality.get("page_count", 0),
        "character_count": quality.get("character_count", len(source_resume_text)),
        "ocr_pages": list(quality.get("ocr_pages") or []),
        "needs_review": bool(quality.get("needs_review", False)),
    }
    user_info.extra_fields.setdefault("profile_id", version.profile_id)
    user_info.extra_fields.setdefault("profile_version_id", version.id)
    return LegacyProfileSession(
        user_info=user_info,
        profile_id=version.profile_id,
        profile_version_id=version.id,
        temporary_files=(materialized_path,),
    )


def _to_user_info(fields: dict[str, Any]) -> UserInfo:
    """Accept both the full UserInfo shape and extractor-friendly flat fields."""

    if isinstance(fields.get("personal_info"), dict):
        payload = {
            key: value
            for key, value in fields.items()
            if key in UserInfo.model_fields
        }
        info = UserInfo.model_validate(payload)
    else:
        info = UserInfo()
        personal_aliases = {
            "full_name": "name",
            "name": "name",
            "email": "email",
            "phone": "phone",
            "gender": "gender",
            "address": "address",
            "city": "city",
            "current_city": "current_city",
            "wechat": "wechat",
        }
        for source, target in personal_aliases.items():
            value = fields.get(source)
            if value not in (None, ""):
                setattr(info.personal_info, target, str(value))

        for key in (
            "job_intentions",
            "education",
            "work_experience",
            "project_experience",
            "awards",
            "publications",
            "skills",
            "self_introduction",
        ):
            value = fields.get(key)
            if isinstance(value, list) or (key == "self_introduction" and isinstance(value, str)):
                try:
                    validated = UserInfo.model_validate({key: value})
                    setattr(info, key, getattr(validated, key))
                except Exception:
                    info.extra_fields[key] = value
            elif value not in (None, ""):
                info.extra_fields[key] = value

    resume_text = str(
        fields.get("resume_text")
        or fields.get("raw_resume_text")
        or info.extra_fields.get("resume_text")
        or ""
    ).strip()
    if resume_text:
        info.extra_fields["resume_text"] = resume_text
    for key, value in fields.items():
        if key not in UserInfo.model_fields and key not in {"full_name", "name"}:
            info.extra_fields.setdefault(key, value)
    return info
