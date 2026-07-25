"""腾讯文档解析模块。

提供读取腾讯文档智能表格与公司匹配能力。
- reader.read_tencent_document: 打开腾讯文档 URL 并提取表格行数据
- matcher.match_companies: 从行数据中按岗位/行业/城市筛选匹配的公司
"""

from job_application_agent_langchain.document_parser.matcher import match_companies
from job_application_agent_langchain.document_parser.reader import (
    DocumentAccessError,
    read_tencent_document,
)

__all__ = [
    "DocumentAccessError",
    "read_tencent_document",
    "match_companies",
]
