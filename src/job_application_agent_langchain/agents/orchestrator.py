"""投递流程编排器。

使用公司子 Agent 架构：每家公司创建一个子 Agent 处理完整投递流程。
支持并行和顺序模式，通过 AgentEventEmitter 与用户交互。
"""

import asyncio
from typing import Any

from job_application_agent_langchain.agent_events import (
    AgentEventEmitter,
    CLIEmitter,
    generate_request_id,
)
from job_application_agent_langchain.agents.company_agent import run_company_agent
from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import CompanyState
from job_application_agent_langchain.document_parser import (
    DocumentAccessError,
    match_companies,
    read_tencent_document,
)
from job_application_agent_langchain.memory import load_memory, save_memory, user_info_to_dict
from job_application_agent_langchain.user_info.parser import UserInfo


async def run_job_application(
    user_info: UserInfo,
    companies: list[CompanyState],
    parallel: bool = False,
    emitter: AgentEventEmitter | None = None,
    message_history: list | None = None,
) -> dict[str, Any]:
    """运行简历投递流程。

    为每家公司创建一个公司子 Agent，处理完整的投递流程（搜索→推荐→润色→填表→投递）。
    支持并行和顺序模式。

    Args:
        user_info: 用户信息
        companies: 待投递公司列表
        parallel: 是否并行处理多家公司
        emitter: 事件发射器，None 时使用 CLIEmitter（终端交互）
        message_history: 可选的历史消息列表，透传给公司子 Agent 用于续接/中断重试。

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
            run_company_agent(
                user_info, company, memory, emitter, file_paths,
                message_history=message_history,
            )
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
            result = await run_company_agent(
                user_info, company, memory, emitter, file_paths,
                message_history=message_history,
            )
            results[company.company_name] = result

    # 保存记忆
    save_memory(memory, settings.memory_file_path)

    # 关闭共享浏览器
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    await BrowserAutomation.close_shared()

    return results


async def run_from_document(
    doc_url: str,
    user_info: UserInfo,
    job_keyword: str = "",
    industry: str = "",
    city: str = "",
    recruitment_type: str = "校招",
    parallel: bool = False,
    emitter: AgentEventEmitter | None = None,
) -> dict[str, Any]:
    """从腾讯文档读取公司列表并投递。

    流程：
    1. emit_progress(phase="document", message="正在读取文档...")
    2. 调用 read_tencent_document(doc_url, emitter) 读取表格
    3. 调用 match_companies(rows, job_keyword, industry, city) 匹配公司
    4. 若无匹配：emit_log("warning", "未找到匹配公司")，返回 {"status": "no_match"}
    5. emit_progress(phase="document", message=f"找到 {len(matched)} 家匹配公司")
    6. 如果 emitter 不为 None：
       - 调用 emitter.request_position_selection 让用户确认要投递哪些公司
         （复用岗位选择 UI，把公司当"岗位"展示，positions 参数传 [{name: 公司名, ...}]）
       - 根据用户选择过滤公司列表
    7. 将匹配的公司转为 CompanyState 列表（source="document",
       application_url=文档中的链接, recruitment_type=传入的,
       job_keywords=job_keyword, preferred_cities=[city] if city else []）
    8. 调用 run_job_application(user_info, companies, parallel, emitter) 执行投递
    9. 返回结果

    异常处理：捕获 DocumentAccessError，emit_log("error", ...)，
    返回 {"status": "error", "error": str(e)}

    Args:
        doc_url: 腾讯文档 URL
        user_info: 用户信息
        job_keyword: 岗位关键词（可空）
        industry: 行业关键词（可空）
        city: 城市关键词（可空）
        recruitment_type: 投递类型（校招/社招/日常实习/暑期实习（转正实习））
        parallel: 是否并行处理多家公司
        emitter: 事件发射器，None 时使用 CLIEmitter

    Returns:
        投递结果 dict。可能包含 status=error/no_match，或正常投递结果
    """
    # emitter 为 None 时，emit_progress/emit_log 直接跳过；
    # read_tencent_document 在需要登录时会因 emitter 为 None 抛出 DocumentAccessError
    async def _safe_emit_progress(phase: str, message: str) -> None:
        if emitter is not None:
            await emitter.emit_progress(phase, message)

    async def _safe_emit_log(level: str, message: str) -> None:
        if emitter is not None:
            await emitter.emit_log(level, message)

    try:
        # 1. 通知开始读取文档
        await _safe_emit_progress("document", "正在读取文档...")

        # 2. 读取腾讯文档表格
        rows = await read_tencent_document(doc_url, emitter)

        # 3. 匹配公司
        matched = match_companies(rows, job_keyword=job_keyword, industry=industry, city=city)

        # 4. 无匹配处理
        if not matched:
            await _safe_emit_log("warning", "未找到匹配公司")
            return {"status": "no_match"}

        # 5. 通知匹配结果
        await _safe_emit_progress("document", f"找到 {len(matched)} 家匹配公司")

        # 6. 让用户确认要投递哪些公司（复用岗位选择 UI）
        if emitter is not None:
            # 把公司当"岗位"展示
            positions_for_ui = [
                {
                    "name": row.get("_company_name", "") or row.get("公司", ""),
                    "location": row.get("城市", row.get("地点", "")),
                    "url": row.get("_application_url", ""),
                    "reason": "来自腾讯文档",
                }
                for row in matched
            ]
            request_id = generate_request_id()
            selected = await emitter.request_position_selection(request_id, positions_for_ui)

            if not selected:
                await _safe_emit_log("info", "用户未选择任何公司，结束流程")
                return {"status": "no_match"}

            # 根据用户选择过滤公司列表（按公司名匹配）
            selected_names = {
                (s.get("name") or "").strip() for s in selected if s.get("name")
            }
            matched = [
                row for row in matched
                if (row.get("_company_name", "") or "").strip() in selected_names
            ]
            if not matched:
                await _safe_emit_log("warning", "用户选择的公司未在匹配列表中")
                return {"status": "no_match"}

        # 7. 转为 CompanyState 列表
        companies: list[CompanyState] = []
        for row in matched:
            company_name = (row.get("_company_name", "") or "").strip()
            if not company_name:
                # 兜底：使用原始行中可能的公司字段
                company_name = (
                    row.get("公司", "") or row.get("公司名称", "")
                    or row.get("企业", "") or row.get("company", "") or "未知公司"
                ).strip()
            companies.append(
                CompanyState(
                    company_name=company_name,
                    recruitment_type=recruitment_type,
                    job_keywords=job_keyword,
                    preferred_cities=[city] if city else [],
                    application_url=(row.get("_application_url", "") or "").strip(),
                    source="document",
                )
            )

        # 8. 执行投递
        return await run_job_application(user_info, companies, parallel, emitter)

    except DocumentAccessError as e:
        # 文档访问异常（登录失败/反爬/无法提取）
        await _safe_emit_log("error", f"文档访问失败: {e}")
        return {"status": "error", "error": str(e)}
