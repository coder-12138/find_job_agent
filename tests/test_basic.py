import pytest
import os
import json

from job_application_agent.config import Settings
from job_application_agent.context import AppContext, CompanyState, RECRUITMENT_TYPES
from job_application_agent.user_info.parser import (
    UserInfo, PersonalInfo, Education, WorkExperience,
    ProjectExperience, Award, Skill, Publication,
    load_user_info, parse_txt_info,
)
from job_application_agent.utils import sanitize_agent_name
from job_application_agent.agents.search import create_search_agent
from job_application_agent.agents.form import create_form_agent
from job_application_agent.agents.orchestrator import create_orchestrator


class TestSettings:
    def test_singleton(self):
        Settings._instance = None
        s1 = Settings()
        s2 = Settings()
        assert s1 is s2

    def test_default_values(self):
        Settings._instance = None
        s = Settings()
        assert s.openai_model == "gpt-4o"
        assert s.browser_headless is True
        assert s.email_notification_enabled is False

    def test_validate_missing_api_key(self):
        Settings._instance = None
        s = Settings()
        errors = s.validate()
        assert any("OPENAI_API_KEY" in e for e in errors)

    def test_desktop_detection_linux_no_display(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", "")
        monkeypatch.setenv("WAYLAND_DISPLAY", "")
        Settings._instance = None
        s = Settings()
        assert s.has_desktop is False


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

    def test_parse_basic_info(self):
        content = """# 基础信息
姓名：李四
英文名：li si
性别：女
手机：13900139000
邮箱：lisi@test.com
出生日期：2000-01-01
民族：汉族
证件号码：1234567890
政治面貌：团员
户籍：北京
籍贯：北京市
现居住城市：北京
邮编：100000
血型：A型
紧急联系人：李五
紧急联系人电话：13800138000"""
        info = parse_txt_info(content)
        assert info.personal_info.name == "李四"
        assert info.personal_info.english_name == "li si"
        assert info.personal_info.gender == "女"
        assert info.personal_info.phone == "13900139000"
        assert info.personal_info.email == "lisi@test.com"
        assert info.personal_info.birthday == "2000-01-01"
        assert info.personal_info.ethnicity == "汉族"
        assert info.personal_info.id_number == "1234567890"
        assert info.personal_info.political_status == "团员"
        assert info.personal_info.household_registration == "北京"
        assert info.personal_info.native_place == "北京市"
        assert info.personal_info.current_city == "北京"
        assert info.personal_info.zip_code == "100000"
        assert info.personal_info.blood_type == "A型"
        assert info.personal_info.emergency_contact == "李五"
        assert info.personal_info.emergency_contact_phone == "13800138000"

    def test_parse_education(self):
        content = """# 教育经历
## 北京大学
就读时间：2022-09 至 2025-06
专业：计算机科学
学历：硕士
GPA：3.9
排名：前5%
学院：信息学院

## 清华大学
就读时间：2018-09 至 2022-06
专业：软件工程
学历：本科
GPA：3.8"""
        info = parse_txt_info(content)
        assert len(info.education) == 2
        assert info.education[0].school == "北京大学"
        assert info.education[0].major == "计算机科学"
        assert info.education[0].degree == "硕士"
        assert info.education[0].start_date == "2022-09"
        assert info.education[0].end_date == "2025-06"
        assert info.education[0].gpa == "3.9"
        assert info.education[0].rank == "前5%"
        assert info.education[0].college == "信息学院"
        assert info.education[1].school == "清华大学"
        assert info.education[1].major == "软件工程"

    def test_parse_work_experience(self):
        content = """# 实习经历
## 字节跳动
实习时间：2024-03 至 2024-09
部门：AI Lab
岗位：算法实习生
工作内容：
1. 优化推荐系统
2. 训练大模型"""
        info = parse_txt_info(content)
        assert len(info.work_experience) == 1
        assert info.work_experience[0].company == "字节跳动"
        assert info.work_experience[0].department == "AI Lab"
        assert info.work_experience[0].position == "算法实习生"
        assert info.work_experience[0].start_date == "2024-03"
        assert info.work_experience[0].end_date == "2024-09"

    def test_parse_awards(self):
        content = """# 奖惩情况
1. ACM竞赛
   级别：国家级
   奖项：金奖
   获奖时间：2023-05

2. 数学建模
   级别：省级
   奖项：一等奖
   获奖时间：2022-11"""
        info = parse_txt_info(content)
        assert len(info.awards) == 2
        assert info.awards[0].name == "ACM竞赛"
        assert info.awards[0].level == "国家级"
        assert info.awards[0].date == "2023-05"
        assert info.awards[1].name == "数学建模"

    def test_parse_publications(self):
        content = """# 论文和著作
1. Deep Learning for NLP
   发表会议：ACL 2024
   发表时间：2024-06
   发表形式：Oral"""
        info = parse_txt_info(content)
        assert len(info.publications) == 1
        assert "Deep Learning" in info.publications[0].title
        assert info.publications[0].conference == "ACL 2024"
        assert info.publications[0].date == "2024-06"

    def test_parse_job_intentions(self):
        content = """# 求职意向
算法工程师
Agent开发工程师"""
        info = parse_txt_info(content)
        assert info.job_intentions == ["算法工程师", "Agent开发工程师"]

    def test_parse_real_file(self):
        real_path = "/data3/zhuym/find_job_agent/data/personal_information.txt"
        if not os.path.exists(real_path):
            pytest.skip("Real personal info file not found")
        info = load_user_info(real_path)
        assert info.personal_info.name == "朱一鸣"
        assert info.personal_info.gender == "男"
        assert len(info.education) == 2
        assert len(info.work_experience) == 1
        assert len(info.awards) == 3
        assert len(info.publications) == 2
        assert "算法工程师" in info.job_intentions


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
        assert cs.recruitment_type == "校招"

    def test_with_values(self):
        cs = CompanyState(
            company_name="字节跳动",
            recruitment_type="社招",
            referral_code="ABC123",
            job_keywords="AI算法",
            preferred_cities=["北京", "上海"],
        )
        assert cs.recruitment_type == "社招"
        assert cs.referral_code == "ABC123"
        assert cs.job_keywords == "AI算法"
        assert len(cs.preferred_cities) == 2

    def test_recruitment_types(self):
        for rt in ["校招", "社招", "日常实习", "暑期实习（转正实习）"]:
            cs = CompanyState(company_name="测试", recruitment_type=rt)
            assert cs.recruitment_type == rt


class TestAgentCreation:
    def test_search_agent(self):
        agent = create_search_agent("Google")
        assert "Search_Google" == agent.name
        assert len(agent.tools) == 5

    def test_search_agent_with_type(self):
        agent = create_search_agent("Google", "社招")
        assert "社招" in agent.instructions

    def test_form_agent(self):
        agent = create_form_agent("Google")
        assert "Form_Google" == agent.name
        assert len(agent.tools) == 11

    def test_form_agent_with_type(self):
        agent = create_form_agent("Google", "社招")
        assert "社招" in agent.instructions

    def test_orchestrator(self):
        info = UserInfo(personal_info=PersonalInfo(name="测试"))
        companies = [CompanyState(company_name="Google")]
        orch = create_orchestrator(info, companies)
        assert orch.name == "Orchestrator"
        assert len(orch.handoffs) == 2

    def test_orchestrator_multiple_companies(self):
        info = UserInfo(personal_info=PersonalInfo(name="测试"))
        companies = [
            CompanyState(company_name="Google", recruitment_type="校招"),
            CompanyState(company_name="Meta", recruitment_type="社招"),
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
