"""REST API 路由。"""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import CompanyState, RECRUITMENT_TYPES
from job_application_agent_langchain.api_v2.dependencies import (
    get_file_resource_service,
    get_profile_service,
    get_resume_extraction_service,
)
from job_application_agent_langchain.application.legacy_profile_bridge import (
    load_profile_for_legacy_session,
)
from job_application_agent_langchain.application.profiles import ProfileNotFoundError
from job_application_agent_langchain.resume_ingestion import ResumeExtractor
from job_application_agent_langchain.web.file_storage import (
    list_uploads,
    save_upload_file,
)
from job_application_agent_langchain.web.schemas import (
    ApiConnectionTestResponse,
    ApiSettings,
    ApiSettingsStatus,
    ConfirmRequest,
    DocumentSessionRequest,
    FileUploadResponse,
    MemoryResponse,
    MessageRequest,
    NotificationSettings,
    SessionCreateRequest,
    SessionResponse,
)
from job_application_agent_langchain.web.session_manager import session_manager
from job_application_agent_langchain.web.settings_store import (
    clear_api_settings,
    is_api_verified,
    load_api_settings,
    load_settings,
    save_api_settings,
    save_settings,
    verify_api_settings,
)

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------
# 会话相关
# ----------------------------------------------------------------------

@router.post("/sessions", response_model=SessionResponse)
async def create_session(req: SessionCreateRequest) -> SessionResponse:
    """创建投递会话并启动后台 Agent。"""
    if not req.companies:
        raise HTTPException(status_code=400, detail="至少需要一家公司")
    if not is_api_verified():
        raise HTTPException(
            status_code=400,
            detail="请先在左侧「Agent 连接」页面输入 API 配置并完成连接验证",
        )

    settings = Settings()
    errors = settings.validate()
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    try:
        profile_session = await asyncio.to_thread(
            load_profile_for_legacy_session, req.profile_version_id
        )
    except ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail="请先在「候选人档案」中上传 PDF、确认内容并选择一个可用版本",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"候选人档案的来源 PDF 无法用于润色：{exc}",
        ) from exc

    companies = [
        CompanyState(
            company_name=c.company_name,
            recruitment_type=c.recruitment_type,
            referral_code=c.referral_code,
            job_keywords=c.job_keywords,
            preferred_cities=list(c.preferred_cities),
            application_url=c.application_url,
        )
        for c in req.companies
    ]

    session_id = session_manager.create_session(
        companies,
        req.parallel,
        profile_session.user_info,
        profile_id=profile_session.profile_id,
        profile_version_id=profile_session.profile_version_id,
        temporary_files=list(profile_session.temporary_files),
    )
    info = session_manager.get_session(session_id)
    return SessionResponse(
        session_id=session_id,
        status=info.status if info else "pending",
        created_at=info.created_at if info else "",
    )


@router.post("/sessions/document", response_model=SessionResponse)
async def create_document_session_endpoint(req: DocumentSessionRequest) -> SessionResponse:
    """腾讯文档入口已按产品范围决定移除。"""
    del req
    raise HTTPException(status_code=410, detail="腾讯文档投递已移除，请在投递任务中直接添加公司")


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """获取会话状态和结果。"""
    status = session_manager.get_session_status(session_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="会话不存在")
    return status


@router.post("/sessions/{session_id}/confirm")
async def confirm_request(session_id: str, req: ConfirmRequest) -> dict:
    """用户响应请求，解析挂起的 future。"""
    info = session_manager.get_session(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    ok = session_manager.resolve_request(session_id, req.request_id, req.data)
    if not ok:
        raise HTTPException(status_code=404, detail="未找到对应的请求或请求已处理")
    return {"ok": True, "request_id": req.request_id}


@router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, req: MessageRequest) -> dict:
    """用户在 Agent 运行任意阶段发送文本消息干预。

    运行中发送的消息排队，ainvoke 完成后自动续接；
    已完成/出错时发送的消息会重启 Agent 任务。
    """
    info = session_manager.get_session(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session_manager.send_message(session_id, req.message)


@router.post("/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str, req: MessageRequest) -> dict:
    """中断当前 Agent 运行并以新的用户消息重启。"""
    info = session_manager.get_session(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session_manager.interrupt_and_restart(session_id, req.message)


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str) -> dict:
    """立即停止当前 Agent，不自动重启。"""
    info = session_manager.get_session(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await session_manager.cancel_session(session_id)


# ----------------------------------------------------------------------
# 文件上传
# ----------------------------------------------------------------------

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...), file_type: str = Form("other")
) -> FileUploadResponse:
    """上传文件。multipart 表单字段：file, file_type。"""
    try:
        if file_type != "resume":
            return await save_upload_file(file, file_type)

        original_name = Path(file.filename or "resume.pdf").name
        if Path(original_name).suffix.lower() != ".pdf":
            raise ValueError("简历只接受 PDF 文件")
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("PDF 简历不能超过 20 MiB")
        if b"%PDF-" not in content[:1024]:
            raise ValueError("文件内容不是有效的 PDF")
        saved = get_file_resource_service().save(
            content, original_name=original_name, media_type="application/pdf"
        )
        extraction = ResumeExtractor().extract(content).to_dict()
        get_resume_extraction_service().save(saved.resource_id, extraction)
        return FileUploadResponse(
            filename=original_name,
            file_type="resume",
            saved_path="",
            size=len(content),
            resource_id=saved.resource_id,
            duplicate=not saved.created,
            extraction=extraction,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.get("/uploads")
async def get_uploads() -> dict:
    """列出所有已上传的文件。"""
    encrypted_resumes = [
        {
            "file_type": "resume",
            "filename": item["original_name"],
            "saved_path": "",
            "size": item["byte_size"],
            "modified_at": item["created_at"],
            "resource_id": item["id"],
            "encrypted": True,
        }
        for item in get_file_resource_service().list_resources(
            media_type="application/pdf"
        )
    ]
    legacy_other_files = [
        item for item in list_uploads() if item.get("file_type") != "resume"
    ]
    return {"uploads": encrypted_resumes + legacy_other_files}


# ----------------------------------------------------------------------
# 通知设置
# ----------------------------------------------------------------------

@router.get("/settings/notifications", response_model=NotificationSettings)
async def get_notification_settings() -> NotificationSettings:
    return load_settings()


@router.put("/settings/notifications", response_model=NotificationSettings)
async def update_notification_settings(
    settings: NotificationSettings,
) -> NotificationSettings:
    ok = save_settings(settings)
    if not ok:
        raise HTTPException(status_code=500, detail="保存设置失败")
    return settings


# ----------------------------------------------------------------------
# API 配置
# ----------------------------------------------------------------------

@router.get("/settings/api", response_model=ApiSettingsStatus)
async def get_api_settings() -> ApiSettingsStatus:
    return load_api_settings()


@router.put("/settings/api", response_model=ApiSettingsStatus)
async def update_api_settings(settings: ApiSettings) -> ApiSettingsStatus:
    """临时载入配置但不验证；不会写入磁盘。"""
    return save_api_settings(settings)


@router.post("/settings/api/verify", response_model=ApiConnectionTestResponse)
async def verify_api_connection(settings: ApiSettings) -> ApiConnectionTestResponse:
    """验证 Agent API；成功后仅在本次服务进程中启用。"""
    try:
        return await verify_api_settings(settings)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/settings/api", response_model=ApiSettingsStatus)
async def delete_api_settings() -> ApiSettingsStatus:
    """立即清除当前进程内的 API 密钥。"""
    return clear_api_settings()


# ----------------------------------------------------------------------
# 记忆
# ----------------------------------------------------------------------

@router.get("/memory", response_model=MemoryResponse)
async def get_memory() -> MemoryResponse:
    """获取记忆内容（learned_fields / source_user_info / field_metadata）。"""
    settings = Settings()
    path = Path(settings.memory_file_path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            source_user_info = data.get("source_user_info", {})
            try:
                active = get_profile_service().get_active_version()
                fields = active.fields
                source_user_info = dict(fields.get("personal_info") or {})
                source_user_info.update(
                    {
                        key: value
                        for key, value in fields.items()
                        if key not in {"personal_info", "resume_text", "raw_resume_text"}
                        and not isinstance(value, (dict, list))
                    }
                )
                if fields.get("full_name"):
                    source_user_info["name"] = fields["full_name"]
            except ProfileNotFoundError:
                pass
            return MemoryResponse(
                learned_fields=data.get("learned_fields", {}),
                source_user_info=source_user_info,
                field_metadata=data.get("field_metadata", {}),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取记忆失败: {e}")
    try:
        active = get_profile_service().get_active_version()
        fields = dict(active.fields)
        source = dict(fields.get("personal_info") or {})
        source.update(
            {key: value for key, value in fields.items() if isinstance(value, str) and key != "resume_text"}
        )
        if fields.get("full_name"):
            source["name"] = fields["full_name"]
        return MemoryResponse(source_user_info=source)
    except ProfileNotFoundError:
        return MemoryResponse()


@router.delete("/memory/{field_name}")
async def delete_memory_field(field_name: str) -> dict:
    """删除记忆中某个 learned_field 字段（直接操作 JSON 以保留其它字段）。"""
    settings = Settings()
    path = Path(settings.memory_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="记忆文件不存在")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取记忆失败: {e}")

    learned = data.get("learned_fields", {})
    metadata = data.get("field_metadata", {})
    removed = False
    if field_name in learned:
        learned.pop(field_name)
        removed = True
    if field_name in metadata:
        metadata.pop(field_name)

    if not removed:
        raise HTTPException(status_code=404, detail=f"字段 {field_name} 不在 learned_fields 中")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存记忆失败: {e}")

    return {"ok": True, "field_name": field_name}


# ----------------------------------------------------------------------
# 其他
# ----------------------------------------------------------------------

@router.get("/recruitment-types")
async def get_recruitment_types() -> dict:
    """返回支持的招聘类型列表。"""
    return {"recruitment_types": RECRUITMENT_TYPES}


@router.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}
