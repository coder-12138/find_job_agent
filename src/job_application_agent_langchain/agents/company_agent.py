"""公司子 Agent 模块。

每个公司创建一个子 Agent，处理完整的投递流程（搜索官网 → 推荐岗位 → JD 润色 → 填表 → 投递）。
使用 deepagents 框架作为 harness，通过 AgentEventEmitter 接口与用户交互。
"""

import contextvars
import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from job_application_agent_langchain.agent_events import AgentEventEmitter, generate_request_id
from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import CompanyState
from job_application_agent_langchain.memory import AgentMemory
from job_application_agent_langchain.user_info.parser import UserInfo

# ============================================================================
# 上下文变量：每个公司子 Agent 运行期间独立的状态
# ============================================================================

_emitter_ctx: contextvars.ContextVar[AgentEventEmitter | None] = contextvars.ContextVar(
    "company_emitter", default=None
)
_memory_ctx: contextvars.ContextVar[AgentMemory | None] = contextvars.ContextVar(
    "company_memory", default=None
)
_user_info_ctx: contextvars.ContextVar[UserInfo | None] = contextvars.ContextVar(
    "company_user_info", default=None
)
_company_ctx: contextvars.ContextVar[CompanyState | None] = contextvars.ContextVar(
    "company_state", default=None
)
_missing_fields_ctx: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "company_missing_fields", default=None
)
_file_paths_ctx: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "company_file_paths", default=None
)
_recommended_positions_ctx: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "company_recommended_positions", default=None
)
_selected_positions_ctx: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "company_selected_positions", default=None
)
_form_filled_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "company_form_filled", default=False
)
_submitted_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "company_submitted", default=False
)


# ============================================================================
# 上下文访问辅助函数（供 form.py 的 check_field_in_memory 等工具调用）
# ============================================================================

def get_company_memory() -> AgentMemory | None:
    """获取当前公司子 Agent 运行上下文中的记忆"""
    return _memory_ctx.get()


def get_company_emitter() -> AgentEventEmitter | None:
    """获取当前公司子 Agent 运行上下文中的事件发射器"""
    return _emitter_ctx.get()


def get_company_user_info() -> UserInfo | None:
    """获取当前公司子 Agent 运行上下文中的用户信息"""
    return _user_info_ctx.get()


def get_company_state() -> CompanyState | None:
    """获取当前公司子 Agent 运行上下文中的公司状态"""
    return _company_ctx.get()


def get_file_paths() -> dict[str, str]:
    """获取当前公司子 Agent 运行上下文中的文件路径映射"""
    return _file_paths_ctx.get() or {}


def record_missing_field(field_name: str, field_label: str = "", reason: str = "") -> None:
    """记录缺失的必填字段，供后续批量询问"""
    fields = _missing_fields_ctx.get()
    if fields is None:
        fields = []
    # 避免重复记录同一字段
    existing_names = {f.get("name") for f in fields}
    if field_name not in existing_names:
        fields.append({
            "name": field_name,
            "label": field_label or field_name,
            "reason": reason,
        })
        _missing_fields_ctx.set(fields)


def get_missing_fields() -> list[dict]:
    """获取已记录的缺失字段列表"""
    return _missing_fields_ctx.get() or []


def clear_missing_fields() -> None:
    """清空缺失字段列表"""
    _missing_fields_ctx.set([])


# ============================================================================
# LLM 与 Agent 创建
# ============================================================================

def _get_llm() -> ChatOpenAI:
    """获取 LLM 实例"""
    settings = Settings()
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=0.3,
    )


def _create_agent(model, tools, system_prompt):
    """创建 deepagents Agent，失败时回退到 create_react_agent"""
    try:
        from deepagents import create_deep_agent

        agent = create_deep_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
        )
        return agent, "deepagents"
    except Exception as e:
        # 回退到 langgraph.prebuilt.create_react_agent
        from langgraph.prebuilt import create_react_agent

        agent = create_react_agent(
            model=model,
            tools=tools,
            prompt=system_prompt,
        )
        return agent, "react_agent"


# ============================================================================
# 基于 Emitter 的人机交互工具（HITL）
# ============================================================================

@tool
async def emit_progress(phase: str, message: str) -> str:
    """向用户推送执行进度。

    Args:
        phase: 阶段名称，可选 search/recommend/polish/fill/confirm/submit
        message: 进度描述消息
    """
    emitter = _emitter_ctx.get()
    company = _company_ctx.get()
    company_name = company.company_name if company else ""
    if emitter:
        await emitter.emit_progress(phase, message, company_name)
    return f"已推送进度: [{phase}] {message}"


@tool
async def emit_screenshot(path: str) -> str:
    """向用户推送截图路径供展示。

    Args:
        path: 截图文件路径
    """
    emitter = _emitter_ctx.get()
    company = _company_ctx.get()
    company_name = company.company_name if company else ""
    if emitter:
        await emitter.emit_screenshot(path, company_name)
    return f"已推送截图: {path}"


@tool
async def report_recommended_positions(positions_json: str) -> str:
    """报告搜索到的推荐岗位列表，存储后供后续岗位选择使用。

    Args:
        positions_json: 推荐岗位列表的 JSON 字符串，每个岗位包含 name/title/location/url/jd/reason 等字段
    """
    try:
        positions = json.loads(positions_json)
    except json.JSONDecodeError:
        return "错误: positions_json 不是有效的 JSON"

    if not isinstance(positions, list):
        return "错误: positions_json 应为列表"

    _recommended_positions_ctx.set(positions)

    company = _company_ctx.get()
    if company:
        company.recommended_positions = positions

    return f"已记录 {len(positions)} 个推荐岗位"


@tool
async def request_position_selection(positions_json: str) -> str:
    """请求用户从推荐岗位中选择要投递的岗位（含志愿顺序）。

    Args:
        positions_json: 推荐岗位列表的 JSON 字符串（与 report_recommended_positions 相同格式）

    Returns:
        选中的岗位列表 JSON 字符串，含 volunteer_order 字段
    """
    try:
        positions = json.loads(positions_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "positions_json 不是有效的 JSON"}, ensure_ascii=False)

    emitter = _emitter_ctx.get()
    if not emitter:
        return json.dumps({"error": "无事件发射器"}, ensure_ascii=False)

    request_id = generate_request_id()
    selected = await emitter.request_position_selection(request_id, positions)

    # 存储选中的岗位
    _selected_positions_ctx.set(selected)
    company = _company_ctx.get()
    if company:
        company.selected_positions = selected

    return json.dumps({"selected_positions": selected}, ensure_ascii=False)


@tool
async def request_resume_review(polished_json: str) -> str:
    """请求用户审核润色后的简历内容。

    Args:
        polished_json: polish_resume_for_jd 工具的返回值 JSON 字符串（含 original 和 polished 字段）

    Returns:
        用户确认/编辑后的简历内容 JSON 字符串
    """
    try:
        data = json.loads(polished_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "polished_json 不是有效的 JSON"}, ensure_ascii=False)

    original = data.get("original", {})
    polished = data.get("polished", {})

    # 确保是 dict 格式
    if isinstance(original, str):
        original = {"content": original}
    if isinstance(polished, str):
        polished = {"content": polished}

    emitter = _emitter_ctx.get()
    if not emitter:
        return json.dumps({"error": "无事件发射器", "confirmed": polished}, ensure_ascii=False)

    request_id = generate_request_id()
    confirmed = await emitter.request_resume_review(request_id, original, polished)

    return json.dumps({"confirmed_content": confirmed}, ensure_ascii=False)


@tool
async def request_missing_fields() -> str:
    """批量请求用户补充填表过程中收集到的所有缺失必填字段。
    无需参数：自动从上下文中读取 check_field_in_memory 记录的缺失字段。

    Returns:
        用户补充的字段值 JSON 字符串 {field_name: value}
    """
    fields = _missing_fields_ctx.get()
    if not fields:
        return json.dumps({"fields": {}, "message": "无缺失字段"}, ensure_ascii=False)

    emitter = _emitter_ctx.get()
    if not emitter:
        return json.dumps({"error": "无事件发射器", "fields": {}}, ensure_ascii=False)

    request_id = generate_request_id()
    user_answers = await emitter.request_missing_fields(request_id, fields)

    # 保存到记忆
    memory = _memory_ctx.get()
    if memory:
        for field_name, value in user_answers.items():
            if value:
                memory.set_field(field_name, value, reason="用户批量补充必填项")

    # 清空缺失字段列表
    clear_missing_fields()

    return json.dumps({"fields": user_answers}, ensure_ascii=False)


@tool
async def request_delivery_confirmation() -> str:
    """请求用户确认是否由 AI 自动执行投递。
    弹出醒目警告，因为部分校招网站一旦投递后无法修改。

    Returns:
        "confirmed" 或 "cancelled"
    """
    emitter = _emitter_ctx.get()
    company = _company_ctx.get()
    company_name = company.company_name if company else "未知公司"

    if not emitter:
        return "cancelled"

    request_id = generate_request_id()
    title = f"⚠️ 重要警告 - {company_name} 投递确认"
    message = (
        f"公司: {company_name}\n\n"
        "⚠️ 重要警告：执行此步，AI agent 将直接自动完成简历投递，"
        "不会再暂停让您检查并确认。"
        "部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，请谨慎选择。"
    )
    options = ["由 AI 自动完成投递", "不由 AI 投递，结束该公司流程"]

    selected = await emitter.request_confirmation(request_id, title, message, options)

    if selected == options[0]:
        _submitted_ctx.set(True)
        if company:
            company.submitted = True
            company.status = "submitted"
        return "confirmed"
    else:
        if company:
            company.status = "user_skipped"
        return "cancelled"


@tool
async def report_form_filled() -> str:
    """报告表单已填写完成。在调用 take_screenshot_for_review 后、请求投递确认前调用此工具。"""
    _form_filled_ctx.set(True)
    company = _company_ctx.get()
    if company:
        company.form_filled = True
    return "已标记表单填写完成"


# ============================================================================
# 系统提示构建
# ============================================================================

def _build_system_prompt(user_info: UserInfo, company: CompanyState, file_paths: dict[str, str], memory: AgentMemory) -> str:
    """构建公司子 Agent 的系统提示"""
    user_summary = user_info.to_summary()

    file_paths_text = ""
    if file_paths:
        lines = []
        for ftype, fpath in file_paths.items():
            lines.append(f"  - {ftype}: {fpath}")
        file_paths_text = "\n".join(lines)
    else:
        file_paths_text = "  （未提供文件路径，简历上传时使用 user_info.resume_file_path）"

    memory_hint = ""
    if memory and hasattr(memory, "learned_fields") and memory.learned_fields:
        memory_hint = "\n\n## 已记录的补充信息（优先使用）：\n"
        for k, v in memory.learned_fields.items():
            memory_hint += f"- {k}: {v}\n"

    return f"""你是负责「{company.company_name}」投递的公司子 Agent。你独立完成该公司的全部投递流程。

## 当前用户信息：
{user_summary}

## 待投递公司信息：
- 公司名称: {company.company_name}
- 投递类型: {company.recruitment_type}
- 岗位关键词: {company.job_keywords}
- 期望工作城市: {','.join(company.preferred_cities) if company.preferred_cities else '不限'}
- 内推码: {company.referral_code or '无'}

## 文件路径：
{file_paths_text}{memory_hint}

## 你的工作流程（严格按顺序执行）：

### 阶段 1: 搜索官网与岗位推荐
1. 调用 emit_progress（phase="search"）通知用户开始搜索
2. 调用 search_company_website 搜索{company.company_name}的{company.recruitment_type}官网
3. 调用 navigate_and_find_positions 导航到官网并查找相关岗位
4. 调用 find_max_positions 查找该公司可投递的最大岗位数
5. 对有潜力的岗位调用 get_position_details 获取详情
6. 根据用户信息（专业、经历、技能）推荐 2n 个岗位（n 为可投递最大数，若未知则推荐 3-5 个）
7. 调用 report_recommended_positions 记录推荐岗位列表
8. 调用 emit_progress（phase="recommend"）通知用户岗位推荐完成

### 阶段 2: 用户选择岗位
9. 调用 request_position_selection 请用户选择岗位（含志愿顺序）
10. 如果用户未选择任何岗位，直接结束（状态: user_skipped）

### 阶段 3: 获取 JD 与简历润色
11. 调用 emit_progress（phase="polish"）通知用户开始润色
12. 对选中的第一个岗位调用 get_position_details 获取完整 JD
13. 将用户简历信息和 JD 传给 polish_resume_for_jd 进行润色
14. 调用 request_resume_review 请用户审核润色后的简历
15. 记录用户确认的简历内容，用于后续填表

### 阶段 4: 填写表单
16. 调用 emit_progress（phase="fill"）通知用户开始填表
17. 调用 get_current_page_form 获取当前页面表单字段
18. 如有简历上传需求，调用 upload_resume 上传简历（使用文件路径）
19. 对每个必填字段：
    - 调用 check_field_in_memory 检查记忆中是否有值
    - 如果返回 FIELD_FOUND，使用该值调用 fill_form_field 填写
    - 如果返回 FIELD_MISSING，跳过该字段继续填写下一个（不要阻塞等待用户）
20. 所有可填字段填写完成后，调用 request_missing_fields 批量请求用户补充缺失字段
21. 用用户补充的值调用 fill_form_field 填写之前缺失的字段

### 阶段 5: 投递确认与提交
22. 调用 take_screenshot_for_review 截图供用户检查
23. 调用 emit_screenshot 推送截图给用户
24. 调用 report_form_filled 标记表单已填写完成
25. 调用 emit_progress（phase="confirm"）通知用户等待确认
26. 调用 request_delivery_confirmation 请求用户确认是否投递
27. 如果返回 "confirmed"，调用 emit_progress（phase="submit"）后调用 submit_application 执行投递
28. 如果返回 "cancelled"，结束流程（状态: user_skipped）

## 重要规则：
- 遇到非阻塞通知时使用 notify_user（need_confirmation=False）
- 所有人机交互（岗位选择、简历审核、缺失字段补充、投递确认）必须通过 emitter 工具完成
- 不要使用 ask_user_for_field 或 notify_delivery_warning（这些是旧版阻塞式工具）
- 非必填字段缺失时跳过不填
- 不要张冠李戴，确保字段值与字段含义匹配
- 每完成一个阶段，调用 emit_progress 推送进度
- 如果任何步骤出错，使用 emit_progress 通知用户并尝试继续或结束
"""


# ============================================================================
# 工具集合并
# ============================================================================

def get_company_agent_tools() -> list:
    """获取公司子 Agent 的完整工具集：搜索工具 + 表单工具 + emitter HITL 工具。
    排除旧版阻塞式 HITL 工具（ask_user_for_field, notify_delivery_warning, ask_about_resume_parser）。
    对工具按名称去重（notify_user 在 search 和 form 中都有）。
    """
    from job_application_agent_langchain.agents.search import get_search_tools
    from job_application_agent_langchain.agents.form import get_form_tools

    # 搜索工具（含 notify_user 非阻塞通知）
    search_tools = get_search_tools()

    # 表单工具，排除阻塞式 HITL 工具
    blocking_tools = {"ask_user_for_field", "notify_delivery_warning", "ask_about_resume_parser"}
    form_tools = [t for t in get_form_tools() if t.name not in blocking_tools]

    # Emitter HITL 工具
    emitter_tools = [
        emit_progress,
        emit_screenshot,
        report_recommended_positions,
        request_position_selection,
        request_resume_review,
        request_missing_fields,
        request_delivery_confirmation,
        report_form_filled,
    ]

    # 按名称去重（保留首次出现的工具）
    merged = []
    seen_names: set[str] = set()
    for t in search_tools + form_tools + emitter_tools:
        if t.name not in seen_names:
            merged.append(t)
            seen_names.add(t.name)

    return merged


# ============================================================================
# 主入口：运行单个公司的完整投递流程
# ============================================================================

async def run_company_agent(
    user_info: UserInfo,
    company: CompanyState,
    memory: AgentMemory,
    emitter: AgentEventEmitter,
    file_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    """运行单个公司的完整投递流程。

    Args:
        user_info: 用户信息
        company: 公司状态
        memory: Agent 记忆
        emitter: 事件发射器（用于人机交互）
        file_paths: 文件路径映射 {"resume": "...", "degree_cert": "...", "transcript": "..."}

    Returns:
        结果 dict: {status, form_filled, submitted, recommended_positions, error}
    """
    # 设置上下文变量
    _emitter_ctx.set(emitter)
    _memory_ctx.set(memory)
    _user_info_ctx.set(user_info)
    _company_ctx.set(company)
    _missing_fields_ctx.set([])
    _file_paths_ctx.set(file_paths or {})
    _recommended_positions_ctx.set([])
    _selected_positions_ctx.set([])
    _form_filled_ctx.set(False)
    _submitted_ctx.set(False)

    # 合并 file_paths 与 user_info.resume_file_path
    effective_file_paths = dict(file_paths or {})
    if user_info.resume_file_path and "resume" not in effective_file_paths:
        effective_file_paths["resume"] = user_info.resume_file_path
    _file_paths_ctx.set(effective_file_paths)

    company_name = company.company_name

    try:
        await emitter.emit_progress("search", f"开始处理 {company_name} 的投递流程", company_name)

        # 创建 Agent
        model = _get_llm()
        tools = get_company_agent_tools()
        system_prompt = _build_system_prompt(user_info, company, effective_file_paths, memory)
        agent, agent_type = _create_agent(model, tools, system_prompt)

        # 构建用户消息
        user_message = (
            f"请开始处理「{company_name}」的{company.recruitment_type}投递流程。\n"
            f"岗位关键词: {company.job_keywords}\n"
            f"期望城市: {','.join(company.preferred_cities) if company.preferred_cities else '不限'}\n"
            f"内推码: {company.referral_code or '无'}\n\n"
            f"请按照工作流程依次执行搜索、推荐、润色、填表、投递。"
        )

        # 调用 Agent
        result = await agent.ainvoke({
            "messages": [HumanMessage(content=user_message)],
        })

        # 从上下文中提取结果
        recommended = _recommended_positions_ctx.get() or []
        selected = _selected_positions_ctx.get() or []
        form_filled = _form_filled_ctx.get()
        submitted = _submitted_ctx.get()

        # 更新公司状态
        company.recommended_positions = recommended
        company.selected_positions = selected
        company.form_filled = form_filled
        company.submitted = submitted
        if submitted:
            company.status = "submitted"
        elif form_filled:
            company.status = "form_filled"
        elif selected:
            company.status = "positions_selected"
        elif company.status == "pending":
            company.status = "completed"

        # 尝试从最终消息提取额外信息
        final_message = ""
        if result and "messages" in result and result["messages"]:
            last_msg = result["messages"][-1]
            final_message = getattr(last_msg, "content", str(last_msg))

        return {
            "status": company.status,
            "form_filled": form_filled,
            "submitted": submitted,
            "recommended_positions": recommended,
            "selected_positions": selected,
            "error": "",
            "agent_type": agent_type,
            "final_message": final_message[:500] if final_message else "",
        }

    except Exception as e:
        company.status = "error"
        company.error_message = str(e)
        return {
            "status": "error",
            "form_filled": _form_filled_ctx.get(),
            "submitted": _submitted_ctx.get(),
            "recommended_positions": _recommended_positions_ctx.get() or [],
            "error": str(e),
        }
