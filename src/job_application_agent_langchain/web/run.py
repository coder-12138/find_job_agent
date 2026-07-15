"""Web 服务启动脚本。

用法:
    PYTHONPATH=src python -m job_application_agent_langchain.web.run
"""

import os
import sys

from job_application_agent_langchain.config import Settings


def _check_env() -> None:
    """检查 .env 配置，未配置时给出友好提示并退出。"""
    settings = Settings()
    errors = settings.validate()
    if errors:
        print("\n❌ 配置错误:")
        for e in errors:
            print(f"  - {e}")
        print("\n请在项目根目录的 .env 文件中配置以上项目后重试。")
        print("可参考 .env.example 文件。")
        sys.exit(1)
    print("✅ 配置验证通过")


def main() -> None:
    _check_env()

    settings = Settings()
    if not os.path.exists(settings.personal_info_file_path):
        print(
            f"\n⚠️  个人信息文件不存在: {settings.personal_info_file_path}\n"
            "Web 服务仍会启动，但创建会话时可能无法加载用户信息。\n"
        )

    import uvicorn

    print("🚀 启动 Web 服务: http://0.0.0.0:8000")
    print("   API 文档: http://0.0.0.0:8000/docs")
    uvicorn.run(
        "job_application_agent_langchain.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
