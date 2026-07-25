from langchain_core.tools import tool

from job_application_agent_langchain.tools.notify import notify_user, notify_delivery_warning, ask_user_for_field
from job_application_agent_langchain.utils import sanitize_agent_name


async def _get_browser():
    from job_application_agent_langchain.browser.automation import BrowserAutomation
    from job_application_agent_langchain.config import Settings

    settings = Settings()
    return await BrowserAutomation.get_shared(
        headless=settings.browser_headless,
        timeout=settings.browser_timeout,
    )


@tool
async def upload_resume(
    file_input_selector: str = 'input[type="file"]',
    resume_path: str = "",
) -> str:
    """上传简历附件到当前页面。

    Args:
        file_input_selector: 文件上传input元素的CSS选择器
        resume_path: 简历文件路径
    """
    try:
        browser = await _get_browser()
        if not resume_path:
            return "简历文件路径未配置，请在.env中设置RESUME_FILE_PATH"

        success = await browser.upload_file(file_input_selector, resume_path)
        if success:
            return f"简历上传成功: {resume_path}"
        return "简历上传失败"
    except Exception as e:
        return f"上传简历时出错: {e}"


@tool
def ask_about_resume_parser() -> str:
    """询问用户是否使用网站自带的简历解析器。"""
    result = notify_user.invoke({
        "title": "简历解析器选择",
        "message": "当前网站可能提供简历解析功能。是否使用网站自带的简历解析器？\n\n"
        "选择 yes: 使用解析器解析简历，然后自动修正错误和补充缺失\n"
        "选择 no: 不使用解析器，直接手动填写所有字段",
        "level": "info",
        "need_confirmation": True,
        "confirmation_prompt": "是否使用简历解析器？（yes/no）",
    })

    if "yes" in result.lower() or "y" in result.lower():
        return "用户选择使用简历解析器"
    return "用户选择不使用简历解析器"


@tool
async def analyze_parsed_resume() -> str:
    """分析网站解析后的简历内容，与用户信息对比，识别错误和缺失项。"""
    try:
        browser = await _get_browser()
        page_text = await browser.get_page_text()

        return (
            f"页面当前内容:\n{page_text[:3000]}\n\n"
            "请对比页面解析内容与用户实际信息，识别以下问题：\n"
            "1. 解析错误的内容（与用户信息不一致）\n"
            "2. 缺失的字段（用户有但页面未填）\n"
            "3. 多余的内容（页面有但用户未提供）\n\n"
            "然后使用表单填写工具修正错误和补充缺失。"
        )
    except Exception as e:
        return f"分析失败: {e}"


@tool
async def fill_form_field(
    selector: str,
    value: str,
    field_type: str = "text",
) -> str:
    """填写表单中的单个字段。

    Args:
        selector: CSS选择器
        value: 要填写的值
        field_type: 字段类型，可选 text/select/radio/checkbox/date/textarea，默认 text
    """
    try:
        browser = await _get_browser()

        if field_type == "text":
            success = await browser.fill_text(selector, value)
        elif field_type == "textarea":
            success = await browser.fill_text(selector, value)
        elif field_type == "select":
            success = await browser.select_option(selector, label=value)
        elif field_type == "radio":
            success = await browser.click_radio(selector, value)
        elif field_type == "checkbox":
            success = await browser.click_checkbox(selector)
        elif field_type == "date":
            parts = value.split("-")
            year = parts[0] if len(parts) > 0 else ""
            month = parts[1] if len(parts) > 1 else ""
            day = parts[2] if len(parts) > 2 else ""
            success = await browser.select_date_from_calendar(selector, year, month, day)
        else:
            success = await browser.fill_text(selector, value)

        return f"字段填写{'成功' if success else '失败'}: {selector} = {value} (类型: {field_type})"
    except Exception as e:
        return f"填写字段时出错: {e}"


@tool
async def get_current_page_form() -> str:
    """获取当前页面的所有表单字段信息，用于分析需要填写哪些内容。"""
    try:
        browser = await _get_browser()
        fields = await browser.get_form_fields()
        if not fields:
            return "当前页面未找到表单字段"

        result_lines = ["当前页面表单字段:"]
        for i, field in enumerate(fields):
            info = f"{i+1}. 类型: {field.get('type', 'unknown')}"
            if field.get("name"):
                info += f", name: {field['name']}"
            if field.get("label"):
                info += f", label: {field['label']}"
            if field.get("placeholder"):
                info += f", placeholder: {field['placeholder']}"
            if field.get("options"):
                info += f", 选项: {field['options']}"
            info += f", 选择器: {field.get('selector', '')}"
            result_lines.append(info)

        return "\n".join(result_lines)
    except Exception as e:
        return f"获取表单信息失败: {e}"


@tool
async def submit_application(
    submit_button_selector: str = 'button:has-text("投递"), button:has-text("提交"), button:has-text("申请")',
) -> str:
    """执行投递操作，点击提交/投递按钮。

    Args:
        submit_button_selector: 提交按钮的CSS选择器
    """
    try:
        browser = await _get_browser()
        success = await browser.click_button(submit_button_selector)
        if success:
            return "投递操作已执行"
        return "投递按钮点击失败，可能未找到按钮"
    except Exception as e:
        return f"投递时出错: {e}"


@tool
async def take_screenshot_for_review() -> str:
    """截取当前页面截图，供用户检查。"""
    try:
        browser = await _get_browser()
        screenshot_path = await browser.take_screenshot()
        return f"截图已保存到: {screenshot_path}"
    except Exception as e:
        return f"截图失败: {e}"


@tool
async def check_field_in_memory(field_name: str, field_label: str = "") -> str:
    """检查某个字段是否已在记忆中。非阻塞式：如果记忆中没有，记录为缺失字段并返回 FIELD_MISSING，
    由公司子 Agent 在填表完成后批量询问用户（通过 request_missing_fields 工具）。

    Args:
        field_name: 字段名（内部标识）
        field_label: 字段显示名称
    """
    from job_application_agent_langchain.agents.company_agent import (
        get_company_memory,
        record_missing_field,
    )

    memory = get_company_memory()
    if memory is not None:
        value = memory.get_field(field_name)
        if value is not None:
            return f"FIELD_FOUND|{field_name}|{value}"
        # 非阻塞：记录缺失字段，不询问用户
        record_missing_field(field_name, field_label, "该字段为必填项，但个人信息文档中未提供")
        return f"FIELD_MISSING|{field_name}|已记录，将在填表完成后批量询问"

    # 回退：无公司子 Agent 上下文时，从全局记忆加载
    from job_application_agent_langchain.memory import load_memory
    from job_application_agent_langchain.config import Settings
    from job_application_agent_langchain.user_info.parser import load_user_info
    from job_application_agent_langchain.memory import user_info_to_dict

    settings = Settings()
    user_info = load_user_info(settings.personal_info_file_path, settings.resume_file_path)
    user_info_dict = user_info_to_dict(user_info)
    memory = load_memory(settings.memory_file_path, user_info_dict)

    value = memory.get_field(field_name)
    if value is not None:
        return f"FIELD_FOUND|{field_name}|{value}"

    return f"FIELD_MISSING|{field_name}|无公司子 Agent 上下文，无法批量询问"


@tool
async def polish_resume_for_jd(jd: str, resume_content: str) -> str:
    """根据岗位 JD 自适应润色简历内容（LLM 动态润色）。

    基于当前上下文中的用户信息（user_info），结合 JD 进行三步处理：
    1) LLM 分析 JD 关键要求；2) 程序化匹配用户简历中相关内容；3) LLM 生成针对性润色。
    润色只改写/重排/强调已有内容，绝不编造。结果交由 request_resume_review 供用户审核。

    Args:
        jd: 目标岗位的 JD（职位描述）文本
        resume_content: 原始简历内容（JSON 字符串或文本），作为额外上下文补充；
            主要信息来源仍为上下文中的 user_info

    Returns:
        JSON 字符串，包含 original（dict）、polished（dict）字段，
        各含 self_introduction、project_highlights、skill_highlights、
        work_highlights、summary。出错时附带 note/error 字段。
    """
    import json

    from job_application_agent_langchain.agents.company_agent import (
        _get_llm,
        get_company_user_info,
    )
    from job_application_agent_langchain.config import Settings
    from job_application_agent_langchain.resume_polish.polisher import polish_resume
    from job_application_agent_langchain.user_info.parser import load_user_info

    try:
        # 优先从公司子 Agent 上下文获取用户信息，否则回退到本地文件加载
        user_info = get_company_user_info()
        if user_info is None:
            settings = Settings()
            user_info = load_user_info(
                settings.personal_info_file_path, settings.resume_file_path
            )

        # resume_content 若为 JSON 对象/数组，解析为额外上下文
        extra_context = None
        if resume_content:
            try:
                parsed = json.loads(resume_content)
                if isinstance(parsed, dict):
                    extra_context = parsed
                elif isinstance(parsed, list):
                    extra_context = {"resume_items": parsed}
            except (json.JSONDecodeError, TypeError):
                extra_context = None

        llm = _get_llm()
        result = polish_resume(user_info, jd, llm, extra_context=extra_context)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            {
                "original": {},
                "polished": {},
                "note": f"简历润色失败: {e}",
                "error": str(e),
            },
            ensure_ascii=False,
        )


def get_form_tools():
    """返回 Form Agent 使用的所有工具"""
    return [
        upload_resume,
        ask_about_resume_parser,
        analyze_parsed_resume,
        fill_form_field,
        get_current_page_form,
        submit_application,
        take_screenshot_for_review,
        notify_user,
        notify_delivery_warning,
        ask_user_for_field,
        check_field_in_memory,
        polish_resume_for_jd,
    ]
