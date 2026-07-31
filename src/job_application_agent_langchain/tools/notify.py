import asyncio
import smtplib
import sys
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from langchain_core.tools import tool


class NotificationState:
    """通知状态，用于在 LangGraph 节点间传递"""

    def __init__(self):
        self.last_notification = ""
        self.last_user_response = ""
        self.pending_question = False


_notify_state = NotificationState()


def _safe_console_print(value: object = "") -> None:
    """Never let a Windows console code page abort an application workflow."""

    text = str(value)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        printable = text.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
        print(printable)


def _send_email(subject: str, body: str) -> bool:
    from job_application_agent_langchain.config import Settings

    settings = Settings()
    if not settings.email_notification_enabled:
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = settings.smtp_sender_email
        msg["To"] = settings.smtp_recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html", "utf-8"))

        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_server, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_server, settings.smtp_port)

        server.login(settings.smtp_sender_email, settings.smtp_sender_password)
        server.sendmail(
            settings.smtp_sender_email, settings.smtp_recipient_email, msg.as_string()
        )
        server.quit()
        return True
    except Exception as e:
        _safe_console_print(f"[邮件通知] 发送失败: {e}")
        return False


def _show_desktop_notification(title: str, message: str) -> bool:
    from job_application_agent_langchain.config import Settings

    settings = Settings()
    if not settings.has_desktop:
        return False

    try:
        from plyer import notification

        notification.notify(title=title, message=message, app_name="校招投递Agent", timeout=10)
        return True
    except Exception:
        return False


def _terminal_print(title: str, message: str, level: str = "info"):
    prefix_map = {
        "info": "ℹ️",
        "warning": "⚠️",
        "error": "❌",
        "success": "✅",
    }
    prefix = prefix_map.get(level, "ℹ️")
    separator = "=" * 60
    _safe_console_print(f"\n{separator}")
    _safe_console_print(f"{prefix} {title}")
    _safe_console_print(separator)
    _safe_console_print(message)
    _safe_console_print(separator)


def _get_user_input(prompt: str) -> str:
    _safe_console_print(f"\n🤖 {prompt}")
    try:
        response = input("👉 请输入: ")
        return response.strip()
    except (EOFError, KeyboardInterrupt):
        return ""


@tool
def notify_user(
    title: str,
    message: str,
    level: str = "info",
    need_confirmation: bool = False,
    confirmation_prompt: str = "",
) -> str:
    """通知用户，支持终端打印、系统弹窗和邮件通知。当Agent需要暂停、遇到问题或需要用户决策时调用此工具。

    Args:
        title: 通知标题
        message: 通知内容
        level: 通知级别，可选 info/warning/error/success，默认 info
        need_confirmation: 是否需要用户确认输入，默认 False
        confirmation_prompt: 需要用户确认时的提示语
    """
    _terminal_print(title, message, level)

    _show_desktop_notification(title, message)

    from job_application_agent_langchain.config import Settings

    settings = Settings()
    if settings.email_notification_enabled:
        thread = threading.Thread(
            target=_send_email, args=(f"[校招Agent] {title}", message), daemon=True
        )
        thread.start()

    user_response = ""
    if need_confirmation:
        prompt = confirmation_prompt or "请确认（输入 y 继续，输入 n 取消）:"
        user_response = _get_user_input(prompt)

    if user_response:
        return f"用户回复: {user_response}"
    return "通知已发送"


@tool
def notify_delivery_warning(company_name: str) -> str:
    """投递确认警告。在Form Agent完成简历填写后，弹出醒目警告询问用户是否由AI进行投递。

    Args:
        company_name: 公司名称
    """
    warning_title = "⚠️ 重要警告 - 投递确认"
    warning_message = (
        f"公司: {company_name}\n\n"
        "⚠️ 重要警告：执行此步，AI agent将直接自动完成简历投递，"
        "不会再暂停让您检查并确认，"
        "部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，"
        "请谨慎选择\n\n"
        "请选择：\n"
        "  输入 yes - 由AI自动完成投递\n"
        "  输入 no  - 不由AI投递，结束该公司的流程"
    )

    _terminal_print(warning_title, warning_message, "warning")

    _show_desktop_notification(warning_title, "AI投递确认 - 请在终端中操作")

    from job_application_agent_langchain.config import Settings

    settings = Settings()
    if settings.email_notification_enabled:
        thread = threading.Thread(
            target=_send_email,
            args=(f"[校招Agent] {warning_title}", warning_message),
            daemon=True,
        )
        thread.start()

    user_response = _get_user_input("是否由AI进行投递？（yes/no）")

    if user_response.lower() in ("yes", "y", "是"):
        return "用户选择: 同意AI投递"
    return "用户选择: 拒绝AI投递，结束该公司流程"


@tool
def ask_user_for_field(field_name: str, field_label: str = "", reason: str = "") -> str:
    """当必填字段信息缺失时，询问用户该字段的值。

    Args:
        field_name: 字段名（内部标识）
        field_label: 字段显示名称
        reason: 询问原因
    """
    label = field_label or field_name
    prompt = f"表单需要填写「{label}」，但在您的个人信息文档中未找到该信息。"
    if reason:
        prompt += f"\n原因: {reason}"

    _terminal_print(
        f"需要补充信息: {label}",
        prompt,
        "warning",
    )

    user_response = _get_user_input(f"请提供「{label}」的值:")
    return user_response


def get_notification_state() -> NotificationState:
    return _notify_state
