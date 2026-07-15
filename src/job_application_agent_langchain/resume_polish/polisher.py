"""简历润色主模块：协调 JD 分析、内容匹配与 LLM 润色，输出 original/polished 对比结果。"""

import json
from typing import Any

from langchain_openai import ChatOpenAI

from job_application_agent_langchain.resume_polish.jd_analyzer import analyze_jd, _parse_json_response
from job_application_agent_langchain.resume_polish.prompts import RESUME_POLISH_PROMPT
from job_application_agent_langchain.resume_polish.resume_matcher import extract_relevant_content
from job_application_agent_langchain.user_info.parser import UserInfo


def _build_original(user_info: UserInfo) -> dict[str, Any]:
    """从用户原始信息构建 original 字典（未润色内容）。"""
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
    original = _build_original(user_info)

    # 1. JD 分析
    jd_analysis = analyze_jd(jd, llm)

    # 2. 程序化匹配相关内容
    relevant = extract_relevant_content(user_info, jd_analysis)

    # 3. LLM 润色（creative，temperature=0.5）
    polished: dict[str, Any]
    try:
        relevant_block = dict(relevant)
        if extra_context:
            relevant_block["extra_context"] = extra_context

        prompt = RESUME_POLISH_PROMPT.format(
            jd_analysis=json.dumps(jd_analysis, ensure_ascii=False, indent=2),
            user_summary=user_info.to_summary(),
            relevant_content=json.dumps(relevant_block, ensure_ascii=False, indent=2),
        )

        polish_llm = llm.bind(temperature=0.5)
        response = polish_llm.invoke(prompt)
        content = getattr(response, "content", str(response))
        parsed = _parse_json_response(content)
        polished = _normalize_polished(parsed)
    except Exception:
        # 润色失败时回退为原始内容，保证流程不中断
        polished = dict(original)

    return {"original": original, "polished": polished}
