import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class AgentMemory(BaseModel):
    """Agent 持久化记忆结构"""

    source_user_info: dict[str, Any] = Field(default_factory=dict)
    learned_fields: dict[str, Any] = Field(default_factory=dict)
    field_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    company_history: list[dict[str, Any]] = Field(default_factory=list)

    def get_field(self, field_name: str) -> Any:
        """获取字段值，优先从 learned_fields 查找，再从 source_user_info 查找"""
        if field_name in self.learned_fields and self.learned_fields[field_name]:
            return self.learned_fields[field_name]

        if field_name in self.source_user_info and self.source_user_info[field_name]:
            return self.source_user_info[field_name]

        return None

    def set_field(self, field_name: str, value: Any, reason: str = "") -> None:
        """记录用户补充的字段，附带原因和timestamp"""
        self.learned_fields[field_name] = value
        self.field_metadata[field_name] = {
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
        }

    def has_field(self, field_name: str) -> bool:
        """检查是否有某个字段的值（包括 source 和 learned）"""
        return self.get_field(field_name) is not None

    def to_display_dict(self) -> dict[str, Any]:
        """返回用于展示的记忆内容"""
        return {
            "source_user_info": self.source_user_info,
            "learned_fields": self.learned_fields,
            "field_metadata": self.field_metadata,
        }


def load_memory(memory_file_path: str, user_info_dict: dict[str, Any] | None = None) -> AgentMemory:
    """加载记忆，如果不存在则创建新的

    Args:
        memory_file_path: 记忆文件路径
        user_info_dict: 从用户信息文档解析出的原始信息
    """
    memory = AgentMemory()

    if user_info_dict:
        memory.source_user_info = user_info_dict

    path = Path(memory_file_path)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = AgentMemory.model_validate(data)
            memory.learned_fields = loaded.learned_fields
            memory.field_metadata = loaded.field_metadata
            memory.company_history = loaded.company_history
        except Exception as e:
            print(f"[记忆] 加载记忆文件失败: {e}，将创建新的记忆")

    return memory


def save_memory(memory: AgentMemory, memory_file_path: str) -> bool:
    """保存记忆到本地文件"""
    try:
        path = Path(memory_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(memory.model_dump(), f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[记忆] 保存记忆失败: {e}")
        return False


def user_info_to_dict(user_info) -> dict[str, Any]:
    """将 UserInfo 对象转换为扁平化的字典，用于记忆存储"""
    result: dict[str, Any] = {}

    pi = user_info.personal_info
    result["name"] = pi.name
    result["english_name"] = pi.english_name
    result["gender"] = pi.gender
    result["birthday"] = pi.birthday
    result["phone"] = pi.phone
    result["email"] = pi.email
    result["id_type"] = pi.id_type
    result["id_number"] = pi.id_number
    result["nationality"] = pi.nationality
    result["ethnicity"] = pi.ethnicity
    result["political_status"] = pi.political_status
    result["marital_status"] = pi.marital_status
    result["wechat"] = pi.wechat
    result["qq"] = pi.qq
    result["province"] = pi.province
    result["city"] = pi.city
    result["address"] = pi.address
    result["zip_code"] = pi.zip_code
    result["household_registration"] = pi.household_registration
    result["household_type"] = pi.household_type
    result["native_place"] = pi.native_place
    result["source_place"] = pi.source_place
    result["current_city"] = pi.current_city
    result["blood_type"] = pi.blood_type
    result["health_status"] = pi.health_status
    result["gaokao_date"] = pi.gaokao_date
    result["emergency_contact"] = pi.emergency_contact
    result["emergency_contact_phone"] = pi.emergency_contact_phone
    result["emergency_contact_relation"] = pi.emergency_contact_relation
    result["height"] = pi.height
    result["weight"] = pi.weight

    if user_info.job_intentions:
        result["job_intentions"] = user_info.job_intentions

    if user_info.education:
        result["education"] = [edu.model_dump() for edu in user_info.education]

    if user_info.work_experience:
        result["work_experience"] = [work.model_dump() for work in user_info.work_experience]

    if user_info.project_experience:
        result["project_experience"] = [proj.model_dump() for proj in user_info.project_experience]

    if user_info.awards:
        result["awards"] = [award.model_dump() for award in user_info.awards]

    if user_info.publications:
        result["publications"] = [pub.model_dump() for pub in user_info.publications]

    if user_info.skills:
        result["skills"] = [skill.model_dump() for skill in user_info.skills]

    result["self_introduction"] = user_info.self_introduction
    result["resume_file_path"] = user_info.resume_file_path

    if user_info.extra_fields:
        result.update(user_info.extra_fields)

    return result
