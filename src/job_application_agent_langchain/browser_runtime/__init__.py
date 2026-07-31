"""Single-owner managed browser runtime for reviewed application tasks."""

from job_application_agent_langchain.browser_runtime.coordinator import (
    BrowserCoordinator,
    BrowserTaskResult,
)
from job_application_agent_langchain.browser_runtime.feishu import FeishuRecruitingAdapter

__all__ = ["BrowserCoordinator", "BrowserTaskResult", "FeishuRecruitingAdapter"]
