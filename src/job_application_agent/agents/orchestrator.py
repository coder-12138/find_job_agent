from __future__ import annotations

import asyncio
import os
from typing import Any

from agents import Agent, Runner, RunContextWrapper, handoff, RunConfig
from agents.extensions.models.litellm_provider import LitellmProvider

from job_application_agent.context import AppContext, CompanyState
from job_application_agent.user_info.parser import UserInfo
from job_application_agent.agents.search import create_search_agent
from job_application_agent.agents.form import create_form_agent
from job_application_agent.tools.notify import notify_user, _terminal_print, _get_user_input
from job_application_agent.config import Settings


def _build_instructions(ctx: RunContextWrapper[AppContext], agent: Agent[AppContext]) -> str:
    user_summary = ctx.context.user_info.to_summary()
    companies_info = []
    for i, company in enumerate(ctx.context.companies):
        companies_info.append(
            f"{i+1}. {company.company_name}（{company.recruitment_type}）"
            f"（关键词: {company.job_keywords}, 城市: {','.join(company.preferred_cities)}）"
        )
    companies_text = "\n".join(companies_info) if companies_info else "暂无公司"

    return f"""你是简历自动投递的协调主Agent（Orchestrator）。你负责协调整个投递流程。

## 当前用户信息：
{user_summary}

## 待投递公司列表：
{companies_text}

## 你的工作流程：
对于每个公司，按以下顺序执行：
1. 将任务交接给该公司的 Search Agent，搜索官网并推荐岗位
2. 等待用户选择岗位、注册账号、进入简历创建页面
3. 将任务交接给该公司的 Form Agent，完成表单填写和投递
4. 不同公司之间可以并行处理

## 重要规则：
- 遇到任何问题，使用 notify_user 工具通知用户
- 用户选择不投递某公司时，直接跳过
- 每个公司的投递确认是独立的，用户可以选择对某些公司自动投递，对其他公司手动投递
- 始终尊重用户的决定"""


def create_orchestrator(
    user_info: UserInfo,
    companies: list[CompanyState],
) -> Agent[AppContext]:
    """创建协调主Agent"""
    # 为每个公司创建对应的 Search Agent 和 Form Agent
    all_agents = []
    for company in companies:
        all_agents.append(
            create_search_agent(company.company_name, company.recruitment_type)
        )
        all_agents.append(
            create_form_agent(company.company_name, company.recruitment_type)
        )
    
    return Agent(
        name="Orchestrator",
        instructions=_build_instructions,
        tools=[notify_user],
        handoffs=all_agents,
    )


def _get_run_config(settings: Settings) -> RunConfig:
    """创建 RunConfig，使用 LiteLLM 作为模型提供商"""
    # 确保 LiteLLM 能读取到环境变量
    # LiteLLM 使用 OPENAI_API_BASE (不是 OPENAI_BASE_URL)
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    os.environ.setdefault("OPENAI_API_BASE", settings.openai_base_url)
    
    return RunConfig(
        model=settings.openai_model,
        model_provider=LitellmProvider(),
        tracing_disabled=True,
    )


async def run_job_application(
    user_info: UserInfo,
    companies: list[CompanyState],
    parallel: bool = False,
) -> dict[str, Any]:
    """运行简历投递流程"""
    settings = Settings()
    errors = settings.validate()
    if errors:
        for error in errors:
            print(f"配置错误: {error}")
        return {"status": "error", "errors": errors}
    
    if parallel:
        results = await _run_parallel(user_info, companies, settings)
    else:
        results = await _run_sequential(user_info, companies, settings)
    
    return results


async def _run_sequential(
    user_info: UserInfo,
    companies: list[CompanyState],
    settings: Settings,
) -> dict[str, Any]:
    context = AppContext(
        user_info=user_info,
        companies=companies,
        has_desktop=settings.has_desktop,
    )
    
    recruitment_type = companies[0].recruitment_type if companies else "校招"
    orchestrator = create_orchestrator(user_info, companies)
    run_config = _get_run_config(settings)
    
    try:
        result = await Runner.run(
            orchestrator,
            input=f"请开始{recruitment_type}简历投递流程。按照公司列表依次处理每个公司的搜索、表单填写和投递。",
            context=context,
            max_turns=100,
            run_config=run_config,
        )
        
        results = {}
        for company in context.companies:
            results[company.company_name] = {
                "status": "submitted" if company.submitted else company.status,
                "recommended_positions": company.recommended_positions,
                "selected_positions": company.selected_positions,
                "form_filled": company.form_filled,
                "submitted": company.submitted,
                "error_message": company.error_message,
            }
        
        return results
    finally:
        from job_application_agent.browser.automation import BrowserAutomation
        await BrowserAutomation.close_shared()


async def _process_single_company(
    user_info: UserInfo,
    company: CompanyState,
    settings: Settings,
) -> dict[str, Any]:
    context = AppContext(
        user_info=user_info,
        companies=[company],
        current_company_index=0,
    )
    
    search_agent = create_search_agent(company.company_name, company.recruitment_type)
    form_agent = create_form_agent(company.company_name, company.recruitment_type)
    run_config = _get_run_config(settings)
    
    try:
        search_result = await Runner.run(
            search_agent,
            input=(
                f"请搜索{company.company_name}的{company.recruitment_type}官网，"
                f"查找与'{company.job_keywords}'相关的岗位，"
                f"期望工作城市：{','.join(company.preferred_cities)}。"
                f"内推码：{company.referral_code or '无'}"
            ),
            context=context,
            max_turns=20,
            run_config=run_config,
        )
        company.status = "searched"
    except Exception as e:
        company.status = "search_failed"
        company.error_message = str(e)
        return {
            "company_name": company.company_name,
            "status": "search_failed",
            "error": str(e),
        }
    
    _terminal_print(
        f"{company.company_name} - 岗位搜索完成",
        f"请查看推荐岗位，选择要投递的岗位和志愿顺序，\n"
        f"然后自行注册账号并进入{company.recruitment_type}简历创建页面。",
        "info",
    )
    user_confirm = _get_user_input(
        f"是否已为{company.company_name}选好岗位并进入{company.recruitment_type}简历创建页面？（yes/no）"
    )
    if user_confirm.lower() not in ("yes", "y", "是"):
        company.status = "user_skipped"
        return {
            "company_name": company.company_name,
            "status": "user_skipped",
            "submitted": False,
            "form_filled": False,
        }
    
    try:
        form_result = await Runner.run(
            form_agent,
            input=(
                f"请在{company.company_name}的{company.recruitment_type}简历创建页面填写简历信息。"
            ),
            context=context,
            max_turns=30,
            run_config=run_config,
        )
        company.form_filled = True
        company.status = "form_filled"
    except Exception as e:
        company.status = "form_failed"
        company.error_message = str(e)
        return {
            "company_name": company.company_name,
            "status": "form_failed",
            "error": str(e),
        }
    
    return {
        "company_name": company.company_name,
        "status": company.status,
        "recommended_positions": company.recommended_positions,
        "selected_positions": company.selected_positions,
        "form_filled": company.form_filled,
        "submitted": company.submitted,
        "error_message": company.error_message,
    }


async def _run_parallel(
    user_info: UserInfo,
    companies: list[CompanyState],
    settings: Settings,
) -> dict[str, Any]:
    tasks = []
    for company in companies:
        task = _process_single_company(
            user_info,
            company,
            settings,
        )
        tasks.append(task)
    
    try:
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = {}
        for i, task_result in enumerate(task_results):
            company = companies[i]
            if isinstance(task_result, Exception):
                results[company.company_name] = {
                    "status": "error",
                    "error": str(task_result),
                    "submitted": False,
                    "form_filled": False,
                }
            else:
                results[company.company_name] = task_result
        
        return results
    finally:
        from job_application_agent.browser.automation import BrowserAutomation
        await BrowserAutomation.close_shared()
