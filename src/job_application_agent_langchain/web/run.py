"""Web 服务启动脚本。

用法:
    PYTHONPATH=src python -m job_application_agent_langchain.web.run
"""

import os
from job_application_agent_langchain.config import Settings


def main() -> None:
    settings = Settings()
    print("ℹ️  Agent API 配置请在 Web UI 左栏「Agent 连接」中输入并验证。")
    if not os.path.exists(settings.personal_info_file_path):
        print(
            f"\n⚠️  个人信息文件不存在: {settings.personal_info_file_path}\n"
            "Web 服务仍会启动，但创建会话时可能无法加载用户信息。\n"
        )

    import uvicorn

    print("🚀 启动 Web 服务: http://127.0.0.1:8000")
    print("   任务前端: http://127.0.0.1:8000/app")
    print("   API 文档: http://127.0.0.1:8000/docs")
    uvicorn.run(
        "job_application_agent_langchain.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
