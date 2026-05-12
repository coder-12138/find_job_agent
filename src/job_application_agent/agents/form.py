from agents import Agent, function_tool, RunContextWrapper

from job_application_agent.context import AppContext
from job_application_agent.tools.notify import notify_user, notify_delivery_warning
from job_application_agent.utils import sanitize_agent_name


async def _get_browser():
    from job_application_agent.browser.automation import BrowserAutomation
    from job_application_agent.config import Settings

    settings = Settings()
    return await BrowserAutomation.get_shared(
        headless=settings.browser_headless,
        timeout=settings.browser_timeout,
    )


@function_tool
async def upload_resume(
    ctx: RunContextWrapper[AppContext],
    file_input_selector: str = 'input[type="file"]',
) -> str:
    """上传简历附件到当前页面。

    Args:
        file_input_selector: 文件上传input元素的CSS选择器，默认为 'input[type="file"]'
    """
    try:
        browser = await _get_browser()
        resume_path = ctx.context.user_info.resume_file_path
        if not resume_path:
            return "简历文件路径未配置，请在.env中设置RESUME_FILE_PATH"

        success = await browser.upload_file(file_input_selector, resume_path)
        if success:
            return f"简历上传成功: {resume_path}"
        return "简历上传失败"
    except Exception as e:
        return f"上传简历时出错: {e}"


@function_tool
async def ask_about_resume_parser(
    ctx: RunContextWrapper[AppContext],
) -> str:
    """询问用户是否使用网站自带的简历解析器。"""
    result = await notify_user(
        ctx,
        title="简历解析器选择",
        message="当前网站可能提供简历解析功能。是否使用网站自带的简历解析器？\n\n"
        "选择 yes: 使用解析器解析简历，然后自动修正错误和补充缺失\n"
        "选择 no: 不使用解析器，直接手动填写所有字段",
        level="info",
        need_confirmation=True,
        confirmation_prompt="是否使用简历解析器？（yes/no）",
    )

    if "yes" in result.lower() or "y" in result.lower():
        ctx.context.companies[ctx.context.current_company_index].use_resume_parser = True
        return "用户选择使用简历解析器"
    ctx.context.companies[ctx.context.current_company_index].use_resume_parser = False
    return "用户选择不使用简历解析器"


@function_tool
async def analyze_parsed_resume(
    ctx: RunContextWrapper[AppContext],
) -> str:
    """分析网站解析后的简历内容，与用户信息对比，识别错误和缺失项。
    仅在用户选择使用简历解析器时调用。"""
    try:
        browser = await _get_browser()
        page_text = await browser.get_page_text()

        user_summary = ctx.context.user_info.to_summary()

        return (
            f"页面当前内容:\n{page_text[:3000]}\n\n"
            f"用户实际信息:\n{user_summary}\n\n"
            "请对比页面解析内容与用户实际信息，识别以下问题：\n"
            "1. 解析错误的内容（与用户信息不一致）\n"
            "2. 缺失的字段（用户有但页面未填）\n"
            "3. 多余的内容（页面有但用户未提供）\n\n"
            "然后使用表单填写工具修正错误和补充缺失。"
        )
    except Exception as e:
        return f"分析失败: {e}"


@function_tool
async def fill_form_field(
    ctx: RunContextWrapper[AppContext],
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


@function_tool
async def fill_personal_info(
    ctx: RunContextWrapper[AppContext],
) -> str:
    """自动识别并填写页面上的个人信息字段。根据用户信息自动匹配表单字段。"""
    try:
        browser = await _get_browser()
        fields = await browser.get_form_fields()
        if not fields:
            return "未找到表单字段"

        user_info = ctx.context.user_info
        pi = user_info.personal_info

        field_mapping = {
            "姓名": {"value": pi.name, "type": "text"},
            "name": {"value": pi.name, "type": "text"},
            "英文名": {"value": pi.english_name, "type": "text"},
            "性别": {"value": pi.gender, "type": "select"},
            "gender": {"value": pi.gender, "type": "select"},
            "出生": {"value": pi.birthday, "type": "date"},
            "birthday": {"value": pi.birthday, "type": "date"},
            "手机": {"value": pi.phone, "type": "text"},
            "phone": {"value": pi.phone, "type": "text"},
            "电话": {"value": pi.phone, "type": "text"},
            "邮箱": {"value": pi.email, "type": "text"},
            "email": {"value": pi.email, "type": "text"},
            "证件号码": {"value": pi.id_number, "type": "text"},
            "身份证": {"value": pi.id_number, "type": "text"},
            "证件类型": {"value": pi.id_type, "type": "select"},
            "国籍": {"value": pi.nationality, "type": "text"},
            "民族": {"value": pi.ethnicity, "type": "select"},
            "政治": {"value": pi.political_status, "type": "select"},
            "婚姻": {"value": pi.marital_status, "type": "select"},
            "地址": {"value": pi.address, "type": "text"},
            "微信": {"value": pi.wechat, "type": "text"},
            "QQ": {"value": pi.qq, "type": "text"},
            "户籍": {"value": pi.household_registration, "type": "text"},
            "户籍类型": {"value": pi.household_type, "type": "select"},
            "籍贯": {"value": pi.native_place, "type": "text"},
            "生源地": {"value": pi.source_place, "type": "text"},
            "现居住": {"value": pi.current_city, "type": "text"},
            "邮编": {"value": pi.zip_code, "type": "text"},
            "血型": {"value": pi.blood_type, "type": "select"},
            "健康": {"value": pi.health_status, "type": "select"},
            "紧急联系人": {"value": pi.emergency_contact, "type": "text"},
            "紧急联系人电话": {"value": pi.emergency_contact_phone, "type": "text"},
            "与紧急联系人关系": {"value": pi.emergency_contact_relation, "type": "select"},
        }

        results = []
        for field in fields:
            field_name = field.get("name", "").lower()
            field_label = field.get("label", "")
            field_placeholder = field.get("placeholder", "")
            selector = field.get("selector", "")

            matched_value = None
            matched_type = field.get("type", "text")

            for key, mapping in field_mapping.items():
                if key in field_name or key in field_label or key in field_placeholder:
                    if mapping["value"]:
                        matched_value = mapping["value"]
                        matched_type = mapping.get("type", matched_type)
                    break

            if matched_value:
                if matched_type == "select":
                    success = await browser.select_option(selector, label=matched_value)
                elif matched_type == "date":
                    parts = matched_value.split("-")
                    year = parts[0] if len(parts) > 0 else ""
                    month = parts[1] if len(parts) > 1 else ""
                    day = parts[2] if len(parts) > 2 else ""
                    success = await browser.select_date_from_calendar(
                        selector, year, month, day
                    )
                else:
                    success = await browser.fill_text(selector, matched_value)

                results.append(
                    f"{'✅' if success else '❌'} {field_label or field_name}: {matched_value}"
                )
            else:
                results.append(f"⏭️ {field_label or field_name}: 跳过（信息缺失）")

        return "个人信息填写结果:\n" + "\n".join(results)
    except Exception as e:
        return f"填写个人信息时出错: {e}"


@function_tool
async def fill_education_info(
    ctx: RunContextWrapper[AppContext],
) -> str:
    """填写教育经历信息。"""
    try:
        browser = await _get_browser()
        user_info = ctx.context.user_info
        if not user_info.education:
            return "用户未提供教育经历信息，跳过"

        results = []
        for i, edu in enumerate(user_info.education):
            edu_info = (
                f"学校: {edu.school}, 专业: {edu.major}, "
                f"学历: {edu.degree}, 时间: {edu.start_date} ~ {edu.end_date}"
            )
            if edu.gpa:
                edu_info += f", GPA: {edu.gpa}"

            results.append(f"教育经历 {i+1}: {edu_info}")

            if i > 0:
                add_buttons = await browser.find_elements(
                    'button:has-text("添加"), button:has-text("新增"), '
                    'a:has-text("添加"), a:has-text("新增")'
                )
                if add_buttons:
                    try:
                        await add_buttons[0].click()
                        import asyncio
                        await asyncio.sleep(1)
                    except Exception:
                        pass

        return "教育经历信息:\n" + "\n".join(results) + "\n\n请使用 fill_form_field 工具逐个填写各字段。"
    except Exception as e:
        return f"填写教育经历时出错: {e}"


@function_tool
async def get_current_page_form(
    ctx: RunContextWrapper[AppContext],
) -> str:
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


@function_tool
async def submit_application(
    ctx: RunContextWrapper[AppContext],
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
            company_idx = ctx.context.current_company_index
            if company_idx < len(ctx.context.companies):
                ctx.context.companies[company_idx].submitted = True
            return "投递操作已执行"
        return "投递按钮点击失败，可能未找到按钮"
    except Exception as e:
        return f"投递时出错: {e}"


@function_tool
async def take_screenshot_for_review(
    ctx: RunContextWrapper[AppContext],
) -> str:
    """截取当前页面截图，供用户检查。"""
    try:
        browser = await _get_browser()
        screenshot_path = await browser.take_screenshot()
        return f"截图已保存到: {screenshot_path}"
    except Exception as e:
        return f"截图失败: {e}"


def create_form_agent(company_name: str) -> Agent[AppContext]:
    safe_name = sanitize_agent_name(company_name)
    return Agent[AppContext](
        name=f"Form_{safe_name}",
        instructions=f"""你是{company_name}的表单填写Agent。你的任务是：

1. **简历附件上传**：使用 upload_resume 工具上传简历附件
2. **简历解析器选择**：使用 ask_about_resume_parser 工具询问用户是否使用网站自带的简历解析器
   - 用户选择不使用：如果网站支持只上传不解析，则直接上传后填写表单；如果网站自动解析，则忽略解析结果，使用用户信息重新填写所有字段
   - 用户选择使用：使用网站解析器，然后用 analyze_parsed_resume 工具分析解析结果，自动修正错误和补充缺失
3. **表单识别**：使用 get_current_page_form 工具获取当前页面的所有表单字段
4. **表单填写**：
   - 使用 fill_personal_info 工具填写个人信息
   - 使用 fill_education_info 工具填写教育经历
   - 使用 fill_form_field 工具逐个填写其他字段
   - 支持多种表单元素：文本框(text)、下拉菜单(select)、单选按钮(radio)、复选框(checkbox)、日历组件(date)、文本域(textarea)
   - 信息缺失时跳过不填，不要张冠李戴
5. **用户检查**：填写完成后，使用 take_screenshot_for_review 截图，然后使用 notify_user 工具通知用户检查
6. **投递确认**：用户检查完毕后，使用 notify_delivery_warning 工具弹出醒目警告
   - 如果用户选择否，直接结束该公司流程
   - 如果用户选择是，使用 submit_application 工具执行投递

用户信息摘要：
{{user_info_summary}}

遇到任何问题（如找不到表单元素、页面加载失败、验证码等），立即使用 notify_user 工具通知用户并等待指示。""",
        tools=[
            upload_resume,
            ask_about_resume_parser,
            analyze_parsed_resume,
            fill_form_field,
            fill_personal_info,
            fill_education_info,
            get_current_page_form,
            submit_application,
            take_screenshot_for_review,
            notify_user,
            notify_delivery_warning,
        ],
    )
