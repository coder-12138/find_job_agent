"""公司子 Agent 模块。

每个公司创建一个子 Agent，处理完整的投递流程（搜索官网 → 推荐岗位 → JD 润色 → 填表 → 投递）。
使用 deepagents 框架作为 harness，通过 AgentEventEmitter 接口与用户交互。
"""

import asyncio
import contextvars
import json
from typing import Any
from urllib.parse import urlparse

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
_reviewed_resume_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "company_reviewed_resume", default=None
)
_form_filled_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "company_form_filled", default=False
)
_form_ready_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "company_form_ready", default=False
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


def is_application_form_ready() -> bool:
    return _form_ready_ctx.get()


def mark_application_form_ready(ready: bool = True) -> None:
    _form_ready_ctx.set(ready)


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
        timeout=settings.llm_request_timeout,
        max_retries=settings.llm_max_retries,
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
        company.search_completed = True

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

    error = str(data.get("error") or "").strip()
    if error or data.get("ok") is False:
        diagnostics = data.get("diagnostics") or {}
        resume_characters = diagnostics.get("resume_text_characters", 0)
        message = (
            f"润色失败，已阻止打开空白审核框：{error or '未知错误'}；"
            f"进入润色工具的档案正文为 {resume_characters} 字符"
        )
        company = _company_ctx.get()
        if company:
            company.status = "polish_failed"
            company.error_message = message
        emitter = _emitter_ctx.get()
        if emitter:
            await emitter.emit_progress(
                "polish", message, company.company_name if company else ""
            )
            await emitter.emit_log("error", message)
        return json.dumps(
            {
                "error": error or "润色工具返回失败",
                "diagnostics": diagnostics,
            },
            ensure_ascii=False,
        )

    original = data.get("original", {})
    polished = data.get("polished", {})

    # 确保是 dict 格式
    if isinstance(original, str):
        original = {"content": original}
    if isinstance(polished, str):
        polished = {"content": polished}

    if not isinstance(original, dict) or not isinstance(polished, dict):
        return json.dumps(
            {"error": "润色结果结构无效，已阻止打开审核框"},
            ensure_ascii=False,
        )
    if not original or not polished or not any(
        value not in (None, "", [], {}) for value in polished.values()
    ):
        message = "润色结果为空，已阻止打开空白审核框"
        company = _company_ctx.get()
        if company:
            company.status = "polish_failed"
            company.error_message = message
        emitter = _emitter_ctx.get()
        if emitter:
            await emitter.emit_progress(
                "polish", message, company.company_name if company else ""
            )
            await emitter.emit_log("error", message)
        return json.dumps({"error": message}, ensure_ascii=False)

    emitter = _emitter_ctx.get()
    if not emitter:
        return json.dumps({"error": "无事件发射器", "confirmed": polished}, ensure_ascii=False)

    request_id = generate_request_id()
    confirmed = await emitter.request_resume_review(request_id, original, polished)
    _reviewed_resume_ctx.set(confirmed if isinstance(confirmed, dict) else polished)

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
    """Wait for the user to perform the irreversible final submit manually.

    Returns:
        "confirmed" 或 "cancelled"
    """
    emitter = _emitter_ctx.get()
    company = _company_ctx.get()
    company_name = company.company_name if company else "未知公司"

    if not emitter:
        return "cancelled"
    if not _form_ready_ctx.get() or not _form_filled_ctx.get():
        await emitter.emit_progress(
            "fill",
            "申请表单尚未验证并完成填写，已阻止进入最终提交确认",
            company_name,
        )
        return "cancelled"

    request_id = generate_request_id()
    title = f"最终提交由你完成 - {company_name}"
    message = (
        f"公司: {company_name}\n\n"
        "表单已经自动填写并暂停。请回到系统弹出的受管浏览器窗口，"
        "检查所有字段后，由你亲自点击网站的最终提交按钮。\n"
        "完成后再回到这里确认结果。不要把链接复制到其他浏览器，"
        "其他浏览器不会共享当前登录和表单会话。"
    )
    options = ["我已在受管浏览器完成提交", "暂不提交，结束该公司流程"]

    selected = await emitter.request_confirmation(request_id, title, message, options)

    if selected == options[0]:
        outcome = "outcome_unknown"
        outcome_message = "未观察到可验证的投递回执"
        try:
            from job_application_agent_langchain.browser.automation import BrowserAutomation

            browser = await BrowserAutomation.get_shared()
            learned = await browser.capture_manual_interaction_proposals()
            if learned:
                await emitter.emit_log(
                    "info", f"已记录 {learned} 条不含输入值的交互候选，需审核后才会复用"
                )
            outcome, outcome_message = await browser.inspect_submission_outcome()
        except Exception:
            pass
        if outcome == "submitted":
            _submitted_ctx.set(True)
            if company:
                company.submitted = True
                company.status = "submitted"
            return "confirmed"
        if company:
            company.submitted = False
            company.status = "submission_outcome_unknown"
            company.error_message = outcome_message
        await emitter.emit_progress(
            "submit", f"用户已执行最终提交，但结果尚无法验证：{outcome_message}", company_name
        )
        return "outcome_unknown"
    else:
        if company:
            company.status = "user_skipped"
        return "cancelled"


@tool
async def report_form_filled() -> str:
    """报告表单已填写完成。在调用 take_screenshot_for_review 后、请求投递确认前调用此工具。"""
    if not _form_ready_ctx.get():
        return "FORM_NOT_READY：当前页面尚未验证为所选岗位的申请表单，不能标记填写完成"
    _form_filled_ctx.set(True)
    company = _company_ctx.get()
    if company:
        company.form_filled = True
    return "已标记表单填写完成"


@tool
async def request_user_login(login_url: str) -> str:
    """请求用户在浏览器窗口中完成登录/注册。

    在用户确认岗位后、开始填表前调用此工具。Agent 应先导航到登录页，
    然后调用此工具暂停等待用户在浏览器窗口中自行完成登录（支持扫码、
    短信验证码、账号密码等），用户在 Web UI 点击"已完成登录"后返回。

    Args:
        login_url: 当前登录页 URL

    Returns:
        "logged_in" 表示用户已完成登录
    """
    emitter = _emitter_ctx.get()
    if not emitter:
        return "logged_in"  # 无 emitter 时直接继续

    company = _company_ctx.get()
    company_name = company.company_name if company else ""
    _form_ready_ctx.set(False)
    from job_application_agent_langchain.browser.automation import BrowserAutomation

    browser = await BrowserAutomation.get_shared()
    selected = _selected_positions_ctx.get() or []
    selected_position = selected[0] if selected else {}
    position_url = str(selected_position.get("url") or login_url)
    position_name = str(
        selected_position.get("name") or selected_position.get("title") or ""
    )
    source_list_url = str(selected_position.get("source_list_url") or "")
    current_only = False

    while True:
        try:
            learned = await browser.capture_manual_interaction_proposals()
            if learned:
                await emitter.emit_log(
                    "info",
                    f"已记录 {learned} 条不含输入值的登录/导航候选，需审核后才会复用",
                )
            await emitter.emit_progress(
                "login",
                f"正在恢复已选岗位“{position_name or position_url}”并打开申请表单",
                company_name,
            )
            prepared = await browser.prepare_application_form(
                position_url,
                position_name=position_name,
                source_list_url=source_list_url,
                current_only=current_only,
            )
            if prepared.get("ready"):
                _form_ready_ctx.set(True)
                prefill: dict[str, Any] = {}
                user_info = _user_info_ctx.get()
                if user_info is not None:
                    await emitter.emit_progress(
                        "fill",
                        "已识别申请表单，正在上传一次简历并等待网站解析后主动填写档案字段",
                        company_name,
                    )
                    try:
                        prefill = await browser.prefill_application_form(
                            user_info,
                            reviewed_resume=_reviewed_resume_ctx.get() or {},
                            resume_path=user_info.resume_file_path,
                        )
                    except Exception as exc:
                        prefill = {
                            "kind": "prefill_failed",
                            "filled_fields": [],
                            "skipped_fields": [],
                            "message": str(exc),
                        }
                    filled = prefill.get("filled_fields") or []
                    skipped = prefill.get("skipped_fields") or []
                    evidence = prefill.get("evidence") or {}
                    await emitter.emit_progress(
                        "fill",
                        f"确定性预填完成：已填 {len(filled)} 项"
                        f"（{', '.join(filled) or '无'}）；"
                        f"档案中有值但页面未识别 {len(skipped)} 项"
                        f"（{', '.join(skipped) or '无'}）；"
                        f"当前可见控件 {evidence.get('visible_control_count', 0)} 个",
                        company_name,
                    )
                await emitter.emit_progress(
                    "fill",
                    f"已打开所选岗位申请表单：{prepared.get('url', '')}",
                    company_name,
                )
                return (
                    "logged_in_application_form_ready\nPREFILL_RESULT="
                    + json.dumps(prefill, ensure_ascii=False)
                )
        except Exception as exc:
            prepared = {
                "kind": "navigation_failed",
                "url": browser.page.url,
                "message": str(exc),
                "attempts": [],
            }

        if prepared.get("kind") == "login_required":
            message = (
                f"申请入口确认需要登录。请在当前同一个受管浏览器窗口中完成「{company_name}」"
                "的登录或注册。\n"
                f"当前页面: {prepared.get('url') or login_url}\n"
                "支持扫码、短信验证码、账号密码等任意登录方式。\n"
                "不要复制链接，也不要另开普通浏览器。登录完成后点击下方按钮，"
                "系统将在当前岗位继续打开申请表单。"
            )
            result = await emitter.request_user_login(
                generate_request_id(),
                str(prepared.get("url") or login_url),
                message,
                mode="login",
            )
            if result != "logged_in":
                return result
            current_only = False
            continue

        attempts = prepared.get("attempts") or []
        attempt_summary = "；".join(
            f"{item.get('stage')}={item.get('kind')}"
            for item in attempts[-5:]
            if isinstance(item, dict)
        )
        await emitter.emit_progress(
            "login",
            f"自动恢复暂未进入申请表单：{prepared.get('message', '页面状态未知')}；"
            f"当前页面 {prepared.get('url', '')}；尝试记录 {attempt_summary or '无'}。"
            "受管浏览器将保持打开，任务正在等待你手动调整后重新检测。",
            company_name,
        )
        if prepared.get("kind") == "application_action_pending":
            current_only = True
            retry_message = (
                f"系统已经在所选岗位点击申请入口，并保持当前页面不动：\n"
                f"岗位：{position_name or '名称未知'}\n"
                f"详情：{position_url}\n\n"
                "尚未识别到申请表单，但不会回退岗位列表，也不会再次新开页面。"
                "如果页面稍后出现表单或登录页，点击下方按钮即可接管并继续。"
            )
        else:
            retry_message = (
                f"系统已保存并尝试了岗位详情地址、原岗位列表和岗位名称：\n"
                f"岗位：{position_name or '名称未知'}\n"
                f"详情：{position_url}\n"
                f"列表：{source_list_url or '已从详情地址推导'}\n\n"
                "当前仍未识别到申请表单。受管浏览器和当前任务都会保持打开。"
                "你可以在同一受管窗口中手动进入该岗位申请表单，然后点击下方按钮；"
                "也可以直接点击按钮，让系统再次执行完整恢复。"
            )
        result = await emitter.request_user_login(
            generate_request_id(),
            str(prepared.get("url") or position_url),
            retry_message,
            mode=(
                "application_form_wait"
                if current_only
                else "application_form"
            ),
        )
        if result not in {"logged_in", "ready_for_form_check", "retry"}:
            return result


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
- 投递链接: {company.application_url or '无（需搜索官网）'}
- 来源: {'文档自动发现' if company.source == 'document' else '手动输入'}

## 文件路径：
{file_paths_text}{memory_hint}

## 你的工作流程（严格按顺序执行）：

### 阶段 1: 搜索官网与岗位推荐
1. 调用 emit_progress（phase="search"）通知用户开始搜索
   注意：如果待投递公司信息中已提供「投递链接」（application_url 不为空），则跳过步骤 2 的 search_company_website，直接用 navigate_and_find_positions 导航到该链接。若链接是微信公众号推文（mp.weixin.qq.com），暂时提示无法处理并跳过该公司。
2. 调用 search_company_website 搜索{company.company_name}的{company.recruitment_type}官网
   如果工具返回 SEARCH_ABORTED，说明搜索已超时或网站不可达。不要再次调用搜索工具，
   立即调用 emit_progress 告知用户并结束该公司流程。
3. 调用 navigate_and_find_positions 导航到官网并查找相关岗位
   工具会识别“页面不存在/已迁移/站点错误”等伪成功页面，并自动尝试最多 3 个候选链接。
   如果所有候选都失败并返回 SEARCH_ABORTED，不要再重试或猜测其他链接，结束该公司流程，
   并提示用户在 Web UI 中手动填写确认可访问的招聘官网或岗位列表网址。
   注意：部分公司官网（如小鹏汽车）登录后初始页面没有职位列表，需要点击“即刻投递”等入口按钮。
   navigate_and_find_positions 会自动尝试点击常见入口按钮。若返回信息显示“未找到常见入口按钮”，
   请调用 get_visible_buttons_tool 查看页面所有可点击元素，再调用 click_element_by_text_tool 
   点击合适的入口按钮（如“即刻投递”/“开始找工作”/“查看职位”等）。
   若返回中包含“结构化匹配岗位”，这些岗位已经按期望地区做过硬筛选、按关键词排序：
   直接以它们作为推荐候选，不要再逐个调用 get_position_details，也不要推荐其他地区。
   如果手动点击入口后才出现岗位列表，调用 extract_matching_positions 批量提取。
4. 调用 find_max_positions 查找该公司可投递的最大岗位数
5. 仅当步骤 3 没有返回结构化岗位时，才对少量有潜力的岗位调用 get_position_details 获取详情；
   禁止为了筛选而遍历打开大量岗位详情页。
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
   polish_resume_for_jd 会显示“JD 分析”和“生成润色”两个子步骤并分别超时。
   如果返回 error，禁止再次调用润色工具；通知用户具体错误并结束该公司流程。
14. 调用 request_resume_review 请用户审核润色后的简历
15. 记录用户确认的简历内容，用于后续填表

### 阶段 3.5: 用户登录/注册
15.5. 调用 emit_progress（phase="login"）通知用户需要登录
15.6. 保持当前受管浏览器窗口，不要要求用户复制或另开链接
15.7. 调用 request_user_login(login_url) 请求用户在该受管窗口中完成登录
      - 系统以非 headless 模式启动浏览器，用户可在弹出的浏览器窗口中自行操作
      - 支持扫码、短信验证码、账号密码等任意登录方式
      - 用户可能需要先注册，同样在该浏览器窗口中完成
15.8. request_user_login 会在用户确认后确定性返回所选岗位、点击申请入口并验证表单
15.9. request_user_login 会持续保留受管浏览器并等待重新检测；只有工具返回以 logged_in_application_form_ready 开头的结果才能继续填表
      该工具会在识别表单后确定性地上传一次简历、等待网站解析稳定，并主动预填档案中的基础/教育/工作/项目字段

### 阶段 4: 填写表单
17. 调用 emit_progress（phase="fill"）通知用户开始填表
18. 阅读 request_user_login 返回的 PREFILL_RESULT，然后调用 get_current_page_form 重新扫描网站解析后剩余的表单字段
19. request_user_login 已处理简历上传；禁止再次调用 upload_resume 重复上传
20. 对每个必填字段：
    - 调用 check_field_in_memory 检查记忆中是否有值
    - 如果返回 FIELD_FOUND，使用该值调用 fill_form_field 填写
    - 如果返回 FIELD_MISSING，跳过该字段继续填写下一个（不要阻塞等待用户）
21. 所有可填字段填写完成后，调用 request_missing_fields 批量请求用户补充缺失字段
22. 用用户补充的值调用 fill_form_field 填写之前缺失的字段

### 阶段 5: 人工最终提交
23. 调用 take_screenshot_for_review 截图供用户检查
24. 调用 emit_screenshot 推送截图给用户
25. 调用 report_form_filled 标记表单已填写完成
26. 调用 emit_progress（phase="confirm"）通知用户等待确认
27. 调用 request_delivery_confirmation，等待用户在受管浏览器中亲自检查并点击最终提交
28. 如果返回 "confirmed"，调用 emit_progress（phase="submit"）记录已观察到成功回执；如果返回 "outcome_unknown"，明确报告结果未知并结束，禁止伪造成功；禁止调用 submit_application 自动点击最终提交按钮
29. 如果返回 "cancelled"，结束流程（状态: user_skipped）

## 重要规则：
- 遇到非阻塞通知时使用 notify_user（need_confirmation=False）
- 所有人机交互（岗位选择、简历审核、缺失字段补充、投递确认）必须通过 emitter 工具完成
- 不要使用 ask_user_for_field 或 notify_delivery_warning（这些是旧版阻塞式工具）
- 非必填字段缺失时跳过不填
- 不要张冠李戴，确保字段值与字段含义匹配
- 每完成一个阶段，调用 emit_progress 推送进度
- 如果任何步骤出错，使用 emit_progress 通知用户并尝试继续或结束
- 用户可能在运行中通过 Web UI 发送指导消息，请遵循用户指令调整行为
- 浏览器以非 headless 模式启动，用户可直接在浏览器窗口中操作（登录、扫码等）
- 最终提交按钮只能由用户在受管浏览器窗口中亲自点击，Agent 不得代点
- 未验证为申请表单时，禁止调用 report_form_filled、take_screenshot_for_review 或进入投递确认
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
        request_user_login,
    ]

    # 按名称去重（保留首次出现的工具）
    merged = []
    seen_names: set[str] = set()
    for t in search_tools + form_tools + emitter_tools:
        if t.name not in seen_names:
            merged.append(t)
            seen_names.add(t.name)

    return merged


class SearchPhaseTimeoutError(RuntimeError):
    """Agent 未能在规定时间内完成搜索与岗位推荐阶段。"""


def _parse_structured_positions(navigation_result: str) -> list[dict[str, Any]]:
    """从确定性导航工具结果中取出结构化岗位 JSON。"""
    lines = (navigation_result or "").splitlines()
    for index, line in enumerate(lines):
        if "结构化匹配岗位" not in line or index + 1 >= len(lines):
            continue
        try:
            positions = json.loads(lines[index + 1])
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(positions, list):
            return [item for item in positions if isinstance(item, dict)]
    return []


def _feishu_presearch_url(company: CompanyState) -> str:
    """识别可走确定性飞书招聘预搜索的公司网址。"""
    candidates = [company.application_url, *company.candidate_urls]
    for candidate in candidates:
        try:
            if urlparse(candidate).hostname and (
                urlparse(candidate).hostname or ""
            ).lower().endswith("jobs.feishu.cn"):
                return candidate
        except Exception:
            continue
    # 小鹏当前校招站入口稳定，避免让 LLM 先花数轮重新搜索同一网址。
    if "小鹏" in company.company_name:
        return "https://xiaopeng.jobs.feishu.cn/398875"
    return ""


def _deterministic_presearch_url(company: CompanyState) -> str:
    """识别已有确定性页面适配器的招聘网址。"""
    feishu_url = _feishu_presearch_url(company)
    if feishu_url:
        return feishu_url
    candidates = [company.application_url, *company.candidate_urls]
    for candidate in candidates:
        try:
            host = (urlparse(candidate).hostname or "").lower()
            if host == "careers.oppo.com":
                return candidate
        except Exception:
            continue
    if company.company_name.strip().lower() == "oppo":
        return "https://careers.oppo.com/university/oppo/campus"
    return ""


async def _prefetch_structured_positions(
    company: CompanyState,
    emitter: AgentEventEmitter,
) -> list[dict[str, Any]]:
    """在调用 LLM 前完成受支持站点的入口点击、筛选和岗位提取。"""
    website_url = _deterministic_presearch_url(company)
    if not website_url:
        return []
    from job_application_agent_langchain.agents.search import (
        navigate_and_find_positions,
    )
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    from job_application_agent_langchain.config import Settings

    await emitter.emit_progress(
        "search",
        "正在执行确定性招聘页操作（无需等待模型决定下一步）",
        company.company_name,
    )
    settings = Settings()
    browser = await BrowserAutomation.get_shared(
        headless=settings.browser_headless,
        timeout=settings.browser_timeout,
    )
    async with browser.operation_lock:
        navigation_result = await navigate_and_find_positions.coroutine(
            website_url=website_url,
            job_keywords=company.job_keywords,
            preferred_cities=",".join(company.preferred_cities),
            recruitment_type=company.recruitment_type,
        )
    return _parse_structured_positions(navigation_result)


# 保留原名称，兼容已有测试与调用方。
_prefetch_feishu_positions = _prefetch_structured_positions


async def _invoke_agent_with_search_watchdog(
    agent,
    messages: list,
    company: CompanyState,
    emitter: AgentEventEmitter,
    settings: Settings,
):
    """限制 deepagents 的超大默认循环，并监控搜索阶段是否持续无进展。"""
    invocation = asyncio.create_task(
        agent.ainvoke(
            {"messages": messages},
            config={"recursion_limit": settings.agent_recursion_limit},
        )
    )
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    failure_started_at: float | None = None
    next_heartbeat = 15

    try:
        while True:
            done, _ = await asyncio.wait({invocation}, timeout=0.25)
            if done:
                return await invocation

            # 岗位推荐已记录后，搜索阶段结束；后续 HITL 可以正常等待用户。
            if company.search_completed:
                return await invocation

            elapsed = loop.time() - started_at
            if company.status == "search_failed":
                if failure_started_at is None:
                    failure_started_at = loop.time()
                elif loop.time() - failure_started_at >= 12:
                    raise SearchPhaseTimeoutError(
                        company.error_message or "搜索失败后 Agent 未按要求结束"
                    )

            if elapsed >= settings.search_phase_timeout:
                raise SearchPhaseTimeoutError(
                    f"搜索与岗位推荐阶段超过 {settings.search_phase_timeout} 秒，"
                    "已自动中断，避免 Agent 无限循环"
                )

            if elapsed >= next_heartbeat:
                await emitter.emit_progress(
                    "search",
                    (
                        f"Agent 正在分析搜索结果（已用时 {int(elapsed)} 秒，"
                        f"硬上限 {settings.search_phase_timeout} 秒）"
                    ),
                    company.company_name,
                )
                next_heartbeat += 15
    except BaseException:
        if not invocation.done():
            invocation.cancel()
            try:
                await invocation
            except asyncio.CancelledError:
                pass
        raise


# ============================================================================
# 主入口：运行单个公司的完整投递流程
# ============================================================================

async def run_company_agent(
    user_info: UserInfo,
    company: CompanyState,
    memory: AgentMemory,
    emitter: AgentEventEmitter,
    file_paths: dict[str, str] | None = None,
    message_history: list | None = None,
) -> dict[str, Any]:
    """运行单个公司的完整投递流程。

    Args:
        user_info: 用户信息
        company: 公司状态
        memory: Agent 记忆
        emitter: 事件发射器（用于人机交互）
        file_paths: 文件路径映射 {"resume": "...", "degree_cert": "...", "transcript": "..."}
        message_history: 可选的历史消息列表（LangChain message 对象），
            用于续接/中断重试场景。若提供，会与本次的用户消息一起传入 agent。

    Returns:
        结果 dict: {status, form_filled, submitted, recommended_positions, error, messages}
    """
    # 设置上下文变量
    _emitter_ctx.set(emitter)
    _memory_ctx.set(memory)
    _user_info_ctx.set(user_info)
    _company_ctx.set(company)
    _missing_fields_ctx.set([])
    _file_paths_ctx.set(file_paths or {})
    existing_recommended = list(company.recommended_positions)
    existing_selected = list(company.selected_positions)
    _recommended_positions_ctx.set(existing_recommended)
    _selected_positions_ctx.set(existing_selected)
    _reviewed_resume_ctx.set(None)
    _form_filled_ctx.set(company.form_filled)
    _form_ready_ctx.set(False)
    _submitted_ctx.set(False)
    company.search_completed = bool(existing_recommended or company.search_completed)

    # 合并 file_paths 与 user_info.resume_file_path
    effective_file_paths = dict(file_paths or {})
    if user_info.resume_file_path and "resume" not in effective_file_paths:
        effective_file_paths["resume"] = user_info.resume_file_path
    _file_paths_ctx.set(effective_file_paths)

    company_name = company.company_name

    try:
        await emitter.emit_progress("search", f"开始处理 {company_name} 的投递流程", company_name)

        # 飞书招聘页面的打开、城市勾选和岗位提取不应依赖 LLM 自主决定工具
        # 调用顺序。先确定性执行并直接向用户展示候选，避免搜索阶段超时。
        deterministic_presearch_enabled = bool(_deterministic_presearch_url(company))
        resuming_selection = bool(existing_selected)
        preloaded_positions = (
            (existing_recommended or existing_selected)
            if resuming_selection
            else await _prefetch_structured_positions(company, emitter)
        )
        if deterministic_presearch_enabled and not preloaded_positions:
            error_message = (
                company.error_message
                or "招聘页操作已完成，但没有找到同时符合城市和岗位方向的岗位"
            )
            company.status = "search_failed"
            company.error_message = error_message
            await emitter.emit_progress(
                "search",
                f"确定性筛选结束：{error_message}",
                company_name,
            )
            return {
                "status": "search_failed",
                "form_filled": False,
                "submitted": False,
                "recommended_positions": [],
                "selected_positions": [],
                "error": error_message,
                "agent_type": "deterministic_presearch",
                "final_message": error_message,
                "messages": [],
            }
        if preloaded_positions:
            preloaded_positions = preloaded_positions[:8]
            _recommended_positions_ctx.set(preloaded_positions)
            company.recommended_positions = preloaded_positions
            company.search_completed = True
            await emitter.emit_progress(
                "recommend",
                f"已完成确定性筛选，找到 {len(preloaded_positions)} 个匹配岗位",
                company_name,
            )
            if resuming_selection:
                selected_positions = existing_selected
                await emitter.emit_progress(
                    "recommend",
                    f"已恢复之前选择的岗位：{selected_positions[0].get('name') or selected_positions[0].get('title') or ''}",
                    company_name,
                )
            else:
                selection_result = await request_position_selection.coroutine(
                    json.dumps(preloaded_positions, ensure_ascii=False)
                )
                try:
                    selected_positions = json.loads(selection_result).get(
                        "selected_positions", []
                    )
                except (json.JSONDecodeError, AttributeError):
                    selected_positions = []
            _selected_positions_ctx.set(selected_positions)
            company.selected_positions = selected_positions
            if not selected_positions:
                company.status = "user_skipped"
                return {
                    "status": "user_skipped",
                    "form_filled": False,
                    "submitted": False,
                    "recommended_positions": preloaded_positions,
                    "selected_positions": [],
                    "error": "",
                    "agent_type": "deterministic_presearch",
                    "final_message": "用户未选择岗位",
                    "messages": [],
                }
            company.status = "positions_selected"

        # 创建 Agent
        model = _get_llm()
        tools = get_company_agent_tools()
        system_prompt = _build_system_prompt(user_info, company, effective_file_paths, memory)
        if preloaded_positions:
            system_prompt += (
                "\n\n## 本次已完成的阶段\n"
                "程序已经完成招聘页导航、城市复选框验证、岗位方向筛选、推荐记录和用户岗位选择。"
                "禁止再次调用 search_company_website、navigate_and_find_positions、"
                "find_max_positions、report_recommended_positions 或 request_position_selection。"
                "已选岗位对象中的 jd 字段就是页面提取的完整职位描述；jd 非空时禁止再次打开详情页。"
                "直接从阶段 3 开始：使用该 jd、读取上传简历并润色。"
            )
        agent, agent_type = _create_agent(model, tools, system_prompt)

        # 构建用户消息
        if preloaded_positions:
            user_message = (
                f"「{company_name}」的搜索和岗位选择已由程序确定性完成。\n"
                f"用户已选岗位: {json.dumps(company.selected_positions, ensure_ascii=False)}\n"
                "请勿重复搜索或重新请求选择；直接读取第一个已选岗位 JD，"
                "若岗位对象已有 jd 就直接使用，随后使用已上传简历开始阶段 3 的简历润色。"
            )
        else:
            user_message = (
                f"请开始处理「{company_name}」的{company.recruitment_type}投递流程。\n"
                f"岗位关键词: {company.job_keywords}\n"
                f"期望城市: {','.join(company.preferred_cities) if company.preferred_cities else '不限'}\n"
                f"内推码: {company.referral_code or '无'}\n\n"
                f"请按照工作流程依次执行搜索、推荐、润色、填表、投递。"
            )

        # 构建 messages 列表：续接时包含历史消息
        messages = []
        if message_history:
            messages.extend(message_history)
        messages.append(HumanMessage(content=user_message))

        # 调用 Agent
        settings = Settings()
        result = await _invoke_agent_with_search_watchdog(
            agent,
            messages,
            company,
            emitter,
            settings,
        )

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
            "error": company.error_message,
            "agent_type": agent_type,
            "final_message": final_message[:500] if final_message else "",
            "messages": result.get("messages", []) if result else [],
        }

    except SearchPhaseTimeoutError as e:
        company.status = "search_failed"
        company.error_message = str(e)
        await emitter.emit_progress(
            "search",
            f"搜索已自动中断：{e}",
            company_name,
        )
        return {
            "status": "search_failed",
            "form_filled": _form_filled_ctx.get(),
            "submitted": _submitted_ctx.get(),
            "recommended_positions": _recommended_positions_ctx.get() or [],
            "error": str(e),
            "messages": [],
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
            "messages": [],
        }
