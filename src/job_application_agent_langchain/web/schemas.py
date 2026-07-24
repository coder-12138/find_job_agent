"""Web API 的 Pydantic 数据模型。"""

from typing import Any

from pydantic import BaseModel, Field


class CompanyInput(BaseModel):
    """单家公司的输入参数。"""

    company_name: str
    recruitment_type: str = "校招"
    referral_code: str = ""
    job_keywords: str = ""
    preferred_cities: list[str] = Field(default_factory=list)
    parallel: bool = False


class SessionCreateRequest(BaseModel):
    """创建投递会话的请求体。"""

    companies: list[CompanyInput]
    parallel: bool = False


class DocumentSessionRequest(BaseModel):
    """文档投递会话请求。"""

    doc_url: str
    job_keyword: str = ""
    industry: str = ""
    city: str = ""
    recruitment_type: str = "校招"
    parallel: bool = False


class SessionResponse(BaseModel):
    """创建会话后的响应。"""

    session_id: str
    status: str
    created_at: str


class NotificationSettings(BaseModel):
    """邮件通知设置。"""

    email_enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_sender_email: str = ""
    smtp_sender_password: str = ""
    smtp_recipient_email: str = ""


class ApiSettings(BaseModel):
    """Agent API 配置（API 地址、密钥、模型名称）。"""

    api_base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model_name: str = "gpt-4o"


class MemoryResponse(BaseModel):
    """记忆内容响应。"""

    learned_fields: dict[str, Any] = Field(default_factory=dict)
    source_user_info: dict[str, Any] = Field(default_factory=dict)
    field_metadata: dict[str, Any] = Field(default_factory=dict)


class ConfirmRequest(BaseModel):
    """用户对请求的响应。"""

    request_id: str
    # confirmation / missing_fields / resume_review / position_selection
    response_type: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class FileUploadResponse(BaseModel):
    """文件上传响应。"""

    filename: str
    file_type: str
    saved_path: str
    size: int


class MessageRequest(BaseModel):
    """用户干预消息请求（续接/中断重试）。"""

    message: str
