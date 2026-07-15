"""REST API 路由。"""

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import CompanyState, RECRUITMENT_TYPES
from job_application_agent_langchain.user_info.parser import load_user_info
from job_application_agent_langchain.web.file_storage import list_uploads, save_upload_file
from job_application_agent_langchain.web.schemas import (
    ConfirmRequest,
    FileUploadResponse,
    MemoryResponse,
    MessageRequest,
    NotificationSettings,
    SessionCreateRequest,
    SessionResponse,
)
from job_application_agent_langchain.web.session_manager import session_manager
from job_application_agent_langchain.web.settings_store import load_settings, save_settings

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _load_user_info():
    """加载用户信息（每次调用都重新读取，以反映最新文件）。"""
    settings = Settings()
    return load_user_info(settings.personal_info_file_path, settings.resume_file_path)


# ----------------------------------------------------------------------
# 会话相关
# ----------------------------------------------------------------------

@router.post("/sessions", response_model=SessionResponse)
async def create_session(req: SessionCreateRequest) -> SessionResponse:
    """创建投递会话并启动后台 Agent。"""
    if not req.companies:
        raise HTTPException(status_code=400, detail="至少需要一家公司")

    settings = Settings()
    errors = settings.validate()
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    user_info = _load_user_info()

    companies = [
        CompanyState(
            company_name=c.company_name,
            recruitment_type=c.recruitment_type,
            referral_code=c.referral_code,
            job_keywords=c.job_keywords,
            preferred_cities=list(c.preferred_cities),
        )
        for c in req.companies
    ]

    session_id = session_manager.create_session(companies, req.parallel, user_info)
    info = session_manager.get_session(session_id)
    return SessionResponse(
        session_id=session_id,
        status=info.status if info else "pending",
        created_at=info.created_at if info else "",
    )


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


# ----------------------------------------------------------------------
# 文件上传
# ----------------------------------------------------------------------

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...), file_type: str = Form("other")
) -> FileUploadResponse:
    """上传文件。multipart 表单字段：file, file_type。"""
    try:
        return await save_upload_file(file, file_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.get("/uploads")
async def get_uploads() -> dict:
    """列出所有已上传的文件。"""
    return {"uploads": list_uploads()}


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
            return MemoryResponse(
                learned_fields=data.get("learned_fields", {}),
                source_user_info=data.get("source_user_info", {}),
                field_metadata=data.get("field_metadata", {}),
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取记忆失败: {e}")
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
