"""文件上传管理。

将上传的文件按类型存储到 data/uploads/<type>/ 目录下，
并提供查询最新文件路径与列出全部上传文件的能力。
"""

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from job_application_agent_langchain.user_info.parser import extract_resume_text
from job_application_agent_langchain.web.schemas import FileUploadResponse

# 项目根目录：web/ -> job_application_agent_langchain/ -> src/ -> workspace/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
UPLOADS_DIR = PROJECT_ROOT / "data" / "uploads"

# 允许的文件类型
ALLOWED_FILE_TYPES = {"resume", "degree_cert", "transcript", "other"}


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _get_latest_file(directory: Path) -> Path | None:
    """获取目录下最新的文件（按修改时间）。"""
    if not directory.exists():
        return None
    files = [p for p in directory.iterdir() if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


async def save_upload_file(file: UploadFile, file_type: str) -> FileUploadResponse:
    """保存上传的文件到 data/uploads/<file_type>/ 目录。

    Args:
        file: FastAPI UploadFile 对象
        file_type: 文件类型（resume / degree_cert / transcript / other）

    Returns:
        FileUploadResponse 包含文件名、类型、保存路径和大小
    """
    if file_type not in ALLOWED_FILE_TYPES:
        raise ValueError(
            f"不支持的文件类型: {file_type}，允许的类型: {sorted(ALLOWED_FILE_TYPES)}"
        )

    target_dir = UPLOADS_DIR / file_type
    _ensure_dir(target_dir)

    # 只保留文件名部分，防止路径穿越
    original_name = file.filename or "upload"
    safe_name = Path(original_name).name
    # 用时间戳前缀避免文件名冲突
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    saved_name = f"{timestamp}_{safe_name}"
    saved_path = target_dir / saved_name

    content = await file.read()
    with open(saved_path, "wb") as f:
        f.write(content)

    # 上传时立即解析一次并写入磁盘缓存。后续会话或 WebUI 重启只需读取缓存，
    # 不再重复打开并解析同一份 PDF/DOCX。
    if file_type == "resume":
        try:
            await asyncio.to_thread(extract_resume_text, str(saved_path))
        except Exception as exc:
            # 文件已经保存成功；解析/缓存异常应在后续流程中报告，而不应伪装成上传失败。
            print(f"[简历] 上传成功，但预解析失败 ({saved_path.name}): {exc}")

    return FileUploadResponse(
        filename=safe_name,
        file_type=file_type,
        saved_path=str(saved_path),
        size=len(content),
    )


def get_file_paths() -> dict[str, str]:
    """返回各文件类型的最新文件路径映射 {file_type: path}。"""
    result: dict[str, str] = {}
    for ftype in ALLOWED_FILE_TYPES:
        latest = _get_latest_file(UPLOADS_DIR / ftype)
        if latest:
            result[ftype] = str(latest)
    return result


def list_uploads() -> list[dict[str, Any]]:
    """列出所有已上传的文件，按类型与修改时间排序。"""
    uploads: list[dict[str, Any]] = []
    if not UPLOADS_DIR.exists():
        return uploads
    for ftype in sorted(ALLOWED_FILE_TYPES):
        fdir = UPLOADS_DIR / ftype
        if not fdir.exists():
            continue
        files = [p for p in fdir.iterdir() if p.is_file()]
        for p in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
            stat = p.stat()
            uploads.append(
                {
                    "file_type": ftype,
                    "filename": p.name,
                    "saved_path": str(p),
                    "size": stat.st_size,
                    "modified_at": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                    ),
                }
            )
    return uploads
