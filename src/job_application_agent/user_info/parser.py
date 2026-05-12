import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PersonalInfo(BaseModel):
    name: str = ""
    english_name: str = ""
    gender: str = ""
    birthday: str = ""
    phone: str = ""
    email: str = ""
    id_type: str = ""
    id_number: str = ""
    nationality: str = ""
    ethnicity: str = ""
    political_status: str = ""
    marital_status: str = ""
    wechat: str = ""
    qq: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    zip_code: str = ""
    website: str = ""
    household_registration: str = ""
    household_type: str = ""
    native_place: str = ""
    source_place: str = ""
    current_city: str = ""
    blood_type: str = ""
    health_status: str = ""
    gaokao_date: str = ""
    emergency_contact: str = ""
    emergency_contact_phone: str = ""
    emergency_contact_relation: str = ""
    height: str = ""
    weight: str = ""


class Education(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    rank: str = ""
    student_id: str = ""
    duration: str = ""
    location: str = ""
    training_mode: str = ""
    college: str = ""
    orientation_type: str = ""
    school_level: str = ""
    is_recommended: str = ""


class WorkExperience(BaseModel):
    company: str = ""
    position: str = ""
    department: str = ""
    start_date: str = ""
    end_date: str = ""
    location: str = ""
    description: str = ""


class ProjectExperience(BaseModel):
    name: str = ""
    role: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""
    url: str = ""
    organization: str = ""


class Award(BaseModel):
    name: str = ""
    level: str = ""
    date: str = ""
    description: str = ""
    issuer: str = ""


class Publication(BaseModel):
    title: str = ""
    conference: str = ""
    date: str = ""
    form: str = ""
    description: str = ""


class Skill(BaseModel):
    name: str = ""
    level: str = ""


class UserInfo(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    job_intentions: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    project_experience: list[ProjectExperience] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
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
        if pi.english_name:
            parts.append(f"英文名: {pi.english_name}")
        parts.append(f"性别: {pi.gender}")
        parts.append(f"手机: {pi.phone}")
        parts.append(f"邮箱: {pi.email}")
        if pi.birthday:
            parts.append(f"出生日期: {pi.birthday}")
        if pi.id_number:
            parts.append(f"证件号码: {pi.id_number}")
        if pi.ethnicity:
            parts.append(f"民族: {pi.ethnicity}")
        if pi.political_status:
            parts.append(f"政治面貌: {pi.political_status}")
        if pi.household_registration:
            parts.append(f"户籍: {pi.household_registration}")
        if pi.native_place:
            parts.append(f"籍贯: {pi.native_place}")
        if pi.current_city:
            parts.append(f"现居住城市: {pi.current_city}")

        if self.job_intentions:
            parts.append(f"\n求职意向: {', '.join(self.job_intentions)}")

        if self.education:
            parts.append("\n教育经历:")
            for edu in self.education:
                parts.append(
                    f"  {edu.school} - {edu.major} - {edu.degree} "
                    f"({edu.start_date} ~ {edu.end_date})"
                )
                if edu.gpa:
                    parts.append(f"  GPA: {edu.gpa}")
                if edu.rank:
                    parts.append(f"  排名: {edu.rank}")
                if edu.college:
                    parts.append(f"  学院: {edu.college}")

        if self.work_experience:
            parts.append("\n实习/工作经历:")
            for work in self.work_experience:
                parts.append(
                    f"  {work.company} - {work.position} "
                    f"({work.start_date} ~ {work.end_date})"
                )
                if work.department:
                    parts.append(f"  部门: {work.department}")
                if work.description:
                    parts.append(f"  内容: {work.description[:200]}")

        if self.project_experience:
            parts.append("\n项目经历:")
            for proj in self.project_experience:
                parts.append(f"  {proj.name}")
                if proj.description:
                    parts.append(f"  描述: {proj.description[:200]}")

        if self.awards:
            parts.append("\n获奖经历:")
            for award in self.awards:
                parts.append(f"  {award.name} - {award.level} ({award.date})")

        if self.publications:
            parts.append("\n论文:")
            for pub in self.publications:
                parts.append(f"  {pub.title}")
                if pub.conference:
                    parts.append(f"  会议: {pub.conference}")

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
        info = parse_txt_info(content)

    if resume_path and os.path.exists(resume_path):
        info.resume_file_path = os.path.abspath(resume_path)

    return info


def parse_txt_info(content: str) -> UserInfo:
    info = UserInfo()
    lines = content.split("\n")
    current_section = ""
    current_subsection = ""
    current_item: dict[str, Any] = {}
    current_item_lines: list[str] = []
    item_index = 0

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1

        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("## "):
            _flush_current_item(info, current_section, current_item, current_item_lines, item_index)
            current_subsection = stripped[3:].strip()
            current_item = {"_subsection": current_subsection}
            current_item_lines = []
            item_index = 0
            continue

        if stripped.startswith("# "):
            _flush_current_item(info, current_section, current_item, current_item_lines, item_index)
            current_section = stripped[2:].strip()
            current_subsection = ""
            current_item = {}
            current_item_lines = []
            item_index = 0
            continue

        numbered_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if numbered_match and current_section in ("奖惩情况", "论文和著作"):
            _flush_current_item(info, current_section, current_item, current_item_lines, item_index)
            current_item = {}
            current_item_lines = []
            item_index = int(numbered_match.group(1))
            current_item["_title"] = numbered_match.group(2).strip()
            continue

        if current_section in ("基础信息", "基本信息", "基本"):
            _parse_basic_field(info.personal_info, stripped)

        elif current_section == "求职意向":
            if stripped and not stripped.startswith("#"):
                info.job_intentions.append(stripped)

        elif current_section == "教育经历" and current_subsection:
            _parse_education_field(current_item, stripped)

        elif current_section == "实习经历" and current_subsection:
            _parse_work_field(current_item, stripped, current_item_lines)

        elif current_section in ("项目经历", "项目经历/实践活动", "实践活动") and current_subsection:
            _parse_project_field(current_item, stripped, current_item_lines)

        elif current_section == "奖惩情况":
            _parse_award_field(current_item, stripped)

        elif current_section == "论文和著作":
            _parse_publication_field(current_item, stripped, current_item_lines)

        elif current_section == "技能":
            if "：" in stripped or ":" in stripped:
                sep = "：" if "：" in stripped else ":"
                name, level = stripped.split(sep, 1)
                info.skills.append(Skill(name=name.strip(), level=level.strip()))

    _flush_current_item(info, current_section, current_item, current_item_lines, item_index)

    return info


def _flush_current_item(
    info: UserInfo,
    section: str,
    item: dict,
    item_lines: list[str],
    index: int,
):
    if not item and not item_lines:
        return

    if section == "教育经历" and ("school" in item or "_subsection" in item):
        school = item.pop("_subsection", "")
        if school and "school" not in item:
            item["school"] = school
        if "school" in item:
            info.education.append(Education(**{k: v for k, v in item.items() if not k.startswith("_")}))

    elif section == "实习经历" and ("company" in item or "_subsection" in item):
        company = item.pop("_subsection", "")
        if company and "company" not in item:
            item["company"] = company
        if "company" in item or item_lines:
            if item_lines:
                item["description"] = "\n".join(item_lines)
            if "company" not in item:
                item["company"] = company
            info.work_experience.append(WorkExperience(**{k: v for k, v in item.items() if not k.startswith("_")}))

    elif section in ("项目经历", "项目经历/实践活动", "实践活动") and ("name" in item or "_subsection" in item):
        name = item.pop("_subsection", "")
        if name and "name" not in item:
            item["name"] = name
        if item_lines:
            item["description"] = "\n".join(item_lines)
        if "name" in item:
            info.project_experience.append(ProjectExperience(**{k: v for k, v in item.items() if not k.startswith("_")}))

    elif section == "奖惩情况" and item:
        if "_title" in item:
            item["name"] = item.pop("_title")
        if "name" in item:
            info.awards.append(Award(**{k: v for k, v in item.items() if not k.startswith("_")}))

    elif section == "论文和著作" and item:
        if "_title" in item:
            item["title"] = item.pop("_title")
        if item_lines:
            item["description"] = "\n".join(item_lines)
        if "title" in item:
            info.publications.append(Publication(**{k: v for k, v in item.items() if not k.startswith("_")}))


def _parse_basic_field(pi: PersonalInfo, line: str):
    mapping: dict[str, str] = {
        "姓名": "name", "名字": "name",
        "英文名": "english_name",
        "性别": "gender",
        "出生日期": "birthday", "生日": "birthday",
        "手机": "phone", "电话": "phone", "手机号": "phone",
        "邮箱": "email", "邮件": "email",
        "证件号码类型": "id_type",
        "证件号码": "id_number", "身份证": "id_number", "身份证号": "id_number",
        "国籍": "nationality",
        "民族": "ethnicity",
        "政治面貌": "political_status",
        "婚姻状况": "marital_status",
        "微信": "wechat", "微信号": "wechat",
        "QQ": "qq",
        "省": "province", "省份": "province",
        "市": "city", "城市": "city",
        "地址": "address",
        "邮编": "zip_code", "邮政编码": "zip_code",
        "户籍": "household_registration",
        "户籍类型": "household_type",
        "籍贯": "native_place",
        "生源地": "source_place",
        "现居住城市": "current_city",
        "血型": "blood_type",
        "健康状况": "health_status",
        "高考时间": "gaokao_date",
        "紧急联系人": "emergency_contact",
        "紧急联系人电话": "emergency_contact_phone",
        "与紧急联系人关系": "emergency_contact_relation",
        "身高": "height",
        "体重": "weight",
    }

    if "：" in line or ":" in line:
        sep = "：" if "：" in line else ":"
        key, value = line.split(sep, 1)
        key = key.strip()
        value = value.strip()
        if key in mapping:
            setattr(pi, mapping[key], value)


def _parse_education_field(item: dict, line: str):
    mapping: dict[str, str] = {
        "就读时间": "study_period",
        "专业": "major",
        "学号": "student_id",
        "学制": "duration",
        "就读地点": "location",
        "学历": "degree",
        "培养方式": "training_mode",
        "学院": "college",
        "定向类型": "orientation_type",
        "GPA": "gpa", "绩点": "gpa",
        "排名": "rank",
        "是否保研": "is_recommended",
        "是否保送": "is_recommended",
        "院校层次": "school_level",
        "学位": "degree",
    }

    if "：" in line or ":" in line:
        sep = "：" if "：" in line else ":"
        key, value = line.split(sep, 1)
        key = key.strip()
        value = value.strip()

        if key in mapping:
            field = mapping[key]
            if field == "study_period":
                parts = re.split(r"\s*至\s*", value)
                if len(parts) == 2:
                    item["start_date"] = parts[0].strip()
                    item["end_date"] = parts[1].strip()
            else:
                item[field] = value


def _parse_work_field(item: dict, line: str, item_lines: list[str]):
    mapping: dict[str, str] = {
        "实习时间": "work_period",
        "部门": "department",
        "实习地点": "location",
        "岗位": "position",
        "工作内容": "_content_start",
    }

    if "：" in line or ":" in line:
        sep = "：" if "：" in line else ":"
        key, value = line.split(sep, 1)
        key = key.strip()
        value = value.strip()

        if key in mapping:
            field = mapping[key]
            if field == "work_period":
                parts = re.split(r"\s*至\s*", value)
                if len(parts) == 2:
                    item["start_date"] = parts[0].strip()
                    item["end_date"] = parts[1].strip()
            elif field == "_content_start":
                if value:
                    item_lines.append(value)
            else:
                item[field] = value
    elif re.match(r"^\d+\.\s", line.strip()):
        item_lines.append(line.strip())


def _parse_project_field(item: dict, line: str, item_lines: list[str]):
    mapping: dict[str, str] = {
        "开展时间": "start_date",
        "依托单位": "organization",
    }

    if "：" in line or ":" in line:
        sep = "：" if "：" in line else ":"
        key, value = line.split(sep, 1)
        key = key.strip()
        value = line[line.index(sep) + 1:].strip()

        if key in mapping:
            item[mapping[key]] = value
        elif key in ("背景&任务", "背景", "任务", "数据预处理", "方法", "核心成果", "内容"):
            item_lines.append(f"{key}: {value}")
    elif re.match(r"^\d+\.\s", line.strip()):
        item_lines.append(line.strip())


def _parse_award_field(item: dict, line: str):
    mapping: dict[str, str] = {
        "颁发单位": "issuer",
        "级别": "level",
        "奖项": "description",
        "获奖时间": "date",
    }

    if "：" in line or ":" in line:
        sep = "：" if "：" in line else ":"
        key, value = line.split(sep, 1)
        key = key.strip()
        value = value.strip()

        if key in mapping:
            item[mapping[key]] = value


def _parse_publication_field(item: dict, line: str, item_lines: list[str]):
    mapping: dict[str, str] = {
        "发表会议": "conference",
        "发表时间": "date",
        "发表形式": "form",
        "项目内容": "description",
    }

    if "：" in line or ":" in line:
        sep = "：" if "：" in line else ":"
        key, value = line.split(sep, 1)
        key = key.strip()
        value = value.strip()

        if key in mapping:
            item[mapping[key]] = value
