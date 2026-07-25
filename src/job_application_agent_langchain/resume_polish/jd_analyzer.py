"""JD 分析模块：使用 LLM 从岗位 JD 中提取关键要求。"""

import json
import re

from langchain_openai import ChatOpenAI

from job_application_agent_langchain.resume_polish.prompts import JD_ANALYSIS_PROMPT


def _parse_json_response(content: str) -> dict:
    """从 LLM 返回内容中解析 JSON，兼容 markdown 代码块包裹的情况。"""
    if not content:
        return {}
    text = content.strip()

    # 去除 markdown 代码块（```json ... ``` 或 ``` ... ```）
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 回退：截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return {}


def _empty_analysis() -> dict:
    return {
        "required_skills": [],
        "preferred_skills": [],
        "experience_requirements": "",
        "keywords": [],
        "responsibilities": [],
        "summary": "",
    }


def analyze_jd(jd: str, llm: ChatOpenAI) -> dict:
    """使用 LLM 分析 JD，提取关键要求。

    分析阶段使用较低温度（temperature=0.3）以保证结构稳定。

    Args:
        jd: 岗位 JD 文本
        llm: ChatOpenAI 实例

    Returns:
        包含 required_skills、preferred_skills、experience_requirements、
        keywords、responsibilities、summary 的 dict。
    """
    if not jd or not jd.strip():
        return _empty_analysis()

    prompt = JD_ANALYSIS_PROMPT.format(jd=jd)
    # 分析阶段使用较低温度以保证结构稳定
    analysis_llm = llm.bind(temperature=0.3)

    try:
        response = analysis_llm.invoke(prompt)
    except Exception:
        return _empty_analysis()

    content = getattr(response, "content", str(response))
    result = _parse_json_response(content)

    # 确保所有字段存在且类型正确
    return {
        "required_skills": result.get("required_skills") or [],
        "preferred_skills": result.get("preferred_skills") or [],
        "experience_requirements": result.get("experience_requirements") or "",
        "keywords": result.get("keywords") or [],
        "responsibilities": result.get("responsibilities") or [],
        "summary": result.get("summary") or "",
    }
