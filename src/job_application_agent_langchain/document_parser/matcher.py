"""公司匹配模块。

从腾讯文档读取的表格行数据中，按用户给定的岗位/行业/城市关键词筛选匹配的公司。
匹配采用纯字符串包含匹配，大小写不敏感。
"""

from typing import Any

# 各字段支持的列名别名（统一小写比较）
_COLUMN_ALIASES: dict[str, list[str]] = {
    "company": ["公司", "公司名称", "企业", "企业名称", "company"],
    "position": ["岗位", "职位", "岗位名称", "position", "job"],
    "industry": ["行业", "领域", "industry"],
    "city": ["城市", "地点", "工作地点", "city", "location"],
    "url": ["链接", "投递链接", "官网", "网址", "url", "link"],
}


def _normalize_key(key: str) -> str:
    """规范化列名：去首尾空白并转小写。"""
    return (key or "").strip().lower()


def _find_column(rows: list[dict[str, str]], field: str) -> str | None:
    """从首行（表头）中查找指定字段对应的实际列名。

    Args:
        rows: 文档行数据，第一行作为表头识别来源（实际上每行 dict 的 key 都是表头）
        field: _COLUMN_ALIASES 中的字段名

    Returns:
        匹配到的实际列名（原始大小写），未找到返回 None
    """
    if not rows:
        return None
    aliases = [_normalize_key(a) for a in _COLUMN_ALIASES.get(field, [])]
    if not aliases:
        return None
    # 从第一行获取所有列名
    for original_key in rows[0].keys():
        if _normalize_key(original_key) in aliases:
            return original_key
    return None


def _safe_contains(haystack: str, needle: str) -> bool:
    """大小写不敏感的字符串包含判断，空 needle 不视为匹配。"""
    if not needle:
        return False
    return needle.lower() in (haystack or "").lower()


def match_companies(
    rows: list[dict[str, str]],
    job_keyword: str = "",
    industry: str = "",
    city: str = "",
) -> list[dict[str, str]]:
    """从文档行数据中筛选匹配用户要求的公司。

    匹配逻辑（纯字符串包含匹配，大小写不敏感）：
    1. 自动识别列名（支持多种命名）：
       - 公司名：'公司' '公司名称' '企业' '企业名称' 'company'
       - 岗位：'岗位' '职位' '岗位名称' 'position' 'job'
       - 行业：'行业' '领域' 'industry'
       - 城市：'城市' '地点' '工作地点' 'city' 'location'
       - 投递链接：'链接' '投递链接' '官网' '网址' 'url' 'link'
    2. 筛选条件（AND 关系，空条件跳过）：
       - job_keyword：在岗位列或公司名列中包含该关键词
       - industry：在行业列中包含该关键词
       - city：在城市列中包含该关键词
    3. 返回匹配的行列表（原始 dict），额外注入 '_company_name' 和 '_application_url' 字段方便后续使用

    如果找不到标准列名，尝试用第一列作为公司名。

    Args:
        rows: 文档表格行数据列表（每行是 字段名->值 的 dict）
        job_keyword: 岗位关键词（可空）
        industry: 行业关键词（可空）
        city: 城市关键词（可空）

    Returns:
        匹配的行列表，每行 dict 额外包含 '_company_name' 与 '_application_url' 字段
    """
    if not rows:
        return []

    # 识别各字段对应的实际列名
    company_col = _find_column(rows, "company")
    position_col = _find_column(rows, "position")
    industry_col = _find_column(rows, "industry")
    city_col = _find_column(rows, "city")
    url_col = _find_column(rows, "url")

    # 找不到公司列时，回退使用第一列作为公司名
    if company_col is None:
        # 取第一行的第一个 key 作为公司名列
        try:
            first_key = next(iter(rows[0].keys()))
            company_col = first_key
        except StopIteration:
            company_col = None

    matched: list[dict[str, str]] = []
    for row in rows:
        # 跳过空行：所有值均为空
        if not any((v or "").strip() for v in row.values()):
            continue

        company_value = row.get(company_col, "") if company_col else ""
        position_value = row.get(position_col, "") if position_col else ""
        industry_value = row.get(industry_col, "") if industry_col else ""
        city_value = row.get(city_col, "") if city_col else ""

        # 应用筛选条件（AND 关系，空条件跳过）
        if job_keyword:
            # 在岗位列或公司名列中包含该关键词
            if not (_safe_contains(position_value, job_keyword)
                    or _safe_contains(company_value, job_keyword)):
                continue
        if industry:
            if not _safe_contains(industry_value, industry):
                continue
        if city:
            if not _safe_contains(city_value, city):
                continue

        # 注入辅助字段，便于后续使用
        enriched: dict[str, Any] = dict(row)
        enriched["_company_name"] = (company_value or "").strip()
        enriched["_application_url"] = (row.get(url_col, "") if url_col else "").strip()
        matched.append(enriched)

    return matched
