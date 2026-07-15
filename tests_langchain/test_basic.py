import pytest

from job_application_agent_langchain.config import Settings
from job_application_agent_langchain.context import CompanyState, RECRUITMENT_TYPES
from job_application_agent_langchain.utils import sanitize_agent_name


class TestUtils:
    def test_sanitize_agent_name_ascii(self):
        assert sanitize_agent_name("ByteDance") == "ByteDance"
        assert sanitize_agent_name("Company 123") == "Company_123"

    def test_sanitize_agent_name_chinese(self):
        result = sanitize_agent_name("字节跳动")
        assert result.startswith("company_")

    def test_sanitize_agent_name_mixed(self):
        assert sanitize_agent_name("腾讯Tencent") == "Tencent"

    def test_sanitize_agent_name_starts_with_digit(self):
        result = sanitize_agent_name("123Company")
        assert result.startswith("agent_")


class TestContext:
    def test_company_state_default(self):
        company = CompanyState(company_name="TestCo")
        assert company.recruitment_type == "校招"
        assert company.status == "pending"
        assert company.submitted is False

    def test_recruitment_types(self):
        assert "校招" in RECRUITMENT_TYPES
        assert "社招" in RECRUITMENT_TYPES
        assert len(RECRUITMENT_TYPES) == 4


class TestConfig:
    def test_settings_singleton(self):
        s1 = Settings()
        s2 = Settings()
        assert s1 is s2

    def test_validate_empty_api_key(self):
        settings = Settings()
        original_key = settings.openai_api_key
        settings.openai_api_key = ""
        errors = settings.validate()
        assert any("OPENAI_API_KEY" in e for e in errors)
        settings.openai_api_key = original_key
