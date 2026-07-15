from dataclasses import dataclass, field
from typing import Any

from job_application_agent_langchain.user_info.parser import UserInfo

RECRUITMENT_TYPES = ["校招", "社招", "日常实习", "暑期实习（转正实习）"]

RECRUITMENT_TYPE_KEYWORDS = {
    "校招": ["校招", "校园招聘", "campus", "应届", "秋招", "春招"],
    "社招": ["社招", "社会招聘", "social", "社会人士", "有经验"],
    "日常实习": ["日常实习", "实习", "intern", "日常"],
    "暑期实习（转正实习）": ["暑期实习", "转正实习", "summer intern", "暑期", "转正"],
}


@dataclass
class CompanyState:
    company_name: str
    recruitment_type: str = "校招"
    referral_code: str = ""
    job_keywords: str = ""
    preferred_cities: list[str] = field(default_factory=list)
    max_positions: int = 0
    recommended_positions: list[dict[str, Any]] = field(default_factory=list)
    selected_positions: list[dict[str, Any]] = field(default_factory=list)
    volunteer_order: list[int] = field(default_factory=list)
    status: str = "pending"
    use_resume_parser: bool | None = None
    form_filled: bool = False
    submitted: bool = False
    error_message: str = ""


@dataclass
class AppContext:
    user_info: UserInfo = field(default_factory=UserInfo)
    companies: list[CompanyState] = field(default_factory=list)
    current_company_index: int = 0
    browser_page_url: str = ""
    has_desktop: bool = True
