import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    rank: str = ""


class WorkExperience(BaseModel):
    company: str = ""
    position: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class ProjectExperience(BaseModel):
    name: str = ""
    role: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    url: str = ""


class Award(BaseModel):
    name: str = ""
    level: str = ""
    date: str = ""
    description: str = ""


class Skill(BaseModel):
    name: str = ""
    level: str = ""


class PersonalInfo(BaseModel):
    name: str = ""
    gender: str = ""
    birthday: str = ""
    phone: str = ""
    email: str = ""
    id_number: str = ""
    nationality: str = ""
    ethnicity: str = ""
    political_status: str = ""
    marital_status: str = ""
    height: str = ""
    weight: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    zip_code: str = ""
    website: str = ""
    wechat: str = ""


class UserInfo(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education: list[Education] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    project_experience: list[ProjectExperience] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    self_introduction: str = ""
    resume_file_path: str = ""
    extra_fields: dict[str, Any] = Field(default_factory=dict)

    def get_missing_fields(self) -> list[str]:
        missing = []
        pi = self.personal_info
        if not pi.name:
            missing.append("姓名")
        if not pi.gender:
            missing.append("性别")
        if not pi.phone:
            missing.append("手机号")
        if not pi.email:
            missing.append("邮箱")
        if not self.education:
            missing.append("教育经历")
        return missing

    def to_summary(self) -> str:
        parts = []
        pi = self.personal_info
        parts.append(f"姓名: {pi.name}")
        parts.append(f"性别: {pi.gender}")
        parts.append(f"手机: {pi.phone}")
        parts.append(f"邮箱: {pi.email}")
        if pi.birthday:
            parts.append(f"出生日期: {pi.birthday}")
        if pi.id_number:
            parts.append(f"身份证号: {pi.id_number}")

        if self.education:
            parts.append("\n教育经历:")
            for edu in self.education:
                parts.append(
                    f"  {edu.school} - {edu.major} - {edu.degree} "
                    f"({edu.start_date} ~ {edu.end_date})"
                )
                if edu.gpa:
                    parts.append(f"  GPA: {edu.gpa}")

        if self.work_experience:
            parts.append("\n工作经历:")
            for work in self.work_experience:
                parts.append(
                    f"  {work.company} - {work.position} "
                    f"({work.start_date} ~ {work.end_date})"
                )

        if self.project_experience:
            parts.append("\n项目经历:")
            for proj in self.project_experience:
                parts.append(
                    f"  {proj.name} - {proj.role} "
                    f"({proj.start_date} ~ {proj.end_date})"
                )

        if self.awards:
            parts.append("\n获奖经历:")
            for award in self.awards:
                parts.append(f"  {award.name} - {award.level} ({award.date})")

        if self.skills:
            parts.append("\n技能:")
            for skill in self.skills:
                parts.append(f"  {skill.name}: {skill.level}")

        if self.self_introduction:
            parts.append(f"\n自我介绍: {self.self_introduction}")

        return "\n".join(parts)


def load_user_info(personal_info_path: str, resume_path: str = "") -> UserInfo:
    info = UserInfo()
    path = Path(personal_info_path)

    if not path.exists():
        return info

    if path.suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        info = UserInfo.model_validate(data)
    elif path.suffix in (".txt", ".md"):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        info = _parse_text_info(content)

    if resume_path and os.path.exists(resume_path):
        info.resume_file_path = os.path.abspath(resume_path)

    return info


def _parse_text_info(content: str) -> UserInfo:
    info = UserInfo()
    lines = content.strip().split("\n")
    current_section = ""
    current_item: dict[str, Any] = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("#"):
            current_section = line.lstrip("#").strip()
            continue

        if ":" in line or "：" in line:
            sep = "：" if "：" in line else ":"
            key, value = line.split(sep, 1)
            key = key.strip()
            value = value.strip()

            if current_section == "" or current_section in ("个人信息", "基本"):
                _set_personal_info(info.personal_info, key, value)
            elif current_section in ("教育", "教育经历"):
                if key in ("学校", "院校"):
                    if current_item:
                        info.education.append(Education(**current_item))
                    current_item = {"school": value}
                else:
                    _set_education_field(current_item, key, value)
            elif current_section in ("工作", "工作经历", "实习", "实习经历"):
                if key in ("公司", "单位"):
                    if current_item:
                        info.work_experience.append(WorkExperience(**current_item))
                    current_item = {"company": value}
                else:
                    _set_work_field(current_item, key, value)

    if current_item:
        if current_section in ("教育", "教育经历"):
            info.education.append(Education(**current_item))
        elif current_section in ("工作", "工作经历", "实习", "实习经历"):
            info.work_experience.append(WorkExperience(**current_item))

    return info


def _set_personal_info(pi: PersonalInfo, key: str, value: str):
    mapping = {
        "姓名": "name", "名字": "name",
        "性别": "gender",
        "出生日期": "birthday", "生日": "birthday",
        "手机": "phone", "电话": "phone", "手机号": "phone",
        "邮箱": "email", "邮件": "email",
        "身份证": "id_number", "身份证号": "id_number",
        "国籍": "nationality",
        "民族": "ethnicity",
        "政治面貌": "political_status",
        "婚姻状况": "marital_status",
        "身高": "height",
        "体重": "weight",
        "省": "province", "省份": "province",
        "市": "city", "城市": "city",
        "地址": "address",
        "邮编": "zip_code",
        "微信": "wechat",
    }
    if key in mapping:
        setattr(pi, mapping[key], value)


def _set_education_field(item: dict, key: str, value: str):
    mapping = {
        "学校": "school", "院校": "school",
        "学历": "degree", "学位": "degree",
        "专业": "major",
        "开始": "start_date", "入学": "start_date",
        "结束": "end_date", "毕业": "end_date",
        "GPA": "gpa", "绩点": "gpa",
        "排名": "rank",
    }
    if key in mapping:
        item[mapping[key]] = value


def _set_work_field(item: dict, key: str, value: str):
    mapping = {
        "公司": "company", "单位": "company",
        "职位": "position", "岗位": "position",
        "开始": "start_date", "入职": "start_date",
        "结束": "end_date", "离职": "end_date",
        "描述": "description", "内容": "description",
    }
    if key in mapping:
        item[mapping[key]] = value
