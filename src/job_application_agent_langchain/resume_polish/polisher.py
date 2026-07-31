"""简历润色主模块：协调 JD 分析、内容匹配与 LLM 润色，输出 original/polished 对比结果。"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain_openai import ChatOpenAI

from job_application_agent_langchain.resume_polish.jd_analyzer import analyze_jd, _parse_json_response
from job_application_agent_langchain.resume_polish.prompts import (
    JD_ANALYSIS_PROMPT,
    RESUME_POLISH_PROMPT,
)
from job_application_agent_langchain.resume_polish.resume_matcher import extract_relevant_content
from job_application_agent_langchain.user_info.parser import UserInfo


def _build_original(
    user_info: UserInfo,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从用户原始信息构建 original 字典（未润色内容）。"""
    raw_resume_text = ""
    resume_file_path = ""
    if extra_context:
        raw_resume_text = str(extra_context.get("raw_resume_text") or "").strip()
        resume_file_path = str(extra_context.get("resume_file_path") or "").strip()

    # 上传文件存在时，它才是这次润色的原始简历。不能再把
    # personal_information.json 中的补充/测试资料冒充成上传 PDF 的原文。
    if raw_resume_text:
        return {
            "source_resume_text": raw_resume_text,
            "source_resume_file": Path(resume_file_path).name if resume_file_path else "",
            "self_introduction": "",
            "project_highlights": [],
            "skill_highlights": [],
            "work_highlights": [],
            "summary": "原始内容来自本次上传简历；完整原文见左侧。",
        }

    project_highlights = [
        {
            "name": proj.name or "",
            "role": proj.role or "",
            "description": proj.description or "",
            "relevance_to_jd": "",
        }
        for proj in user_info.project_experience
    ]
    skill_highlights = [
        {
            "skill": skill.name or "",
            "level": skill.level or "",
            "relevance": "",
        }
        for skill in user_info.skills
    ]
    work_highlights = [
        {
            "company": work.company or "",
            "position": work.position or "",
            "description": work.description or "",
            "relevance": "",
        }
        for work in user_info.work_experience
    ]

    # 基于真实信息的简要原始总结（不编造）
    summary_parts: list[str] = []
    if user_info.job_intentions:
        summary_parts.append(f"求职意向: {', '.join(user_info.job_intentions)}")
    if user_info.education:
        top = user_info.education[0]
        summary_parts.append(f"教育: {top.school} {top.major}".strip())
    summary_parts.append(f"项目经历 {len(user_info.project_experience)} 项")
    summary_parts.append(f"工作/实习经历 {len(user_info.work_experience)} 项")
    summary = "；".join(summary_parts)
    return {
        "self_introduction": user_info.self_introduction or "",
        "project_highlights": project_highlights,
        "skill_highlights": skill_highlights,
        "work_highlights": work_highlights,
        "summary": summary,
    }


def _normalize_polished(result: dict) -> dict[str, Any]:
    """规范化 LLM 返回的润色结果，确保所有字段与子字段存在且类型正确。"""
    def _ensure_list_of_dict(value: Any, required_keys: list[str]) -> list[dict]:
        if not isinstance(value, list):
            return []
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized.append({k: (item.get(k) if item.get(k) is not None else "") for k in required_keys})
        return normalized

    return {
        "self_introduction": result.get("self_introduction") or "",
        "project_highlights": _ensure_list_of_dict(
            result.get("project_highlights"),
            ["name", "role", "description", "relevance_to_jd"],
        ),
        "skill_highlights": _ensure_list_of_dict(
            result.get("skill_highlights"),
            ["skill", "level", "relevance"],
        ),
        "work_highlights": _ensure_list_of_dict(
            result.get("work_highlights"),
            ["company", "position", "description", "relevance"],
        ),
        "summary": result.get("summary") or "",
    }


def _ground_polished_entities(
    polished: dict[str, Any], raw_resume_text: str
) -> dict[str, Any]:
    """Remove entity labels that cannot be traced to the source resume."""

    if not raw_resume_text.strip():
        return polished

    def normalized(value: object) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).lower())

    source = normalized(raw_resume_text)

    def present(value: object) -> bool:
        candidate = normalized(value)
        return bool(candidate) and candidate in source

    projects = []
    for item in polished.get("project_highlights", []):
        if not present(item.get("name")):
            continue
        grounded = dict(item)
        if grounded.get("role") and not present(grounded["role"]):
            grounded["role"] = ""
        projects.append(grounded)

    work = []
    for item in polished.get("work_highlights", []):
        if not present(item.get("company")):
            continue
        grounded = dict(item)
        if grounded.get("position") and not present(grounded["position"]):
            grounded["position"] = ""
        work.append(grounded)

    skills = [
        dict(item)
        for item in polished.get("skill_highlights", [])
        if present(item.get("skill"))
    ]
    return {
        **polished,
        "project_highlights": projects,
        "skill_highlights": skills,
        "work_highlights": work,
    }


def _build_polish_prompt(
    user_info: UserInfo,
    jd_analysis: dict[str, Any],
    extra_context: dict[str, Any] | None,
) -> str:
    """构建去重后的润色提示词，上传简历存在时只把其原文发送一次。"""
    raw_resume_text = ""
    if extra_context:
        raw_resume_text = str(extra_context.get("raw_resume_text") or "").strip()

    if raw_resume_text:
        # WebUI 上传文件是唯一简历依据。不要再附加 personal_information.json
        # 生成的摘要、程序化匹配结果或 Agent 回传文本，以免测试资料混入且原文重复。
        candidate_summary = raw_resume_text[:12000]
        relevant_block: dict[str, Any] = {
            "source": "uploaded_resume",
            "instruction": "请直接从上方上传简历原文中识别并排序与 JD 相关的真实经历",
        }
    else:
        candidate_summary = user_info.to_summary()
        relevant_block = dict(extract_relevant_content(user_info, jd_analysis))
        if extra_context:
            safe_context = {
                key: value
                for key, value in extra_context.items()
                if key not in {"raw_resume_text", "resume_file_path"}
            }
            if safe_context:
                relevant_block["extra_context"] = safe_context

    return RESUME_POLISH_PROMPT.format(
        jd_analysis=json.dumps(jd_analysis, ensure_ascii=False, indent=2),
        user_summary=candidate_summary,
        relevant_content=json.dumps(relevant_block, ensure_ascii=False, indent=2),
    )


def polish_resume(
    user_info: UserInfo,
    jd: str,
    llm: ChatOpenAI,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """根据 JD 对用户简历进行自适应润色。

    流程：
      1. analyze_jd —— 用 LLM 提取 JD 关键要求
      2. extract_relevant_content —— 程序化匹配用户简历中与 JD 相关的内容
      3. 用 LLM（temperature=0.5）生成针对性润色内容
      4. 返回 {"original": {...}, "polished": {...}}，两者均为 dict

    Args:
        user_info: 用户信息
        jd: 岗位 JD 文本
        llm: ChatOpenAI 实例
        extra_context: 额外上下文（如从 resume_content 解析出的补充信息），可选

    Returns:
        {"original": {...}, "polished": {...}}，original 与 polished 均为 dict，
        包含 self_introduction、project_highlights、skill_highlights、
        work_highlights、summary 字段。
    """
    original = _build_original(user_info, extra_context)

    # 1. JD 分析
    jd_analysis = analyze_jd(jd, llm)

    # 2. 构建去重提示词并生成润色内容
    polished: dict[str, Any]
    try:
        prompt = _build_polish_prompt(user_info, jd_analysis, extra_context)

        polish_llm = llm.bind(temperature=0.3, max_tokens=1800)
        response = polish_llm.invoke(prompt)
        content = getattr(response, "content", str(response))
        parsed = _parse_json_response(content)
        polished = _ground_polished_entities(
            _normalize_polished(parsed),
            str((extra_context or {}).get("raw_resume_text") or ""),
        )
    except Exception:
        # 润色失败时回退为原始内容，保证流程不中断
        polished = dict(original)

    return {"original": original, "polished": polished}


async def polish_resume_async(
    user_info: UserInfo,
    jd: str,
    llm: ChatOpenAI,
    extra_context: dict[str, Any] | None = None,
    progress_callback: Callable[[str], Awaitable[None]] | None = None,
    stage_timeout: int = 45,
    generation_timeout: int | None = None,
) -> dict[str, Any]:
    """异步、分阶段且可超时的简历润色，避免阻塞 WebUI 事件循环。"""
    original = _build_original(user_info, extra_context)

    async def progress(message: str) -> None:
        if progress_callback is not None:
            await progress_callback(message)

    analysis_timeout = max(5, stage_timeout)
    generation_timeout = max(
        5, generation_timeout if generation_timeout is not None else stage_timeout
    )
    analysis_started = time.monotonic()
    await progress(
        f"步骤 1/2：正在分析岗位 JD（最长 {analysis_timeout} 秒）"
    )
    if not jd or not jd.strip():
        jd_analysis = {
            "required_skills": [],
            "preferred_skills": [],
            "experience_requirements": "",
            "keywords": [],
            "responsibilities": [],
            "summary": "",
        }
    else:
        analysis_llm = llm.bind(temperature=0.2, max_tokens=700)
        try:
            async with asyncio.timeout(analysis_timeout):
                response = await analysis_llm.ainvoke(
                    JD_ANALYSIS_PROMPT.format(jd=jd.strip()[:12000])
                )
        except TimeoutError as exc:
            raise TimeoutError(f"JD 分析超过 {analysis_timeout} 秒") from exc
        content = getattr(response, "content", str(response))
        parsed = _parse_json_response(content)
        jd_analysis = {
            "required_skills": parsed.get("required_skills") or [],
            "preferred_skills": parsed.get("preferred_skills") or [],
            "experience_requirements": parsed.get("experience_requirements") or "",
            "keywords": parsed.get("keywords") or [],
            "responsibilities": parsed.get("responsibilities") or [],
            "summary": parsed.get("summary") or "",
        }

    await progress(
        f"步骤 1/2 完成（{time.monotonic() - analysis_started:.1f} 秒）"
    )
    prompt = _build_polish_prompt(user_info, jd_analysis, extra_context)
    raw_resume_characters = len(
        str((extra_context or {}).get("raw_resume_text") or "")
    )
    await progress(
        "步骤 2/2：正在根据上传简历生成针对性润色"
        f"（简历原文 {raw_resume_characters} 字符；完整提示词 {len(prompt)} 字符；"
        f"最长 {generation_timeout} 秒）"
    )
    generation_started = time.monotonic()
    polish_llm = llm.bind(temperature=0.3, max_tokens=1800)
    try:
        async with asyncio.timeout(generation_timeout):
            response = await polish_llm.ainvoke(prompt)
    except TimeoutError as exc:
        raise TimeoutError(f"简历生成超过 {generation_timeout} 秒") from exc
    content = getattr(response, "content", str(response))
    parsed = _parse_json_response(content)
    polished = _ground_polished_entities(
        _normalize_polished(parsed),
        str((extra_context or {}).get("raw_resume_text") or ""),
    )
    if not any(
        (
            polished["self_introduction"],
            polished["project_highlights"],
            polished["skill_highlights"],
            polished["work_highlights"],
            polished["summary"],
        )
    ):
        raise ValueError("模型没有返回可用的润色 JSON")
    await progress(
        f"步骤 2/2 完成（{time.monotonic() - generation_started:.1f} 秒），"
        "简历润色完成，正在准备审核内容"
    )
    return {"original": original, "polished": polished}
