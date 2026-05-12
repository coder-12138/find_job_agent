import os
import sys
import tempfile
from pathlib import Path
from dotenv import load_dotenv


class Settings:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._load_env()
        self._parse_settings()

    def _load_env(self):
        env_path = Path(__file__).parent.parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv()

    def _parse_settings(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")

        self.email_notification_enabled = os.getenv("EMAIL_NOTIFICATION_ENABLED", "false").lower() == "true"
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        self.smtp_sender_email = os.getenv("SMTP_SENDER_EMAIL", "")
        self.smtp_sender_password = os.getenv("SMTP_SENDER_PASSWORD", "")
        self.smtp_recipient_email = os.getenv("SMTP_RECIPIENT_EMAIL", "")

        self.resume_file_path = os.getenv("RESUME_FILE_PATH", "./data/resume.pdf")
        self.personal_info_file_path = os.getenv("PERSONAL_INFO_FILE_PATH", "./data/personal_info.json")

        self.browser_headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
        self.browser_timeout = int(os.getenv("BROWSER_TIMEOUT", "30000"))

        self.has_desktop = self._detect_desktop()

        self.read_only_dirs = [
            os.path.dirname(os.path.abspath(self.resume_file_path)),
            os.path.dirname(os.path.abspath(self.personal_info_file_path)),
        ]
        self.write_only_dirs = [tempfile.gettempdir()]

    def _detect_desktop(self) -> bool:
        if sys.platform == "linux":
            display = os.environ.get("DISPLAY", "")
            wayland = os.environ.get("WAYLAND_DISPLAY", "")
            if not display and not wayland:
                return False
        return True

    def validate(self) -> list[str]:
        errors = []
        if not self.openai_api_key or self.openai_api_key == "sk-your-api-key-here":
            errors.append("OPENAI_API_KEY 未配置，请在 .env 文件中设置")
        if self.email_notification_enabled:
            if not self.smtp_sender_email:
                errors.append("邮件通知已启用但 SMTP_SENDER_EMAIL 未配置")
            if not self.smtp_sender_password:
                errors.append("邮件通知已启用但 SMTP_SENDER_PASSWORD 未配置")
            if not self.smtp_recipient_email:
                errors.append("邮件通知已启用但 SMTP_RECIPIENT_EMAIL 未配置")
        return errors
