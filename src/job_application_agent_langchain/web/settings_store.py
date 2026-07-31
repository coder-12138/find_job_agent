"""Web 设置管理。

通知设置仍保存到本地 JSON。Agent API 密钥仅保存在当前 Python 进程
的内存中，服务重启后自动清空，不写入 .env 或任何 JSON 文件。
"""

import json
import os
from datetime import datetime
from pathlib import Path

from job_application_agent_langchain.web.schemas import (
    ApiConnectionTestResponse,
    ApiSettings,
    ApiSettingsStatus,
    NotificationSettings,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SETTINGS_FILE = PROJECT_ROOT / "data" / "notification_settings.json"

# 字段名 -> 环境变量名
_ENV_MAP = {
    "email_enabled": "EMAIL_NOTIFICATION_ENABLED",
    "smtp_server": "SMTP_SERVER",
    "smtp_port": "SMTP_PORT",
    "smtp_use_tls": "SMTP_USE_TLS",
    "smtp_sender_email": "SMTP_SENDER_EMAIL",
    "smtp_sender_password": "SMTP_SENDER_PASSWORD",
    "smtp_recipient_email": "SMTP_RECIPIENT_EMAIL",
}


_temporary_api_settings = ApiSettings()
_api_verified = False
_api_verified_at = ""
_api_last_error = ""


def _value_only(value: str, *variable_names: str) -> str:
    """同时接受纯值和形如 NAME=value 的整行粘贴内容。"""
    text = value.strip()
    for name in variable_names:
        prefix = f"{name}="
        if text.upper().startswith(prefix):
            text = text[len(prefix):].strip()
            break
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _sync_runtime_settings(settings: ApiSettings) -> None:
    """只同步当前进程中的 Settings 单例，不写环境变量或磁盘。"""
    from job_application_agent_langchain.config import Settings

    runtime = Settings()
    runtime.openai_base_url = settings.api_base_url
    runtime.openai_api_key = settings.api_key
    runtime.openai_model = settings.model_name


def load_api_settings() -> ApiSettingsStatus:
    """返回临时 API 配置状态；密钥永远不会通过接口回传。"""
    return ApiSettingsStatus(
        api_base_url=_temporary_api_settings.api_base_url,
        model_name=_temporary_api_settings.model_name,
        api_key_configured=bool(_temporary_api_settings.api_key),
        verified=_api_verified,
        verified_at=_api_verified_at,
        last_error=_api_last_error,
    )


def save_api_settings(settings: ApiSettings) -> ApiSettingsStatus:
    """将 API 配置保存到当前进程内存，修改后需要重新验证。"""
    global _temporary_api_settings, _api_verified, _api_verified_at, _api_last_error

    _temporary_api_settings = settings.model_copy(deep=True)
    _api_verified = False
    _api_verified_at = ""
    _api_last_error = ""
    _sync_runtime_settings(_temporary_api_settings)
    return load_api_settings()


def clear_api_settings() -> ApiSettingsStatus:
    """清除当前进程中的 API 密钥和验证状态。"""
    global _temporary_api_settings, _api_verified, _api_verified_at, _api_last_error

    _temporary_api_settings = ApiSettings()
    _api_verified = False
    _api_verified_at = ""
    _api_last_error = ""
    _sync_runtime_settings(_temporary_api_settings)
    return load_api_settings()


def is_api_verified() -> bool:
    """当前进程中的 Agent API 是否已成功验证。"""
    return _api_verified


async def verify_api_settings(settings: ApiSettings) -> ApiConnectionTestResponse:
    """调用一次最小模型请求；成功后才把配置用于当前进程。"""
    global _temporary_api_settings, _api_verified, _api_verified_at, _api_last_error

    # 一旦开始验证新配置，旧连接立即失效，避免新配置验证失败后误用旧密钥。
    _temporary_api_settings = ApiSettings()
    _api_verified = False
    _api_verified_at = ""
    _api_last_error = ""
    _sync_runtime_settings(_temporary_api_settings)

    api_base_url = _value_only(
        settings.api_base_url, "OPENAI_API_BASE", "OPENAI_BASE_URL"
    )
    api_key = _value_only(settings.api_key, "OPENAI_API_KEY")
    model_name = _value_only(settings.model_name, "OPENAI_MODEL")
    if not api_base_url:
        _api_last_error = "API 接口地址不能为空"
        raise ValueError("API 接口地址不能为空")
    if not api_key:
        _api_last_error = "API 密钥不能为空"
        raise ValueError("API 密钥不能为空")
    if not model_name:
        _api_last_error = "模型名称不能为空"
        raise ValueError("模型名称不能为空")

    from langchain_openai import ChatOpenAI

    candidate = ApiSettings(
        api_base_url=api_base_url,
        api_key=api_key,
        model_name=model_name,
    )
    try:
        llm = ChatOpenAI(
            model=candidate.model_name,
            api_key=candidate.api_key,
            base_url=candidate.api_base_url,
            temperature=0,
            timeout=20,
            max_retries=0,
        )
        await llm.ainvoke("This is a connection test. Reply with OK only.")
    except Exception as exc:
        safe_detail = str(exc).replace(api_key, "***")[:500]
        _api_last_error = f"连接验证失败：{type(exc).__name__}: {safe_detail}"
        print(f"[settings_store] {_api_last_error}")
        raise RuntimeError(_api_last_error) from exc

    _temporary_api_settings = candidate
    _api_verified = True
    _api_verified_at = datetime.now().astimezone().isoformat(timespec="seconds")
    _api_last_error = ""
    _sync_runtime_settings(_temporary_api_settings)
    return ApiConnectionTestResponse(
        success=True,
        message="Agent API 连接验证成功，配置仅在本次服务运行期间有效",
        api_base_url=candidate.api_base_url,
        model_name=candidate.model_name,
        verified_at=_api_verified_at,
    )


def load_settings() -> NotificationSettings:
    """从文件加载通知设置，不存在则尝试从环境变量读取默认值。"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return NotificationSettings(**data)
        except Exception as e:
            print(f"[settings_store] 加载通知设置失败: {e}，使用默认值")

    return NotificationSettings(
        email_enabled=os.getenv("EMAIL_NOTIFICATION_ENABLED", "false").lower() == "true",
        smtp_server=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        smtp_sender_email=os.getenv("SMTP_SENDER_EMAIL", ""),
        smtp_sender_password=os.getenv("SMTP_SENDER_PASSWORD", ""),
        smtp_recipient_email=os.getenv("SMTP_RECIPIENT_EMAIL", ""),
    )


def save_settings(settings: NotificationSettings) -> bool:
    """保存通知设置到文件，并同步到环境变量与 Settings 单例。"""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings.model_dump(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[settings_store] 保存通知设置失败: {e}")
        return False

    # 同步到环境变量
    data = settings.model_dump()
    for field, env_key in _ENV_MAP.items():
        value = data[field]
        if isinstance(value, bool):
            os.environ[env_key] = "true" if value else "false"
        else:
            os.environ[env_key] = str(value)

    # 同步到 Settings 单例，使后续运行能立即生效
    try:
        from job_application_agent_langchain.config import Settings

        s = Settings()
        s.email_notification_enabled = settings.email_enabled
        s.smtp_server = settings.smtp_server
        s.smtp_port = settings.smtp_port
        s.smtp_use_tls = settings.smtp_use_tls
        s.smtp_sender_email = settings.smtp_sender_email
        s.smtp_sender_password = settings.smtp_sender_password
        s.smtp_recipient_email = settings.smtp_recipient_email
    except Exception as e:
        print(f"[settings_store] 同步 Settings 单例失败: {e}")

    return True
