"""简历匹配模块：程序化地从用户简历中提取与 JD 相关的内容。

本步骤不调用 LLM，仅基于关键词/技能的字符串匹配，为后续润色准备好上下文。
"""

from typing import Any

from job_application_agent_langchain.user_info.parser import UserInfo


def _normalize(text: str) -> str:
    if not text:
        return ""
    return text.lower().strip()


def _token_in_text(token: str, text: str) -> bool:
    """判断某个 JD 术语/技能是否出现在文本中（大小写不敏感的子串匹配）。"""
    if not token or not text:
        return False
    return _normalize(token) in _normalize(text)


def _match_skills(user_info: UserInfo, jd_analysis: dict) -> list[dict]:
    """将用户技能与 JD 必备/加分技能进行匹配。"""
    required = jd_analysis.get("required_skills", []) or []
    preferred = jd_analysis.get("preferred_skills", []) or []

    matched: list[dict] = []
    seen: set[str] = set()

    for skill in user_info.skills:
        skill_name = skill.name or ""
        if not skill_name:
            continue
        key = _normalize(skill_name)
        if key in seen:
            continue

        match_type = ""
        matched_term = ""
        for req in required:
            if _token_in_text(req, skill_name) or _token_in_text(skill_name, req):
                match_type = "required"
                matched_term = req
                break
        if not match_type:
            for pref in preferred:
                if _token_in_text(pref, skill_name) or _token_in_text(skill_name, pref):
                    match_type = "preferred"
                    matched_term = pref
                    break

        if match_type:
            seen.add(key)
            matched.append({
                "skill": skill_name,
                "level": skill.level or "",
                "match_type": match_type,
                "matched_jd_term": matched_term,
            })

    return matched


def _score_item(text: str, jd_terms: list[str]) -> tuple[int, list[str]]:
    """统计 JD 术语在文本中的命中数，返回 (得分, 命中的术语列表)。"""
    if not text:
        return 0, []
    score = 0
    hits: list[str] = []
    for term in jd_terms:
        if term and _token_in_text(term, text):
            score += 1
            hits.append(term)
    return score, hits


def _match_projects(user_info: UserInfo, jd_analysis: dict) -> list[dict]:
    """按与 JD 的相关性排序项目经历。"""
    jd_terms = _collect_jd_terms(jd_analysis)
    scored: list[dict] = []
    for proj in user_info.project_experience:
        text = " ".join([proj.name or "", proj.role or "", proj.description or ""])
        score, hits = _score_item(text, jd_terms)
        scored.append({
            "name": proj.name or "",
            "role": proj.role or "",
            "description": proj.description or "",
            "score": score,
            "matched_keywords": hits,
        })
    # 相关性高的在前
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _match_work(user_info: UserInfo, jd_analysis: dict) -> list[dict]:
    """按与 JD 的相关性排序工作/实习经历。"""
    jd_terms = _collect_jd_terms(jd_analysis)
    scored: list[dict] = []
    for work in user_info.work_experience:
        text = " ".join([
            work.company or "",
            work.position or "",
            work.department or "",
            work.description or "",
        ])
        score, hits = _score_item(text, jd_terms)
        scored.append({
            "company": work.company or "",
            "position": work.position or "",
            "description": work.description or "",
            "score": score,
            "matched_keywords": hits,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _match_awards(user_info: UserInfo, jd_analysis: dict) -> list[dict]:
    """筛选与 JD 相关的获奖经历。"""
    jd_terms = _collect_jd_terms(jd_analysis)
    relevant: list[dict] = []
    for award in user_info.awards:
        text = " ".join([award.name or "", award.description or ""])
        score, hits = _score_item(text, jd_terms)
        if score > 0:
            relevant.append({
                "name": award.name or "",
                "level": award.level or "",
                "date": award.date or "",
                "description": award.description or "",
                "matched_keywords": hits,
            })
    return relevant


def _match_publications(user_info: UserInfo, jd_analysis: dict) -> list[dict]:
    """筛选与 JD 相关的论文/著作。"""
    jd_terms = _collect_jd_terms(jd_analysis)
    relevant: list[dict] = []
    for pub in user_info.publications:
        text = " ".join([pub.title or "", pub.conference or "", pub.description or ""])
        score, hits = _score_item(text, jd_terms)
        if score > 0:
            relevant.append({
                "title": pub.title or "",
                "conference": pub.conference or "",
                "date": pub.date or "",
                "matched_keywords": hits,
            })
    return relevant


def _collect_jd_terms(jd_analysis: dict) -> list[str]:
    """汇总 JD 中所有可用于匹配的术语（技能 + 关键词 + 职责）。"""
    terms: list[str] = []
    for key in ("required_skills", "preferred_skills", "keywords"):
        terms.extend(jd_analysis.get(key, []) or [])
    return terms


def extract_relevant_content(user_info: UserInfo, jd_analysis: dict) -> dict[str, Any]:
    """从用户简历中提取与 JD 相关的内容（程序化匹配，不调用 LLM）。

    Args:
        user_info: 用户信息
        jd_analysis: analyze_jd 返回的 JD 分析结果

    Returns:
        dict，包含 matched_skills、relevant_projects、relevant_work、
        relevant_awards、relevant_publications。
    """
    return {
        "matched_skills": _match_skills(user_info, jd_analysis),
        "relevant_projects": _match_projects(user_info, jd_analysis),
        "relevant_work": _match_work(user_info, jd_analysis),
        "relevant_awards": _match_awards(user_info, jd_analysis),
        "relevant_publications": _match_publications(user_info, jd_analysis),
    }
