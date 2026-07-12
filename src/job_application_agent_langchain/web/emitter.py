"""WebEventEmitter —— Agent 与 Web UI 之间的桥接。

实现 AgentEventEmitter 接口：
- emit_* 方法：通过 WebSocket 立即推送事件给前端（非阻塞）
- request_* 方法：推送请求事件后等待用户响应（阻塞，基于 asyncio.Future）
"""

import asyncio
from typing import TYPE_CHECKING, Any

from job_application_agent_langchain.agent_events import AgentEventEmitter

if TYPE_CHECKING:
    from job_application_agent_langchain.web.session_manager import SessionManager

# 用户请求超时时间（秒）
REQUEST_TIMEOUT = 300  # 5 分钟

# WebSocket 断开时设置到 future 上的哨兵值，emitter 据此返回默认值
_DISCONNECTED_SENTINEL = {"__disconnected__": True}


class WebEventEmitter(AgentEventEmitter):
    """Web UI 事件发射器，通过 SessionManager 推送事件并等待用户响应。"""

    def __init__(self, session_id: str, session_manager: "SessionManager"):
        self.session_id = session_id
        self.session_manager = session_manager

    # ------------------------------------------------------------------
    # 非阻塞推送方法
    # ------------------------------------------------------------------

    async def emit_progress(self, phase: str, message: str, company: str = "") -> None:
        await self.session_manager.push_event(
            self.session_id,
            {
                "type": "progress",
                "phase": phase,
                "message": message,
                "company": company,
            },
        )

    async def emit_screenshot(self, path: str, company: str = "") -> None:
        await self.session_manager.push_event(
            self.session_id,
            {
                "type": "screenshot",
                "path": path,
                "company": company,
            },
        )

    async def emit_log(self, level: str, message: str) -> None:
        await self.session_manager.push_event(
            self.session_id,
            {
                "type": "log",
                "level": level,
                "message": message,
            },
        )

    # ------------------------------------------------------------------
    # 阻塞请求方法
    # ------------------------------------------------------------------

    async def request_confirmation(
        self, request_id: str, title: str, message: str, options: list[str]
    ) -> str:
        default_selected = options[-1] if options else ""
        event = {
            "type": "request",
            "request_id": request_id,
            "request_type": "confirmation",
            "title": title,
            "message": message,
            "options": options,
        }
        result = await self._request(event, request_id, {"selected": default_selected})
        if isinstance(result, dict):
            selected = result.get("selected", "")
        else:
            selected = str(result)
        return selected or default_selected

    async def request_missing_fields(self, request_id: str, fields: list[dict]) -> dict:
        event = {
            "type": "request",
            "request_id": request_id,
            "request_type": "missing_fields",
            "fields": fields,
        }
        result = await self._request(event, request_id, {"fields": {}})
        if isinstance(result, dict):
            return result.get("fields", result)
        return {}

    async def request_resume_review(
        self, request_id: str, original: dict, polished: dict
    ) -> dict:
        event = {
            "type": "request",
            "request_id": request_id,
            "request_type": "resume_review",
            "original": original,
            "polished": polished,
        }
        result = await self._request(event, request_id, {"confirmed": polished})
        if isinstance(result, dict):
            return result.get("confirmed", result)
        return polished

    async def request_position_selection(
        self, request_id: str, positions: list[dict]
    ) -> list:
        event = {
            "type": "request",
            "request_id": request_id,
            "request_type": "position_selection",
            "positions": positions,
        }
        result = await self._request(event, request_id, {"selected_positions": []})
        if isinstance(result, dict):
            selected = result.get("selected_positions", [])
        elif isinstance(result, list):
            selected = result
        else:
            selected = []
        return selected if isinstance(selected, list) else []

    # ------------------------------------------------------------------
    # 内部：注册 future、推送请求、等待响应
    # ------------------------------------------------------------------

    async def _request(self, event: dict, request_id: str, default: Any) -> Any:
        """推送请求事件并等待用户响应。

        Args:
            event: 推送给前端的请求事件
            request_id: 请求 ID
            default: 超时或断开时返回的默认值

        Returns:
            用户响应数据，或超时/断开时的默认值
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self.session_manager.register_request(self.session_id, request_id, future)

        # 推送请求事件给前端
        await self.session_manager.push_event(self.session_id, event)

        try:
            result = await asyncio.wait_for(future, timeout=REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            await self.session_manager.push_event(
                self.session_id,
                {
                    "type": "error",
                    "message": f"请求 {request_id} 等待用户响应超时（{REQUEST_TIMEOUT}秒）",
                },
            )
            self.session_manager.unregister_request(self.session_id, request_id)
            return default
        except asyncio.CancelledError:
            # 任务被取消（如服务停止），返回默认值
            self.session_manager.unregister_request(self.session_id, request_id)
            return default

        # WebSocket 断开时由 detach_websocket 设置哨兵值
        if isinstance(result, dict) and result.get("__disconnected__"):
            return default
        return result
