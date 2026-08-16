"""Explicit command/query API for the reliability-first application core."""

from pathlib import Path
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel

from job_application_agent_langchain.api_v2.dependencies import (
    get_application_service,
    get_browser_coordinator,
    get_file_resource_service,
    get_profile_service,
    get_resume_extraction_service,
)
from job_application_agent_langchain.application.applications import (
    ApplicationConflictError,
    ApplicationNotFoundError,
    ApplicationService,
    ApplicationView,
    UnsupportedJobUrlError,
)
from job_application_agent_langchain.application.file_resources import FileResourceService
from job_application_agent_langchain.application.profiles import (
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileService,
    ProfileVersionView,
)
from job_application_agent_langchain.application.resume_extractions import (
    ResumeExtractionService,
)
from job_application_agent_langchain.core import get_core_runtime
from job_application_agent_langchain.browser_runtime import BrowserCoordinator
from job_application_agent_langchain.resume_ingestion import ResumeExtractor


router = APIRouter(prefix="/api/v2", tags=["core-v2"])
MAX_RESUME_BYTES = 20 * 1024 * 1024


class ResumeResourceResponse(BaseModel):
    resource_id: str
    content_sha256: str
    byte_size: int
    media_type: str
    original_name: str
    duplicate: bool


class ResumeExtractionResponse(BaseModel):
    resource_id: str
    extraction: dict[str, object]


class CreateProfileRequest(BaseModel):
    fields: dict[str, Any]
    source_file_resource_id: str


class CreateProfileVersionRequest(CreateProfileRequest):
    expected_version: int


class VersionMutationRequest(BaseModel):
    expected_version: int


class CreateChangeProposalRequest(BaseModel):
    base_version_id: str
    source_file_resource_id: str
    proposed_fields: dict[str, Any]


class AcceptChangeProposalRequest(BaseModel):
    selected_fields: list[str]
    expected_version: int


class CreateApplicationRequest(BaseModel):
    source_url: str
    profile_version_id: str
    title: str | None = None
    company: str | None = None
    description: str | None = None
    idempotency_key: str | None = None


class ChangeApplicationProfileRequest(BaseModel):
    profile_version_id: str
    expected_version: int


class PrepareApplicationRequest(BaseModel):
    form_values: dict[str, Any]
    expected_version: int


class ApplicationMutationRequest(BaseModel):
    expected_version: int


class SubmissionOutcomeRequest(BaseModel):
    outcome: str
    evidence: dict[str, Any]
    expected_version: int


class ReviewHintRequest(BaseModel):
    status: str


def _version_response(view: ProfileVersionView) -> dict[str, Any]:
    return {
        "id": view.id,
        "profile_id": view.profile_id,
        "version_number": view.version_number,
        "status": view.status,
        "source_file_resource_id": view.source_file_resource_id,
        "fields": view.fields,
        "created_at": view.created_at,
    }


def _profile_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProfileNotFoundError):
        return HTTPException(status_code=404, detail="候选人档案资源不存在")
    if isinstance(exc, ProfileConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


def _application_response(view: ApplicationView) -> dict[str, Any]:
    return {
        "id": view.id,
        "platform": view.platform,
        "job_snapshot_id": view.job_snapshot_id,
        "profile_version_id": view.profile_version_id,
        "state": view.state,
        "state_reason": view.state_reason,
        "row_version": view.row_version,
        "source_url": view.source_url,
        "title": view.title,
        "company": view.company,
        "created_at": view.created_at,
        "updated_at": view.updated_at,
        "submitted_at": view.submitted_at,
        "form_values": view.form_values,
    }


def _application_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ApplicationNotFoundError):
        return HTTPException(status_code=404, detail="职位申请资源不存在")
    if isinstance(exc, ApplicationConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UnsupportedJobUrlError):
        return HTTPException(status_code=400, detail=str(exc))
    raise exc


@router.get("/health")
async def core_health() -> dict[str, object]:
    runtime = get_core_runtime()
    return {"status": "ok", "core": "ready", "schema_version": runtime.schema_version}


@router.get("/system/capabilities")
async def core_capabilities() -> dict[str, object]:
    return {
        "formal_platforms": ["feishu_recruiting"],
        "workflow_controller": "task_ui",
        "external_model_required": False,
        "final_submission_actor": "user",
        "stage": 5,
    }


@router.post("/resumes", response_model=ResumeResourceResponse, status_code=201)
async def upload_resume(
    response: Response,
    file: UploadFile,
    service: FileResourceService = Depends(get_file_resource_service),
    extractions: ResumeExtractionService = Depends(get_resume_extraction_service),
) -> ResumeResourceResponse:
    """Store an immutable PDF directly into the encrypted content store."""

    original_name = Path(file.filename or "resume.pdf").name
    if Path(original_name).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="只接受 PDF 简历")

    content = bytearray()
    try:
        while chunk := await file.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > MAX_RESUME_BYTES:
                raise HTTPException(status_code=413, detail="PDF 简历不能超过 20 MiB")
    finally:
        await file.close()

    raw = bytes(content)
    if b"%PDF-" not in raw[:1024]:
        raise HTTPException(status_code=400, detail="文件内容不是有效的 PDF")

    saved = service.save(raw, original_name=original_name, media_type="application/pdf")
    try:
        extraction = ResumeExtractor().extract(raw).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    extractions.save(saved.resource_id, extraction)
    if not saved.created:
        response.status_code = 200
    return ResumeResourceResponse(
        resource_id=saved.resource_id,
        content_sha256=saved.content_sha256,
        byte_size=saved.byte_size,
        media_type=saved.media_type,
        original_name=saved.original_name,
        duplicate=not saved.created,
    )


@router.post(
    "/resume-resources/{resource_id}/extract", response_model=ResumeExtractionResponse
)
async def extract_resume_resource(
    resource_id: str,
    service: FileResourceService = Depends(get_file_resource_service),
    extractions: ResumeExtractionService = Depends(get_resume_extraction_service),
) -> ResumeExtractionResponse:
    saved_extraction = extractions.get(resource_id)
    if saved_extraction is not None:
        return ResumeExtractionResponse(
            resource_id=resource_id, extraction=saved_extraction
        )
    try:
        content = service.read(resource_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="简历资源不存在") from exc
    try:
        extraction = ResumeExtractor().extract(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    serialized = extraction.to_dict()
    extractions.save(resource_id, serialized)
    return ResumeExtractionResponse(resource_id=resource_id, extraction=serialized)


@router.post("/profiles", status_code=201)
async def create_profile(
    request: CreateProfileRequest,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return _version_response(
            service.create_profile(
                request.fields, source_file_resource_id=request.source_file_resource_id
            )
        )
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.get("/profiles")
async def list_profiles(
    service: ProfileService = Depends(get_profile_service),
) -> list[dict[str, Any]]:
    result = service.list_profiles()
    for profile in result:
        profile["active_version"] = _version_response(profile["active_version"])
    return result


@router.get("/profiles/{profile_id}/versions")
async def list_profile_versions(
    profile_id: str,
    service: ProfileService = Depends(get_profile_service),
) -> list[dict[str, Any]]:
    try:
        return [_version_response(item) for item in service.list_versions(profile_id)]
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/profiles/{profile_id}/versions", status_code=201)
async def create_profile_version(
    profile_id: str,
    request: CreateProfileVersionRequest,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return _version_response(
            service.create_version(
                profile_id,
                request.fields,
                source_file_resource_id=request.source_file_resource_id,
                expected_version=request.expected_version,
            )
        )
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/profiles/{profile_id}/versions/{version_id}/activate")
async def activate_profile_version(
    profile_id: str,
    version_id: str,
    request: VersionMutationRequest,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return _version_response(
            service.set_active_version(
                profile_id, version_id, expected_version=request.expected_version
            )
        )
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/profiles/{profile_id}/versions/{version_id}/archive")
async def archive_profile_version(
    profile_id: str,
    version_id: str,
    request: VersionMutationRequest,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return _version_response(
            service.archive_version(
                profile_id, version_id, expected_version=request.expected_version
            )
        )
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.delete("/profiles/{profile_id}/versions/{version_id}", status_code=204)
async def delete_profile_version(
    profile_id: str,
    version_id: str,
    expected_version: int,
    service: ProfileService = Depends(get_profile_service),
) -> Response:
    try:
        service.delete_version(profile_id, version_id, expected_version=expected_version)
        return Response(status_code=204)
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/profiles/{profile_id}/change-proposals", status_code=201)
async def create_profile_change_proposal(
    profile_id: str,
    request: CreateChangeProposalRequest,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return service.create_change_proposal(
            profile_id,
            base_version_id=request.base_version_id,
            source_file_resource_id=request.source_file_resource_id,
            proposed_fields=request.proposed_fields,
        )
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.get("/change-proposals/{proposal_id}")
async def get_profile_change_proposal(
    proposal_id: str,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return service.get_change_proposal(proposal_id)
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/change-proposals/{proposal_id}/accept", status_code=201)
async def accept_profile_change_proposal(
    proposal_id: str,
    request: AcceptChangeProposalRequest,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return _version_response(
            service.accept_change_proposal(
                proposal_id,
                selected_fields=request.selected_fields,
                expected_version=request.expected_version,
            )
        )
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/change-proposals/{proposal_id}/discard")
async def discard_profile_change_proposal(
    proposal_id: str,
    service: ProfileService = Depends(get_profile_service),
) -> dict[str, Any]:
    try:
        return service.discard_change_proposal(proposal_id)
    except (ProfileNotFoundError, ProfileConflictError) as exc:
        raise _profile_error(exc) from exc


@router.post("/applications", status_code=201)
async def create_application(
    request: CreateApplicationRequest,
    service: ApplicationService = Depends(get_application_service),
) -> dict[str, Any]:
    try:
        return _application_response(
            service.create_application(
                source_url=request.source_url,
                profile_version_id=request.profile_version_id,
                title=request.title,
                company=request.company,
                description=request.description,
                idempotency_key=request.idempotency_key,
            )
        )
    except (ApplicationNotFoundError, ApplicationConflictError, UnsupportedJobUrlError) as exc:
        raise _application_error(exc) from exc


@router.get("/applications")
async def list_applications(
    service: ApplicationService = Depends(get_application_service),
) -> list[dict[str, Any]]:
    return [_application_response(item) for item in service.list_applications()]


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    service: ApplicationService = Depends(get_application_service),
) -> dict[str, Any]:
    try:
        return _application_response(service.get_application(application_id))
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc


@router.post("/applications/{application_id}/profile-version")
async def change_application_profile(
    application_id: str,
    request: ChangeApplicationProfileRequest,
    service: ApplicationService = Depends(get_application_service),
) -> dict[str, Any]:
    try:
        return _application_response(
            service.change_profile_version(
                application_id,
                profile_version_id=request.profile_version_id,
                expected_version=request.expected_version,
            )
        )
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc


@router.post("/applications/{application_id}/prepare")
async def prepare_application(
    application_id: str,
    request: PrepareApplicationRequest,
    service: ApplicationService = Depends(get_application_service),
) -> dict[str, Any]:
    try:
        return _application_response(
            service.prepare_for_review(
                application_id,
                form_values=request.form_values,
                expected_version=request.expected_version,
            )
        )
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc


@router.post("/applications/{application_id}/approve-review")
async def approve_application_review(
    application_id: str,
    request: ApplicationMutationRequest,
    service: ApplicationService = Depends(get_application_service),
) -> dict[str, Any]:
    try:
        return _application_response(
            service.approve_review(
                application_id, expected_version=request.expected_version
            )
        )
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc


@router.post("/applications/{application_id}/submission-outcome")
async def record_application_outcome(
    application_id: str,
    request: SubmissionOutcomeRequest,
    service: ApplicationService = Depends(get_application_service),
) -> dict[str, Any]:
    try:
        return _application_response(
            service.record_submission_outcome(
                application_id,
                outcome=request.outcome,
                evidence=request.evidence,
                expected_version=request.expected_version,
            )
        )
    except (ApplicationNotFoundError, ApplicationConflictError, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise _application_error(exc) from exc


@router.get("/applications/{application_id}/audit-events")
async def list_application_audit_events(
    application_id: str,
    service: ApplicationService = Depends(get_application_service),
) -> list[dict[str, Any]]:
    try:
        return service.list_audit_events(application_id)
    except ApplicationNotFoundError as exc:
        raise _application_error(exc) from exc


@router.post("/applications/{application_id}/browser/open")
async def open_application_browser(
    application_id: str,
    coordinator: BrowserCoordinator = Depends(get_browser_coordinator),
) -> dict[str, Any]:
    try:
        return asdict(await coordinator.open_application(application_id))
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"受管浏览器启动失败：{exc}") from exc


@router.post("/applications/{application_id}/browser/continue")
async def continue_application_browser(
    application_id: str,
    coordinator: BrowserCoordinator = Depends(get_browser_coordinator),
) -> dict[str, Any]:
    try:
        return asdict(await coordinator.continue_after_takeover(application_id))
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"受管浏览器检查失败：{exc}") from exc


@router.post("/applications/{application_id}/browser/observe-submission")
async def observe_application_submission(
    application_id: str,
    coordinator: BrowserCoordinator = Depends(get_browser_coordinator),
) -> dict[str, Any]:
    try:
        return asdict(await coordinator.observe_submission(application_id))
    except (ApplicationNotFoundError, ApplicationConflictError) as exc:
        raise _application_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"提交回执检查失败：{exc}") from exc


@router.get("/interaction-hints")
async def list_interaction_hints(
    review_status: str | None = None,
    coordinator: BrowserCoordinator = Depends(get_browser_coordinator),
) -> list[dict[str, Any]]:
    return coordinator.list_hints(review_status=review_status)


@router.post("/interaction-hints/{hint_id}/review")
async def review_interaction_hint(
    hint_id: str,
    request: ReviewHintRequest,
    coordinator: BrowserCoordinator = Depends(get_browser_coordinator),
) -> dict[str, Any]:
    try:
        return coordinator.review_hint(hint_id, status=request.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="交互提示不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
