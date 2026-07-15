"""FastAPI 应用主入口。

提供 REST API 与 WebSocket 端点，前端可通过 WebSocket 实时接收 Agent 事件。
"""

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from job_application_agent_langchain.web.routes import router
from job_application_agent_langchain.web.session_manager import session_manager

app = FastAPI(
    title="简历自动投递 Agent Web API",
    description="提供 Web UI 后端：REST API + WebSocket 实时事件推送",
    version="0.1.0",
)

# CORS：开发环境允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 REST 路由
app.include_router(router)


# ----------------------------------------------------------------------
# WebSocket 端点
# ----------------------------------------------------------------------

@app.websocket("/ws/sessions/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str) -> None:
    """WebSocket 连接：推送事件、接收用户响应。

    客户端 -> 服务端消息格式：
        {"type": "response", "request_id": "...", "data": {...}}
    """
    await ws.accept()
    info = session_manager.get_session(session_id)
    if info is None:
        await ws.send_json({"type": "error", "message": "会话不存在"})
        await ws.close()
        return

    # 绑定 WebSocket，冲刷缓存事件
    await session_manager.attach_websocket(session_id, ws)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "无效的 JSON 消息"})
                continue

            if msg.get("type") == "response":
                request_id = msg.get("request_id", "")
                data = msg.get("data", {})
                ok = session_manager.resolve_request(session_id, request_id, data)
                if not ok:
                    await ws.send_json(
                        {
                            "type": "error",
                            "message": f"未找到请求 {request_id} 或请求已处理",
                        }
                    )
            elif msg.get("type") == "user_message":
                # 用户在 Agent 运行任意阶段发送文本消息干预
                text = msg.get("message", "")
                result = session_manager.send_message(session_id, text)
                await ws.send_json({"type": "message_status", "result": result})
            elif msg.get("type") == "interrupt":
                # 中断当前 Agent 运行并以新消息重启
                text = msg.get("message", "")
                result = session_manager.interrupt_and_restart(session_id, text)
                await ws.send_json({"type": "message_status", "result": result})
            else:
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"不支持的消息类型: {msg.get('type')}",
                    }
                )
    except WebSocketDisconnect:
        print(f"[ws] 客户端断开连接: session={session_id}")
    except Exception as e:
        print(f"[ws] 连接异常: {e}")
    finally:
        await session_manager.detach_websocket(session_id)


# ----------------------------------------------------------------------
# 静态文件挂载（前端资源，若存在）
# ----------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
async def root():
    """根路由：返回前端单页应用入口。"""
    return FileResponse(str(STATIC_DIR / "index.html"))


if STATIC_DIR.exists() and STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
