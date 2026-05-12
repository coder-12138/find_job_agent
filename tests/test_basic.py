import pytest
import os
import json
import tempfile

from job_application_agent.config import Settings
from job_application_agent.context import AppContext, CompanyState
from job_application_agent.user_info.parser import (
    UserInfo, PersonalInfo, Education, WorkExperience,
    ProjectExperience, Award, Skill, load_user_info, _parse_text_info,
)
from job_application_agent.utils import sanitize_agent_name
from job_application_agent.agents.search import create_search_agent
from job_application_agent.agents.form import create_form_agent
from job_application_agent.agents.orchestrator import create_orchestrator


class TestSettings:
    def test_singleton(self):
        s1 = Settings()
        s2 = Settings()
        assert s1 is s2

    def test_default_values(self):
        s = Settings()
        assert s.openai_model == "gpt-4o"
        assert s.browser_headless is True
        assert s.email_notification_enabled is False

    def test_validate_missing_api_key(self):
        s = Settings()
        errors = s.validate()
        assert any("OPENAI_API_KEY" in e for e in errors)

    def test_desktop_detection_linux_no_display(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", "")
        monkeypatch.setenv("WAYLAND_DISPLAY", "")
        s = Settings()
        s._initialized = False
        s.__class__._instance = None
        s2 = Settings()
        assert s2.has_desktop is False


class TestUserInfo:
    def test_default_user_info(self):
        info = UserInfo()
        assert info.personal_info.name == ""
        assert len(info.education) == 0
        assert len(info.get_missing_fields()) > 0

    def test_load_json(self, tmp_path):
        data = {
            "personal_info": {"name": "测试", "gender": "男", "phone": "123", "email": "a@b.com"},
            "education": [{"school": "北大", "degree": "硕士", "major": "CS"}],
        }
        json_file = tmp_path / "info.json"
        json_file.write_text(json.dumps(data, ensure_ascii=False))
        info = load_user_info(str(json_file))
        assert info.personal_info.name == "测试"
        assert len(info.education) == 1
        assert info.education[0].school == "北大"

    def test_load_nonexistent(self):
        info = load_user_info("/nonexistent/path.json")
        assert info.personal_info.name == ""

    def test_missing_fields(self):
        info = UserInfo()
        missing = info.get_missing_fields()
        assert "姓名" in missing
        assert "性别" in missing
        assert "手机号" in missing
        assert "邮箱" in missing
        assert "教育经历" in missing

    def test_to_summary(self):
        info = UserInfo(personal_info=PersonalInfo(name="张三", gender="男"))
        summary = info.to_summary()
        assert "张三" in summary
        assert "男" in summary

    def test_parse_text_info(self):
        content = """# 个人信息
姓名：李四
性别：女
手机：13900139000
邮箱：lisi@test.com

# 教育经历
学校：清华大学
学历：本科
专业：计算机"""
        info = _parse_text_info(content)
        assert info.personal_info.name == "李四"
        assert info.personal_info.gender == "女"


class TestSanitizeAgentName:
    def test_ascii_name(self):
        assert sanitize_agent_name("Google") == "Google"

    def test_chinese_name(self):
        result = sanitize_agent_name("字节跳动")
        assert result.startswith("company_")
        assert all(c.isalnum() or c == "_" for c in result)

    def test_mixed_name(self):
        assert sanitize_agent_name("Alibaba Group") == "Alibaba_Group"

    def test_starts_with_digit(self):
        result = sanitize_agent_name("123Company")
        assert result.startswith("agent_")


class TestCompanyState:
    def test_default_values(self):
        cs = CompanyState(company_name="测试公司")
        assert cs.status == "pending"
        assert cs.submitted is False
        assert cs.form_filled is False
        assert cs.use_resume_parser is None

    def test_with_values(self):
        cs = CompanyState(
            company_name="字节跳动",
            referral_code="ABC123",
            job_keywords="AI算法",
            preferred_cities=["北京", "上海"],
        )
        assert cs.referral_code == "ABC123"
        assert cs.job_keywords == "AI算法"
        assert len(cs.preferred_cities) == 2


class TestAgentCreation:
    def test_search_agent(self):
        agent = create_search_agent("Google")
        assert "Search_Google" == agent.name
        assert len(agent.tools) == 5

    def test_form_agent(self):
        agent = create_form_agent("Google")
        assert "Form_Google" == agent.name
        assert len(agent.tools) == 11

    def test_orchestrator(self):
        info = UserInfo(personal_info=PersonalInfo(name="测试"))
        companies = [CompanyState(company_name="Google")]
        orch = create_orchestrator(info, companies)
        assert orch.name == "Orchestrator"
        assert len(orch.handoffs) == 2

    def test_orchestrator_multiple_companies(self):
        info = UserInfo(personal_info=PersonalInfo(name="测试"))
        companies = [
            CompanyState(company_name="Google"),
            CompanyState(company_name="Meta"),
        ]
        orch = create_orchestrator(info, companies)
        assert len(orch.handoffs) == 4


class TestAppContext:
    def test_default_context(self):
        ctx = AppContext()
        assert len(ctx.companies) == 0
        assert ctx.current_company_index == 0

    def test_context_with_companies(self):
        companies = [CompanyState(company_name="A"), CompanyState(company_name="B")]
        ctx = AppContext(companies=companies)
        assert len(ctx.companies) == 2
