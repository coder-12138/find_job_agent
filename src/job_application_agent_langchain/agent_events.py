"""Agent 事件发射器接口与终端实现。

此模块定义了 Agent 与 Web UI 层之间的交互契约。
Web UI 层（Task 3）实现 AgentEventEmitter 接口，Agent 通过它与用户交互。
CLIEmitter 提供终端实现，用于无 Web UI 时的命令行运行。
"""

import uuid
from abc import ABC, abstractmethod
from typing import Any


class AgentEventEmitter(ABC):
    """Agent 事件发射器接口。Web UI 层实现此接口，Agent 通过它与用户交互。"""

    @abstractmethod
    async def emit_progress(self, phase: str, message: str, company: str = "") -> None:
        """推送执行进度（phase: search/recommend/polish/fill/confirm/submit 等）"""

    @abstractmethod
    async def emit_screenshot(self, path: str, company: str = "") -> None:
        """推送截图路径供 UI 展示"""

    @abstractmethod
    async def emit_log(self, level: str, message: str) -> None:
        """推送日志（level: info/warning/error/success）"""

    @abstractmethod
    async def request_confirmation(self, request_id: str, title: str, message: str, options: list[str]) -> str:
        """请求用户确认，返回用户选择的 option"""

    @abstractmethod
    async def request_missing_fields(self, request_id: str, fields: list[dict]) -> dict:
        """批量请求用户补充缺失的必填字段。fields: [{"name","label","reason"},...]。返回 {field_name: value}"""

    @abstractmethod
    async def request_resume_review(self, request_id: str, original: dict, polished: dict) -> dict:
        """请求用户审核润色后的简历。返回确认/编辑后的 polished 内容 dict"""

    @abstractmethod
    async def request_position_selection(self, request_id: str, positions: list[dict]) -> list:
        """请求用户选择岗位。返回选中的岗位列表（含志愿顺序）"""

    @abstractmethod
    async def request_user_login(
        self,
        request_id: str,
        login_url: str,
        message: str,
        mode: str = "login",
    ) -> str:
        """请求用户在浏览器窗口中完成登录/注册。

        Args:
            request_id: 请求 ID
            login_url: 当前登录页 URL
            message: 提示消息

        Returns:
            "logged_in" 表示用户已完成登录，"retry" 表示需要重新登录
        """
        ...


class CLIEmitter(AgentEventEmitter):
    """终端实现，用于无 Web UI 时的命令行运行。用 print/input 完成交互。"""

    def __init__(self):
        self._company: str = ""

    def _print_separator(self, char: str = "="):
        print(char * 60)

    async def emit_progress(self, phase: str, message: str, company: str = "") -> None:
        prefix_map = {
            "search": "🔍",
            "recommend": "📋",
            "polish": "✨",
            "fill": "✍️",
            "confirm": "⚠️",
            "submit": "🚀",
        }
        prefix = prefix_map.get(phase, "▶️")
        label = f"[{company}] " if company else ""
        print(f"\n{prefix} {label}{phase}: {message}")

    async def emit_screenshot(self, path: str, company: str = "") -> None:
        label = f"[{company}] " if company else ""
        print(f"\n📸 {label}截图已保存: {path}")

    async def emit_log(self, level: str, message: str) -> None:
        prefix_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }
        prefix = prefix_map.get(level, "ℹ️")
        print(f"{prefix} {message}")

    async def request_confirmation(self, request_id: str, title: str, message: str, options: list[str]) -> str:
        self._print_separator()
        print(f"⚠️ {title}")
        self._print_separator()
        print(message)
        print("\n可选选项:")
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        self._print_separator("-")

        while True:
            try:
                choice = input(f"👉 请输入选项编号（1-{len(options)}）: ").strip()
            except (EOFError, KeyboardInterrupt):
                return options[-1] if options else ""
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                selected = options[int(choice) - 1]
                print(f"  ✅ 已选择: {selected}")
                return selected
            print("  ❌ 无效输入，请重新选择")

    async def request_missing_fields(self, request_id: str, fields: list[dict]) -> dict:
        self._print_separator()
        print("📝 需要补充以下缺失的必填字段:")
        self._print_separator()

        results: dict[str, Any] = {}
        for field in fields:
            name = field.get("name", "")
            label = field.get("label", name)
            reason = field.get("reason", "")
            prompt_text = f"请提供「{label}」的值"
            if reason:
                prompt_text += f"（原因: {reason}）"
            try:
                value = input(f"👉 {prompt_text}: ").strip()
            except (EOFError, KeyboardInterrupt):
                value = ""
            results[name] = value
            print(f"  ✅ 已记录: {label} = {value}")

        self._print_separator("-")
        return results

    async def request_resume_review(self, request_id: str, original: dict, polished: dict) -> dict:
        self._print_separator()
        print("📝 简历润色审核:")
        self._print_separator()
        print("\n--- 原始简历内容 ---")
        self._print_dict(original)
        print("\n--- 润色后简历内容 ---")
        self._print_dict(polished)
        self._print_separator("-")

        print("\n请选择:")
        print("  1. 确认使用润色内容")
        print("  2. 手动编辑润色内容")
        while True:
            try:
                choice = input("👉 请选择（1-2）: ").strip()
            except (EOFError, KeyboardInterrupt):
                choice = "1"
            if choice in ("1", "2"):
                break
            print("  ❌ 无效输入")

        if choice == "1":
            print("  ✅ 已确认使用润色内容")
            return polished

        # 手动编辑：逐字段让用户修改
        edited = dict(polished)
        for key, value in edited.items():
            try:
                new_value = input(f"👉 {key}（当前: {value}，直接回车保持不变）: ").strip()
            except (EOFError, KeyboardInterrupt):
                new_value = ""
            if new_value:
                edited[key] = new_value
        print("  ✅ 已保存编辑后的内容")
        return edited

    async def request_position_selection(self, request_id: str, positions: list[dict]) -> list:
        self._print_separator()
        print("📋 请选择要投递的岗位（可多选，按志愿顺序输入编号，用逗号分隔）:")
        self._print_separator()

        for i, pos in enumerate(positions, 1):
            name = pos.get("name", pos.get("title", ""))
            location = pos.get("location", "")
            reason = pos.get("reason", "")
            print(f"  {i}. {name}" + (f"（{location}）" if location else ""))
            if reason:
                print(f"     推荐理由: {reason}")

        self._print_separator("-")
        try:
            choice = input(f"👉 请输入选择的岗位编号（1-{len(positions)}，逗号分隔）: ").strip()
        except (EOFError, KeyboardInterrupt):
            return []

        selected: list[dict] = []
        for part in choice.split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= len(positions):
                pos = dict(positions[int(part) - 1])
                pos["volunteer_order"] = len(selected) + 1
                selected.append(pos)

        if selected:
            print(f"  ✅ 已选择 {len(selected)} 个岗位")
        return selected

    async def request_user_login(
        self,
        request_id: str,
        login_url: str,
        message: str,
        mode: str = "login",
    ) -> str:
        print(f"\n{'='*50}")
        print("🧭 需要进入申请表单" if mode == "application_form" else "🔐 需要登录")
        print(f"当前目标: {login_url}")
        print(f"提示: {message}")
        print(f"请在浏览器窗口中完成登录，完成后按回车...")
        print(f"{'='*50}")
        input()  # 等待用户按回车
        return "logged_in"

    @staticmethod
    def _print_dict(data: dict, indent: int = 0):
        prefix = "  " * indent
        for key, value in data.items():
            if isinstance(value, dict):
                print(f"{prefix}{key}:")
                CLIEmitter._print_dict(value, indent + 1)
            elif isinstance(value, list):
                print(f"{prefix}{key}:")
                for item in value:
                    print(f"{prefix}  - {item}")
            else:
                print(f"{prefix}{key}: {value}")


def generate_request_id() -> str:
    """生成唯一的请求 ID"""
    return str(uuid.uuid4())[:8]
