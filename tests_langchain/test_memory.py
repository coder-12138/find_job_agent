import os
import tempfile
import pytest

from job_application_agent_langchain.memory import (
    AgentMemory,
    load_memory,
    save_memory,
    user_info_to_dict,
)
from job_application_agent_langchain.user_info.parser import UserInfo, PersonalInfo


class TestAgentMemory:
    def test_get_field_priority(self):
        memory = AgentMemory()
        memory.source_user_info = {"name": "原始姓名", "phone": "123456"}
        memory.learned_fields = {"name": "更新姓名"}

        assert memory.get_field("name") == "更新姓名"
        assert memory.get_field("phone") == "123456"
        assert memory.get_field("nonexistent") is None

    def test_set_field(self):
        memory = AgentMemory()
        memory.set_field("height", "180cm", reason="用户补充")

        assert memory.learned_fields["height"] == "180cm"
        assert "height" in memory.field_metadata
        assert memory.field_metadata["height"]["reason"] == "用户补充"
        assert "timestamp" in memory.field_metadata["height"]

    def test_has_field(self):
        memory = AgentMemory()
        memory.source_user_info = {"email": "test@example.com"}

        assert memory.has_field("email") is True
        assert memory.has_field("nonexistent") is False

        memory.set_field("new_field", "value")
        assert memory.has_field("new_field") is True


class TestMemoryPersistence:
    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            memory = AgentMemory()
            memory.source_user_info = {"name": "测试"}
            memory.set_field("height", "175cm", reason="测试")
            memory.company_history = [{"company": "TestCo"}]

            assert save_memory(memory, temp_path) is True

            loaded = load_memory(temp_path, user_info_dict={"name": "新测试"})
            assert loaded.get_field("height") == "175cm"
            assert loaded.get_field("name") == "新测试"
            assert len(loaded.company_history) == 1
        finally:
            os.unlink(temp_path)

    def test_load_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nonexistent.json")
            memory = load_memory(path, user_info_dict={"name": "测试"})
            assert memory.get_field("name") == "测试"


class TestUserInfoToDict:
    def test_conversion(self):
        user_info = UserInfo()
        user_info.personal_info.name = "张三"
        user_info.personal_info.phone = "13800138000"
        user_info.job_intentions = ["算法工程师"]

        result = user_info_to_dict(user_info)

        assert result["name"] == "张三"
        assert result["phone"] == "13800138000"
        assert result["job_intentions"] == ["算法工程师"]
