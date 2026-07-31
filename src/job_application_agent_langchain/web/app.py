"""Unified FastAPI entry: original agent WebUI plus versioned profile core."""

from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from job_application_agent_langchain.api_v2 import router as core_v2_router
from job_application_agent_langchain.api_v2.dependencies import shutdown_browser_coordinators
from job_application_agent_langchain.core import initialize_core_runtime
from job_application_agent_langchain.web.routes import router as legacy_router
from job_application_agent_langchain.web.session_manager import session_manager


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_core_runtime()
    try:
        yield
    finally:
        session_manager.cleanup_temporary_files()
        await shutdown_browser_coordinators()


app = FastAPI(
    title="简历自动投递 Agent",
    description="原投递系统与版本化加密候选人档案的统一入口",
    version="1.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(legacy_router)
app.include_router(core_v2_router)


@app.websocket("/ws/sessions/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    if session_manager.get_session(session_id) is None:
        await ws.send_json({"type": "error", "message": "会话不存在"})
        await ws.close()
        return
    await session_manager.attach_websocket(session_id, ws)
    try:
        while True:
            try:
                message = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "无效的 JSON 消息"})
                continue
            if message.get("type") == "response":
                ok = session_manager.resolve_request(
                    session_id,
                    message.get("request_id", ""),
                    message.get("data", {}),
                )
                if not ok:
                    await ws.send_json({"type": "error", "message": "请求不存在或已处理"})
            elif message.get("type") == "user_message":
                result = session_manager.send_message(session_id, message.get("message", ""))
                await ws.send_json({"type": "message_status", "result": result})
            elif message.get("type") == "interrupt":
                result = session_manager.interrupt_and_restart(
                    session_id, message.get("message", "")
                )
                await ws.send_json({"type": "message_status", "result": result})
            else:
                await ws.send_json({"type": "error", "message": "不支持的消息类型"})
    except WebSocketDisconnect:
        pass
    finally:
        await session_manager.detach_websocket(session_id)


STATIC_DIR = Path(__file__).resolve().parent / "static"
TASK_STATIC_DIR = Path(__file__).resolve().parent / "task_static"


@app.get("/")
async def root() -> FileResponse:
    """The original delivery system is again the primary product shell."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/app")
@app.get("/app/{spa_path:path}")
async def optional_task_app(spa_path: str = "") -> FileResponse:
    """Keep the rebuilt task view as an optional diagnostics surface."""
    del spa_path
    index = TASK_STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=503, detail="任务前端尚未构建")
    return FileResponse(str(index))


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if TASK_STATIC_DIR.is_dir():
    app.mount("/task-assets", StaticFiles(directory=str(TASK_STATIC_DIR)), name="task-assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
