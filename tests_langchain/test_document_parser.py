"""document_parser 模块的单元测试。

主要测试 match_companies 函数的各种情况：
- 空行输入
- 多种列名识别
- 多条件组合筛选（AND 关系）
- 无匹配场景
- 投递链接注入
- 公司名回退到第一列
- 大小写不敏感
"""

import pytest

from job_application_agent_langchain.document_parser.matcher import match_companies


class TestMatchCompaniesEmpty:
    """空输入与空行处理"""

    def test_empty_rows(self):
        """空列表输入应返回空列表"""
        assert match_companies([]) == []

    def test_all_empty_rows_skipped(self):
        """所有值均为空的行应被跳过"""
        rows = [
            {"公司": "", "岗位": "", "城市": ""},
            {"公司": "   ", "岗位": "", "城市": ""},
        ]
        assert match_companies(rows) == []

    def test_no_filter_returns_all_non_empty(self):
        """不传任何筛选条件时，应返回所有非空行"""
        rows = [
            {"公司": "阿里", "岗位": "算法", "城市": "杭州"},
            {"公司": "", "岗位": "", "城市": ""},  # 空行，应被跳过
            {"公司": "腾讯", "岗位": "后端", "城市": "深圳"},
        ]
        result = match_companies(rows)
        assert len(result) == 2
        names = [r["_company_name"] for r in result]
        assert "阿里" in names
        assert "腾讯" in names


class TestMatchCompaniesColumnRecognition:
    """多种列名识别"""

    def test_recognize_company_aliases(self):
        """公司列的多种命名都应被识别"""
        test_cases = [
            {"公司": "阿里", "岗位": "算法"},
            {"公司名称": "阿里", "岗位": "算法"},
            {"企业": "阿里", "岗位": "算法"},
            {"企业名称": "阿里", "岗位": "算法"},
            {"company": "阿里", "岗位": "算法"},
            {"Company": "阿里", "岗位": "算法"},  # 大小写不敏感
        ]
        for row in test_cases:
            result = match_companies([row])
            assert len(result) == 1, f"列名 {list(row.keys())[0]} 未被识别"
            assert result[0]["_company_name"] == "阿里"

    def test_recognize_position_aliases(self):
        """岗位列的多种命名都应被识别（用于 job_keyword 匹配）"""
        for col in ["岗位", "职位", "岗位名称", "position", "job", "Position"]:
            rows = [{"公司": "某公司", col: "算法工程师"}]
            result = match_companies(rows, job_keyword="算法")
            assert len(result) == 1, f"岗位列名 {col} 未被识别"
            assert result[0]["_company_name"] == "某公司"

    def test_recognize_industry_aliases(self):
        """行业列的多种命名都应被识别"""
        for col in ["行业", "领域", "industry"]:
            rows = [{"公司": "某公司", col: "互联网"}]
            result = match_companies(rows, industry="互联网")
            assert len(result) == 1, f"行业列名 {col} 未被识别"

    def test_recognize_city_aliases(self):
        """城市列的多种命名都应被识别"""
        for col in ["城市", "地点", "工作地点", "city", "location"]:
            rows = [{"公司": "某公司", col: "北京"}]
            result = match_companies(rows, city="北京")
            assert len(result) == 1, f"城市列名 {col} 未被识别"

    def test_recognize_url_aliases(self):
        """投递链接列的多种命名都应被识别并注入 _application_url"""
        for col in ["链接", "投递链接", "官网", "网址", "url", "link"]:
            rows = [{"公司": "某公司", col: "https://example.com/apply"}]
            result = match_companies(rows)
            assert len(result) == 1, f"链接列名 {col} 未被识别"
            assert result[0]["_application_url"] == "https://example.com/apply"

    def test_fallback_to_first_column(self):
        """找不到标准公司列名时，回退用第一列作为公司名"""
        rows = [
            {"机构": "某某机构", "工种": "研发"},
        ]
        result = match_companies(rows)
        assert len(result) == 1
        # 第一列 "机构" 作为公司名
        assert result[0]["_company_name"] == "某某机构"


class TestMatchCompaniesFiltering:
    """多条件筛选（AND 关系）"""

    def test_job_keyword_matches_position(self):
        """job_keyword 在岗位列命中应保留"""
        rows = [
            {"公司": "阿里", "岗位": "算法工程师"},
            {"公司": "腾讯", "岗位": "产品经理"},
        ]
        result = match_companies(rows, job_keyword="算法")
        assert len(result) == 1
        assert result[0]["_company_name"] == "阿里"

    def test_job_keyword_matches_company(self):
        """job_keyword 在公司名列命中也应保留"""
        rows = [
            {"公司": "字节跳动", "岗位": "研发"},
            {"公司": "美团", "岗位": "运营"},
        ]
        result = match_companies(rows, job_keyword="字节")
        assert len(result) == 1
        assert result[0]["_company_name"] == "字节跳动"

    def test_industry_filter(self):
        """industry 在行业列命中应保留"""
        rows = [
            {"公司": "公司A", "行业": "互联网"},
            {"公司": "公司B", "行业": "金融"},
            {"公司": "公司C", "行业": "互联网+教育"},
        ]
        result = match_companies(rows, industry="互联网")
        assert len(result) == 2
        names = {r["_company_name"] for r in result}
        assert names == {"公司A", "公司C"}

    def test_city_filter(self):
        """city 在城市列命中应保留"""
        rows = [
            {"公司": "公司A", "城市": "北京"},
            {"公司": "公司B", "城市": "上海"},
            {"公司": "公司C", "城市": "北京/上海"},
        ]
        result = match_companies(rows, city="北京")
        assert len(result) == 2
        names = {r["_company_name"] for r in result}
        assert names == {"公司A", "公司C"}

    def test_and_combination_all_match(self):
        """多条件 AND 组合：全部命中才保留"""
        rows = [
            {"公司": "阿里", "岗位": "算法", "行业": "互联网", "城市": "杭州"},
            {"公司": "腾讯", "岗位": "算法", "行业": "互联网", "城市": "深圳"},
            {"公司": "百度", "岗位": "算法", "行业": "互联网", "城市": "北京"},
        ]
        result = match_companies(
            rows, job_keyword="算法", industry="互联网", city="北京"
        )
        assert len(result) == 1
        assert result[0]["_company_name"] == "百度"

    def test_and_combination_partial_match_filtered_out(self):
        """多条件 AND 组合：部分命中应被过滤掉"""
        rows = [
            {"公司": "阿里", "岗位": "算法", "行业": "互联网", "城市": "杭州"},
            {"公司": "腾讯", "岗位": "算法", "行业": "金融", "城市": "深圳"},
        ]
        # 行业不匹配的应被过滤
        result = match_companies(
            rows, job_keyword="算法", industry="互联网"
        )
        assert len(result) == 1
        assert result[0]["_company_name"] == "阿里"

    def test_empty_condition_skipped(self):
        """空条件应被跳过（等价于不限制）"""
        rows = [
            {"公司": "阿里", "岗位": "算法", "城市": "杭州"},
            {"公司": "腾讯", "岗位": "后端", "城市": "深圳"},
        ]
        # 空字符串条件等价于不筛选
        result = match_companies(rows, job_keyword="", industry="", city="")
        assert len(result) == 2


class TestMatchCompaniesNoMatch:
    """无匹配场景"""

    def test_no_match_returns_empty(self):
        """无任何匹配时应返回空列表"""
        rows = [
            {"公司": "阿里", "岗位": "算法"},
            {"公司": "腾讯", "岗位": "后端"},
        ]
        result = match_companies(rows, job_keyword="不存在岗位")
        assert result == []

    def test_no_match_with_all_conditions(self):
        """所有条件都不命中时应返回空列表"""
        rows = [
            {"公司": "阿里", "岗位": "算法", "行业": "互联网", "城市": "杭州"},
        ]
        result = match_companies(
            rows, job_keyword="算法", industry="互联网", city="深圳"
        )
        assert result == []


class TestMatchCompaniesCaseInsensitive:
    """大小写不敏感匹配"""

    def test_job_keyword_case_insensitive(self):
        """英文岗位关键词大小写不敏感"""
        rows = [
            {"公司": "公司A", "岗位": "Software Engineer"},
            {"公司": "公司B", "岗位": "Product Manager"},
        ]
        # 用小写关键词匹配大写岗位文本
        result = match_companies(rows, job_keyword="software")
        assert len(result) == 1
        assert result[0]["_company_name"] == "公司A"

    def test_company_name_case_insensitive(self):
        """公司名大小写不敏感"""
        rows = [
            {"company": "ByteDance", "岗位": "研发"},
            {"company": "Tencent", "岗位": "研发"},
        ]
        result = match_companies(rows, job_keyword="bytedance")
        assert len(result) == 1
        assert result[0]["_company_name"] == "ByteDance"


class TestMatchCompaniesEnrichedFields:
    """注入的辅助字段"""

    def test_company_name_and_url_injected(self):
        """匹配行应注入 _company_name 与 _application_url"""
        rows = [
            {
                "公司": "阿里",
                "岗位": "算法",
                "城市": "杭州",
                "投递链接": "https://talent.alibaba.com/apply",
            },
        ]
        result = match_companies(rows)
        assert len(result) == 1
        row = result[0]
        assert row["_company_name"] == "阿里"
        assert row["_application_url"] == "https://talent.alibaba.com/apply"
        # 原始字段应保留
        assert row["公司"] == "阿里"
        assert row["岗位"] == "算法"
        assert row["城市"] == "杭州"

    def test_application_url_empty_when_no_url_column(self):
        """无链接列时 _application_url 应为空字符串"""
        rows = [{"公司": "阿里", "岗位": "算法"}]
        result = match_companies(rows)
        assert len(result) == 1
        assert result[0]["_application_url"] == ""

    def test_application_url_stripped(self):
        """链接值应去除首尾空白"""
        rows = [{"公司": "阿里", "链接": "  https://example.com  "}]
        result = match_companies(rows)
        assert result[0]["_application_url"] == "https://example.com"

    def test_company_name_stripped(self):
        """公司名应去除首尾空白"""
        rows = [{"公司": "  阿里  ", "岗位": "算法"}]
        result = match_companies(rows)
        assert result[0]["_company_name"] == "阿里"


class TestMatchCompaniesComplexScenarios:
    """综合场景"""

    def test_realistic_document_scenario(self):
        """模拟真实文档场景：多行、多列、混合命名"""
        rows = [
            {"公司名称": "字节跳动", "职位": "算法工程师", "行业": "互联网", "工作地点": "北京", "投递链接": "https://job.bytedance.com/1"},
            {"公司名称": "腾讯", "职位": "后端工程师", "行业": "互联网", "工作地点": "深圳", "投递链接": "https://join.tencent.com/1"},
            {"公司名称": "美团", "职位": "算法工程师", "行业": "互联网", "工作地点": "北京", "投递链接": "https://zhaopin.meituan.com/1"},
            {"公司名称": "中信证券", "职位": "量化研究员", "行业": "金融", "工作地点": "北京", "投递链接": "https://www.citics.com/1"},
            {"公司名称": "", "职位": "", "行业": "", "工作地点": "", "投递链接": ""},  # 空行
        ]
        # 筛选：算法 + 互联网 + 北京
        result = match_companies(
            rows, job_keyword="算法", industry="互联网", city="北京"
        )
        assert len(result) == 2
        names = {r["_company_name"] for r in result}
        assert names == {"字节跳动", "美团"}
        # 验证链接注入
        urls = {r["_company_name"]: r["_application_url"] for r in result}
        assert urls["字节跳动"] == "https://job.bytedance.com/1"
        assert urls["美团"] == "https://zhaopin.meituan.com/1"

    def test_job_keyword_substring_match(self):
        """job_keyword 应支持子串匹配"""
        rows = [
            {"公司": "公司A", "岗位": "高级算法工程师"},
            {"公司": "公司B", "岗位": "前端工程师"},
        ]
        result = match_companies(rows, job_keyword="算法")
        assert len(result) == 1
        assert result[0]["_company_name"] == "公司A"
