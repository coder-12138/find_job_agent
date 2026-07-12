"""投递流程编排器。

使用公司子 Agent 架构：每家公司创建一个子 Agent 处理完整投递流程。
支持并行和顺序模式，通过 AgentEventEmitter 与用户交互。
"""

import asyncio
from typing import Any

from job_application_agent_langchain.agent_events import AgentEventEmitter, CLIEmitter
from job_application_agent_langchain.agents.company_agent import run_company_agent
from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import CompanyState
from job_application_agent_langchain.memory import load_memory, save_memory, user_info_to_dict
from job_application_agent_langchain.user_info.parser import UserInfo


async def run_job_application(
    user_info: UserInfo,
    companies: list[CompanyState],
    parallel: bool = False,
    emitter: AgentEventEmitter | None = None,
) -> dict[str, Any]:
    """运行简历投递流程。

    为每家公司创建一个公司子 Agent，处理完整的投递流程（搜索→推荐→润色→填表→投递）。
    支持并行和顺序模式。

    Args:
        user_info: 用户信息
        companies: 待投递公司列表
        parallel: 是否并行处理多家公司
        emitter: 事件发射器，None 时使用 CLIEmitter（终端交互）

    Returns:
        各公司的投递结果 dict: {company_name: {status, form_filled, submitted, ...}}
    """
    settings = Settings()
    errors = settings.validate()
    if errors:
        for error in errors:
            print(f"配置错误: {error}")
        return {"status": "error", "errors": errors}

    # 默认使用 CLIEmitter（终端交互）
    if emitter is None:
        emitter = CLIEmitter()

    user_info_dict = user_info_to_dict(user_info)
    memory = load_memory(settings.memory_file_path, user_info_dict)

    # 构建文件路径映射
    file_paths: dict[str, str] = {}
    if user_info.resume_file_path:
        file_paths["resume"] = user_info.resume_file_path

    results: dict[str, Any] = {}

    if parallel and len(companies) > 1:
        # 并行模式：为每家公司创建独立的公司子 Agent
        tasks = [
            run_company_agent(user_info, company, memory, emitter, file_paths)
            for company in companies
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results_list):
            if isinstance(result, Exception):
                results[companies[i].company_name] = {
                    "status": "error",
                    "error": str(result),
                    "form_filled": False,
                    "submitted": False,
                }
            else:
                results[companies[i].company_name] = result
    else:
        # 顺序模式：逐个处理公司
        for company in companies:
            result = await run_company_agent(user_info, company, memory, emitter, file_paths)
            results[company.company_name] = result

    # 保存记忆
    save_memory(memory, settings.memory_file_path)

    # 关闭共享浏览器
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    await BrowserAutomation.close_shared()

    return results
