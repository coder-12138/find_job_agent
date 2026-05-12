from dataclasses import dataclass, field
from typing import Any

from job_application_agent.user_info.parser import UserInfo


@dataclass
class CompanyState:
    company_name: str
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
