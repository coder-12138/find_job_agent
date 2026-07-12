"""批量缺失字段记忆流程的测试。

覆盖 Task 6 的验证点：
1. record_missing_field / get_missing_fields 上下文记录与读取
2. check_field_in_memory 字段命中（FIELD_FOUND）
3. check_field_in_memory 字段缺失（FIELD_MISSING）并记录到缺失列表
4. AgentMemory 持久化（set_field + save_memory + load_memory）
5. 记忆复用（保存后下次 get_field 可读到）
6. request_missing_fields 收集用户答案并写入记忆（使用 mock emitter）
"""

import asyncio
import json
import os
import tempfile

import pytest

from job_application_agent_langchain.agents.company_agent import (
    _emitter_ctx,
    _memory_ctx,
    _missing_fields_ctx,
    clear_missing_fields,
    get_missing_fields,
    record_missing_field,
    request_missing_fields,
)
from job_application_agent_langchain.agents.form import check_field_in_memory
from job_application_agent_langchain.memory import AgentMemory, load_memory, save_memory


# ============================================================================
# 辅助：模拟事件发射器，request_missing_fields 返回预设字段值
# ============================================================================


class MockEmitter:
    """模拟事件发射器，仅实现 request_missing_fields 用于批量补充测试"""

    def __init__(self, answers: dict):
        self._answers = answers
        # 捕获调用参数，供测试断言
        self.captured_fields = None
        self.captured_request_id = None

    async def request_missing_fields(self, request_id: str, fields: list[dict]) -> dict:
        self.captured_request_id = request_id
        self.captured_fields = fields
        return dict(self._answers)


# ============================================================================
# 测试夹具：管理 contextvar 的设置与还原，确保测试间隔离
# ============================================================================


@pytest.fixture
def missing_fields_ctx():
    """初始化缺失字段上下文为空列表，测试结束后还原"""
    token = _missing_fields_ctx.set([])
    yield
    _missing_fields_ctx.reset(token)


@pytest.fixture
def memory_ctx():
    """设置记忆上下文为空 AgentMemory，测试结束后还原。返回 memory 供测试使用"""
    memory = AgentMemory()
    token = _memory_ctx.set(memory)
    yield memory
    _memory_ctx.reset(token)


@pytest.fixture
def emitter_ctx():
    """设置 mock emitter 上下文，测试结束后还原。返回 emitter 供测试使用"""
    emitter = MockEmitter({"phone": "13800138000"})
    token = _emitter_ctx.set(emitter)
    yield emitter
    _emitter_ctx.reset(token)


# ============================================================================
# 测试 1: record_missing_field 与 get_missing_fields
# ============================================================================


def test_record_and_collect_missing_fields(missing_fields_ctx):
    # 初始为空
    assert get_missing_fields() == []

    # 记录第一个缺失字段
    record_missing_field("phone", "手机号", "必填项缺失")
    fields = get_missing_fields()
    assert len(fields) == 1
    assert fields[0]["name"] == "phone"
    assert fields[0]["label"] == "手机号"
    assert fields[0]["reason"] == "必填项缺失"

    # 记录第二个缺失字段
    record_missing_field("email", "邮箱", "必填项缺失")
    assert len(get_missing_fields()) == 2

    # 验证去重：重复记录同一字段不应增加
    record_missing_field("phone", "手机号", "重复记录")
    assert len(get_missing_fields()) == 2

    # 验证 clear_missing_fields 清空
    clear_missing_fields()
    assert get_missing_fields() == []


# ============================================================================
# 测试 2: check_field_in_memory 字段命中
# ============================================================================


def test_check_field_in_memory_found(memory_ctx, missing_fields_ctx):
    # 在记忆中预设字段
    memory_ctx.set_field("name", "张三", reason="已有信息")

    result = asyncio.run(
        check_field_in_memory.ainvoke({"field_name": "name", "field_label": "姓名"})
    )

    assert result.startswith("FIELD_FOUND")
    assert "name" in result
    assert "张三" in result
    # 字段命中时不应记录到缺失列表
    assert get_missing_fields() == []


# ============================================================================
# 测试 3: check_field_in_memory 字段缺失并记录到缺失列表
# ============================================================================


def test_check_field_in_memory_missing_records(memory_ctx, missing_fields_ctx):
    # memory 为空，phone 不在记忆中
    result = asyncio.run(
        check_field_in_memory.ainvoke({"field_name": "phone", "field_label": "手机号"})
    )

    assert result.startswith("FIELD_MISSING")
    assert "phone" in result
    # 验证已记录到缺失字段列表
    fields = get_missing_fields()
    assert len(fields) == 1
    assert fields[0]["name"] == "phone"
    assert fields[0]["label"] == "手机号"


# ============================================================================
# 测试 4: AgentMemory 持久化（set_field + save_memory + load_memory）
# ============================================================================


def test_memory_persistence():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name
    try:
        memory = AgentMemory()
        memory.set_field("phone", "13800138000", reason="用户补充")
        memory.set_field("email", "test@example.com", reason="用户补充")
        memory.company_history = [{"company": "TestCo"}]

        assert save_memory(memory, temp_path) is True

        # 重新加载，验证字段与元数据
        loaded = load_memory(temp_path)
        assert loaded.get_field("phone") == "13800138000"
        assert loaded.get_field("email") == "test@example.com"
        assert loaded.field_metadata["phone"]["reason"] == "用户补充"
        assert "timestamp" in loaded.field_metadata["phone"]
        assert len(loaded.company_history) == 1
    finally:
        os.unlink(temp_path)


# ============================================================================
# 测试 5: 记忆复用（保存后下次运行可读取）
# ============================================================================


def test_memory_reuse():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name
    try:
        # 第一次运行：写入字段并保存
        memory1 = AgentMemory()
        memory1.set_field("wechat", "wx_test_123", reason="第一次补充")
        assert save_memory(memory1, temp_path) is True

        # 第二次运行：加载记忆并读取（模拟下次运行复用）
        memory2 = load_memory(temp_path)
        assert memory2.get_field("wechat") == "wx_test_123"
        # learned_fields 应包含保存的字段
        assert "wechat" in memory2.learned_fields
        assert memory2.learned_fields["wechat"] == "wx_test_123"
    finally:
        os.unlink(temp_path)


# ============================================================================
# 测试 6: request_missing_fields 收集用户答案并写入记忆
# ============================================================================


def test_request_missing_fields_saves_to_memory(
    memory_ctx, missing_fields_ctx, emitter_ctx
):
    # 预设一个缺失字段
    record_missing_field("phone", "手机号", "必填项缺失")

    result = asyncio.run(request_missing_fields.ainvoke({}))

    # 验证返回结果包含用户答案
    parsed = json.loads(result)
    assert parsed["fields"]["phone"] == "13800138000"

    # 验证 emitter 收到了字段请求
    assert emitter_ctx.captured_fields is not None
    assert len(emitter_ctx.captured_fields) == 1
    assert emitter_ctx.captured_fields[0]["name"] == "phone"
    assert emitter_ctx.captured_request_id is not None

    # 验证答案已保存到记忆（通过 set_field 写入 learned_fields）
    assert memory_ctx.get_field("phone") == "13800138000"
    assert "phone" in memory_ctx.learned_fields
