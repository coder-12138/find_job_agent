"""Original multi-agent delivery orchestrator used by the unified WebUI.

Candidate data is supplied by a confirmed profile version. Tencent Docs
ingestion remains intentionally removed from the supported product scope.
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
    message_history: list | None = None,
) -> dict[str, Any]:
    """Run search, recommendation, polish, login and reviewed form filling."""

    settings = Settings()
    errors = settings.validate()
    if errors:
        return {"status": "error", "errors": errors}
    emitter = emitter or CLIEmitter()
    user_info_dict = user_info_to_dict(user_info)
    memory = load_memory(settings.memory_file_path, user_info_dict)
    file_paths = {"resume": user_info.resume_file_path} if user_info.resume_file_path else {}
    results: dict[str, Any] = {}

    if parallel and len(companies) > 1:
        tasks = [
            run_company_agent(
                user_info,
                company,
                memory,
                emitter,
                file_paths,
                message_history=message_history,
            )
            for company in companies
        ]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        for company, result in zip(companies, completed, strict=True):
            results[company.company_name] = (
                {
                    "status": "error",
                    "error": str(result),
                    "form_filled": False,
                    "submitted": False,
                }
                if isinstance(result, Exception)
                else result
            )
    else:
        for company in companies:
            results[company.company_name] = await run_company_agent(
                user_info,
                company,
                memory,
                emitter,
                file_paths,
                message_history=message_history,
            )

    save_memory(memory, settings.memory_file_path)
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    # 保留仍可续接的受管窗口。浏览器只在流程真正结束或用户明确停止任务时关闭；
    # positions_selected/form_filled 表示用户仍可能需要在当前会话中继续导航或核对。
    recoverable_statuses = {"positions_selected", "form_filled", "needs_user_action"}
    keep_browser_open = any(
        isinstance(result, dict) and result.get("status") in recoverable_statuses
        for result in results.values()
    )
    if not keep_browser_open:
        await BrowserAutomation.close_shared()
    return results


async def run_from_document(*_: Any, **__: Any) -> dict[str, Any]:
    """Fail closed for removed Tencent Docs ingestion."""

    return {
        "status": "removed",
        "error": "腾讯文档导入已移除，请在投递任务中直接添加公司和招聘链接。",
    }
