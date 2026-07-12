"""通知设置的持久化存储。

将通知设置保存到 data/notification_settings.json，并同步更新环境变量
与 Settings 单例，使后续运行能读取到最新配置。
"""

import json
import os
from pathlib import Path

from job_application_agent_langchain.web.schemas import NotificationSettings

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
