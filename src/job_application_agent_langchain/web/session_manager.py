"""会话管理。

管理所有投递会话的生命周期：创建会话、启动后台 Agent 任务、
WebSocket 连接绑定、事件推送、用户请求响应解析。
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from job_application_agent_langchain.agent_events import AgentEventEmitter
from job_application_agent_langchain.agents.orchestrator import run_job_application
from job_application_agent_langchain.context import CompanyState
from job_application_agent_langchain.memory import AgentMemory
from job_application_agent_langchain.user_info.parser import UserInfo
from job_application_agent_langchain.web.emitter import WebEventEmitter

# WebSocket 断开时设置到 future 上的哨兵值
_DISCONNECTED_SENTINEL = {"__disconnected__": True}


@dataclass
class SessionInfo:
    """单个会话的运行时状态。"""

    session_id: str
    emitter: WebEventEmitter
    task: asyncio.Task | None = None
    websocket: WebSocket | None = None
    # pending / running / completed / error / disconnected
    status: str = "pending"
    results: dict[str, Any] = field(default_factory=dict)
    pending_requests: dict[str, asyncio.Future] = field(default_factory=dict)
    # WebSocket 未连接时缓存的事件，连接后冲刷
    event_queue: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error: str = ""
    companies: list[CompanyState] = field(default_factory=list)
    parallel: bool = False


class SessionManager:
    """会话管理器（模块级单例）。"""

    def __init__(self):
        self.sessions: dict[str, SessionInfo] = {}

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------

    def create_session(
        self,
        companies: list[CompanyState],
        parallel: bool,
        user_info: UserInfo,
        memory: AgentMemory | None = None,
    ) -> str:
        """创建会话并启动后台 Agent 任务。返回 session_id。

        Args:
            companies: 待投递公司列表
            parallel: 是否并行处理
            user_info: 用户信息
            memory: 可选的 Agent 记忆（目前由 orchestrator 内部加载）

        Returns:
            session_id
        """
        session_id = str(uuid.uuid4())[:12]
        emitter = WebEventEmitter(session_id, self)
        info = SessionInfo(
            session_id=session_id,
            emitter=emitter,
            companies=companies,
            parallel=parallel,
        )
        self.sessions[session_id] = info

        # 启动后台 Agent 任务（需在运行中的事件循环里调用）
        info.task = asyncio.create_task(
            self._run_agent(session_id, user_info, companies, parallel, emitter)
        )
        return session_id

    async def _run_agent(
        self,
        session_id: str,
        user_info: UserInfo,
        companies: list[CompanyState],
        parallel: bool,
        emitter: AgentEventEmitter,
    ) -> None:
        """后台运行 Agent 的协程。"""
        info = self.sessions.get(session_id)
        if info is None:
            return
        info.status = "running"
        try:
            results = await run_job_application(
                user_info, companies, parallel=parallel, emitter=emitter
            )
            info.results = results if isinstance(results, dict) else {}
            # 判定整体状态
            if info.results.get("status") == "error":
                info.status = "error"
                info.error = "; ".join(info.results.get("errors", []))
            else:
                info.status = "completed"
            # 推送完成事件
            await self.push_event(
                session_id, {"type": "session_complete", "results": info.results}
            )
        except asyncio.CancelledError:
            info.status = "disconnected"
            raise
        except Exception as e:
            info.status = "error"
            info.error = str(e)
            await self.push_event(
                session_id, {"type": "error", "message": f"Agent 运行出错: {e}"}
            )

    # ------------------------------------------------------------------
    # WebSocket 绑定与事件推送
    # ------------------------------------------------------------------

    async def attach_websocket(self, session_id: str, ws: WebSocket) -> bool:
        """绑定 WebSocket 连接，并冲刷缓存的事件。

        Returns:
            True 表示会话存在并绑定成功，False 表示会话不存在
        """
        info = self.sessions.get(session_id)
        if info is None:
            return False
        info.websocket = ws
        # 冲刷缓存事件
        if info.event_queue:
            for event in list(info.event_queue):
                try:
                    await ws.send_json(event)
                except Exception as e:
                    print(f"[session_manager] 冲刷事件失败: {e}")
                    break
            info.event_queue.clear()
        return True

    async def detach_websocket(self, session_id: str) -> None:
        """解除 WebSocket 绑定，并对未完成的请求 future 设置默认响应。

        设置哨兵值让 emitter 的 _request 返回默认值，Agent 可优雅结束，
        而不是因 CancelledError 直接崩溃。
        """
        info = self.sessions.get(session_id)
        if info is None:
            return
        info.websocket = None
        # 对所有等待中的请求设置哨兵值，emitter 据此返回默认值
        for request_id, future in list(info.pending_requests.items()):
            if not future.done():
                future.set_result(_DISCONNECTED_SENTINEL)
        info.pending_requests.clear()
        # 若 Agent 仍在运行，标记为断开
        if info.status == "running":
            info.status = "disconnected"

    async def push_event(self, session_id: str, event: dict) -> None:
        """推送事件到前端。若 WebSocket 未连接，则缓存到队列等待冲刷。"""
        info = self.sessions.get(session_id)
        if info is None:
            return
        ws = info.websocket
        if ws is not None:
            try:
                await ws.send_json(event)
                return
            except Exception as e:
                print(f"[session_manager] WebSocket 推送失败，转为缓存: {e}")
                info.websocket = None
        # 缓存事件，等待 WebSocket 连接后冲刷
        info.event_queue.append(event)

    # ------------------------------------------------------------------
    # 请求 future 管理
    # ------------------------------------------------------------------

    def register_request(
        self, session_id: str, request_id: str, future: asyncio.Future
    ) -> None:
        info = self.sessions.get(session_id)
        if info is None:
            if not future.done():
                future.cancel()
            return
        info.pending_requests[request_id] = future

    def unregister_request(self, session_id: str, request_id: str) -> None:
        info = self.sessions.get(session_id)
        if info is None:
            return
        info.pending_requests.pop(request_id, None)

    def resolve_request(self, session_id: str, request_id: str, data: Any) -> bool:
        """用户响应到达时，设置 future 的结果。

        Returns:
            True 表示成功解析，False 表示未找到对应请求或请求已处理
        """
        info = self.sessions.get(session_id)
        if info is None:
            return False
        future = info.pending_requests.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(data)
        return True

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> SessionInfo | None:
        return self.sessions.get(session_id)

    def get_session_status(self, session_id: str) -> dict[str, Any]:
        info = self.sessions.get(session_id)
        if info is None:
            return {"session_id": session_id, "status": "not_found"}
        return {
            "session_id": session_id,
            "status": info.status,
            "created_at": info.created_at,
            "parallel": info.parallel,
            "companies": [c.company_name for c in info.companies],
            "results": info.results,
            "error": info.error,
            "pending_requests": list(info.pending_requests.keys()),
        }


# 模块级单例
session_manager = SessionManager()
