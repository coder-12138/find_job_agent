"""JD 驱动的简历自适应润色模块。

根据目标岗位 JD，对用户简历内容进行 LLM 动态润色，突出与岗位相关的内容，
提升竞争力。润色遵循「只改写/重排/强调已有内容，绝不编造」的原则。
"""

from job_application_agent_langchain.resume_polish.polisher import polish_resume

__all__ = ["polish_resume"]
