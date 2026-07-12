from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import AppContext, CompanyState
from job_application_agent_langchain.memory import load_memory, save_memory, user_info_to_dict
from job_application_agent_langchain.user_info.parser import UserInfo, load_user_info
from job_application_agent_langchain.agents.search import get_search_tools
from job_application_agent_langchain.agents.form import get_form_tools
from job_application_agent_langchain.tools.notify import notify_user


class AgentState(dict):
    """LangGraph 状态定义"""

    messages: list
    company_index: int
    company_status: str
    current_phase: str
    user_info: UserInfo
    companies: list[CompanyState]
    memory: Any
    memory_file_path: str
    results: dict[str, Any]


def _get_llm():
    """获取 LLM 实例"""
    settings = Settings()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.3,
    )


def _build_system_prompt(user_info: UserInfo, companies: list[CompanyState]) -> str:
    """构建系统提示"""
    user_summary = user_info.to_summary()
    companies_info = []
    for i, company in enumerate(companies):
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
1. 调用 Search Agent，搜索官网并推荐岗位
2. 等待用户选择岗位、注册账号、进入简历创建页面
3. 调用 Form Agent，完成表单填写和投递
4. 不同公司之间可以并行处理

## 重要规则：
- 遇到任何问题，使用 notify_user 工具通知用户
- 用户选择不投递某公司时，直接跳过
- 每个公司的投递确认是独立的
- 始终尊重用户的决定"""


def orchestrator_node(state: AgentState) -> AgentState:
    """Orchestrator Node: 主协调节点，决定下一步路由"""
    messages = state.get("messages", [])
    companies = state.get("companies", [])
    company_index = state.get("company_index", 0)
    current_phase = state.get("current_phase", "start")

    if company_index >= len(companies):
        return {**state, "current_phase": "end"}

    company = companies[company_index]

    if current_phase == "start":
        return {**state, "current_phase": "search"}
    elif current_phase == "search_complete":
        return {**state, "current_phase": "wait_user_register"}
    elif current_phase == "user_ready":
        return {**state, "current_phase": "form"}
    elif current_phase == "form_complete":
        return {**state, "current_phase": "delivery_confirm"}
    elif current_phase == "delivery_done":
        next_index = company_index + 1
        return {
            **state,
            "company_index": next_index,
            "current_phase": "start" if next_index < len(companies) else "end",
        }
    elif current_phase == "company_skipped":
        next_index = company_index + 1
        return {
            **state,
            "company_index": next_index,
            "current_phase": "start" if next_index < len(companies) else "end",
        }

    return state


def router_node(state: AgentState) -> Literal["search", "form", "human_in_loop", "end"]:
    """Router Node: 根据当前状态路由到目标节点"""
    current_phase = state.get("current_phase", "start")

    if current_phase == "search":
        return "search"
    elif current_phase in ("wait_user_register", "delivery_confirm"):
        return "human_in_loop"
    elif current_phase == "form":
        return "form"
    elif current_phase in ("end", "company_skipped"):
        return "end"

    return "end"


def search_node(state: AgentState) -> AgentState:
    """Search Agent Node: 搜索公司官网并推荐岗位"""
    companies = state.get("companies", [])
    company_index = state.get("company_index", 0)
    user_info = state.get("user_info", UserInfo())

    if company_index >= len(companies):
        return {**state, "current_phase": "end"}

    company = companies[company_index]

    llm = _get_llm()
    tools = get_search_tools()
    llm_with_tools = llm.bind_tools(tools)

    system_prompt = _build_system_prompt(user_info, companies)
    search_prompt = f"""请搜索{company.company_name}的{company.recruitment_type}官网，
查找与'{company.job_keywords}'相关的岗位，
期望工作城市：{','.join(company.preferred_cities)}。
内推码：{company.referral_code or '无'}

请按以下步骤执行：
1. 使用 search_company_website 搜索官网
2. 使用 navigate_and_find_positions 导航并查找岗位
3. 使用 find_max_positions 查找可投递最大岗位数
4. 使用 get_position_details 获取岗位详情
5. 返回推荐岗位列表（每个岗位包含名称、地点、JD、推荐理由）

完成后报告搜索结果。"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=search_prompt),
    ]

    response = llm_with_tools.invoke(messages)

    new_messages = state.get("messages", []) + [response]

    notify_user.invoke({
        "title": f"{company.company_name} - 岗位搜索完成",
        "message": f"请查看推荐岗位，选择要投递的岗位和志愿顺序，\n"
                   f"然后自行注册账号并进入{company.recruitment_type}简历创建页面。",
        "level": "info",
    })

    return {
        **state,
        "messages": new_messages,
        "current_phase": "search_complete",
    }


def form_node(state: AgentState) -> AgentState:
    """Form Agent Node: 填写表单并处理投递"""
    companies = state.get("companies", [])
    company_index = state.get("company_index", 0)
    user_info = state.get("user_info", UserInfo())
    memory = state.get("memory")
    memory_file_path = state.get("memory_file_path", "")

    if company_index >= len(companies):
        return {**state, "current_phase": "end"}

    company = companies[company_index]

    llm = _get_llm()
    tools = get_form_tools()
    llm_with_tools = llm.bind_tools(tools)

    system_prompt = _build_system_prompt(user_info, companies)

    memory_hint = ""
    if memory and hasattr(memory, "learned_fields") and memory.learned_fields:
        memory_hint = "\n\n## 已记录的补充信息（优先使用）：\n"
        for k, v in memory.learned_fields.items():
            memory_hint += f"- {k}: {v}\n"

    form_prompt = f"""请在{company.company_name}的{company.recruitment_type}简历创建页面填写简历信息。

请按以下步骤执行：
1. 使用 get_current_page_form 获取当前页面表单字段
2. 使用 upload_resume 上传简历附件
3. 使用 ask_about_resume_parser 询问是否使用简历解析器
4. 对于每个必填字段：
   - 先使用 check_field_in_memory 检查记忆
   - 如果记忆中有值，直接使用 fill_form_field 填写
   - 如果记忆中无值，check_field_in_memory 会自动询问用户并记录
5. 使用 fill_form_field 填写所有字段
6. 使用 take_screenshot_for_review 截图供用户检查
7. 完成后报告表单填写结果

## 用户信息摘要：
{user_info.to_summary()}{memory_hint}

重要提醒：
- 必填字段缺失时，使用 check_field_in_memory 工具，它会自动处理询问和记忆
- 非必填字段缺失时跳过不填
- 不要张冠李戴"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=form_prompt),
    ]

    response = llm_with_tools.invoke(messages)

    new_messages = state.get("messages", []) + [response]

    return {
        **state,
        "messages": new_messages,
        "current_phase": "form_complete",
    }


def human_in_loop_node(state: AgentState) -> AgentState:
    """Human-in-the-loop Node: 暂停等待用户输入"""
    companies = state.get("companies", [])
    company_index = state.get("company_index", 0)
    current_phase = state.get("current_phase", "")

    if company_index >= len(companies):
        return {**state, "current_phase": "end"}

    company = companies[company_index]

    if current_phase == "wait_user_register":
        result = notify_user.invoke({
            "title": f"{company.company_name} - 等待用户操作",
            "message": f"请查看推荐岗位，选择要投递的岗位和志愿顺序，\n"
                       f"然后自行注册账号并进入{company.recruitment_type}简历创建页面。",
            "level": "info",
            "need_confirmation": True,
            "confirmation_prompt": f"是否已为{company.company_name}选好岗位并进入简历创建页面？（yes/no）",
        })

        if "yes" in result.lower() or "y" in result.lower() or "是" in result:
            return {**state, "current_phase": "user_ready"}
        else:
            return {**state, "current_phase": "company_skipped"}

    elif current_phase == "delivery_confirm":
        result = notify_user.invoke({
            "title": f"⚠️ 重要警告 - {company.company_name} 投递确认",
            "message": (
                f"公司: {company.company_name}\n\n"
                "⚠️ 重要警告：执行此步，AI agent将直接自动完成简历投递，"
                "不会再暂停让您检查并确认，"
                "部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，"
                "请谨慎选择\n\n"
                "请选择：\n"
                "  输入 yes - 由AI自动完成投递\n"
                "  输入 no  - 不由AI投递，结束该公司的流程"
            ),
            "level": "warning",
            "need_confirmation": True,
            "confirmation_prompt": "是否由AI进行投递？（yes/no）",
        })

        if "yes" in result.lower() or "y" in result.lower() or "是" in result:
            companies[company_index].submitted = True
            companies[company_index].status = "submitted"
            return {**state, "companies": companies, "current_phase": "delivery_done"}
        else:
            companies[company_index].status = "user_skipped"
            return {**state, "companies": companies, "current_phase": "company_skipped"}

    return state


def create_workflow() -> StateGraph:
    """创建 LangGraph 工作流"""
    workflow = StateGraph(AgentState)

    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("search", search_node)
    workflow.add_node("form", form_node)
    workflow.add_node("human_in_loop", human_in_loop_node)

    workflow.set_entry_point("orchestrator")

    workflow.add_conditional_edges(
        "orchestrator",
        router_node,
        {
            "search": "search",
            "form": "form",
            "human_in_loop": "human_in_loop",
            "end": END,
        },
    )

    workflow.add_edge("search", "orchestrator")
    workflow.add_edge("form", "orchestrator")
    workflow.add_edge("human_in_loop", "orchestrator")

    return workflow.compile(checkpointer=MemorySaver())


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

    user_info_dict = user_info_to_dict(user_info)
    memory = load_memory(settings.memory_file_path, user_info_dict)

    if parallel and len(companies) > 1:
        import asyncio
        tasks = []
        for i, company in enumerate(companies):
            task = _run_single_company(user_info, company, memory, settings.memory_file_path, i)
            tasks.append(task)
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        results = {}
        for i, result in enumerate(results_list):
            if isinstance(result, Exception):
                results[companies[i].company_name] = {
                    "status": "error",
                    "error": str(result),
                }
            else:
                results[companies[i].company_name] = result
    else:
        results = {}
        for i, company in enumerate(companies):
            result = await _run_single_company(user_info, company, memory, settings.memory_file_path, i)
            results[company.company_name] = result

    save_memory(memory, settings.memory_file_path)

    from job_application_agent_langchain.browser.automation import BrowserAutomation
    await BrowserAutomation.close_shared()

    return results


async def _run_single_company(
    user_info: UserInfo,
    company: CompanyState,
    memory,
    memory_file_path: str,
    thread_id: int = 0,
) -> dict[str, Any]:
    """运行单个公司的投递流程"""
    workflow = create_workflow()

    initial_state = AgentState(
        messages=[],
        company_index=0,
        company_status="pending",
        current_phase="start",
        user_info=user_info,
        companies=[company],
        memory=memory,
        memory_file_path=memory_file_path,
        results={},
    )

    config = {"configurable": {"thread_id": f"company_{thread_id}"}}

    try:
        final_state = None
        for event in workflow.stream(initial_state, config):
            final_state = event

        if final_state:
            final_company = final_state.get("companies", [company])[0]
            return {
                "status": final_company.status,
                "form_filled": final_company.form_filled,
                "submitted": final_company.submitted,
                "recommended_positions": final_company.recommended_positions,
                "selected_positions": final_company.selected_positions,
                "error_message": final_company.error_message,
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "form_filled": False,
            "submitted": False,
        }

    return {
        "status": company.status,
        "form_filled": company.form_filled,
        "submitted": company.submitted,
    }
