"""WebUI 上传简历到润色上下文的传递链测试。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace


def test_resume_text_is_persisted_and_reused_without_reparsing(
    monkeypatch, tmp_path
):
    from job_application_agent_langchain.user_info import parser

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"fake-pdf-for-cache-test")
    cache_path = tmp_path / "resume_text_cache.json"
    calls = []

    monkeypatch.setattr(parser, "RESUME_TEXT_CACHE_PATH", cache_path)
    monkeypatch.setattr(
        parser,
        "_extract_resume_text_uncached",
        lambda path: calls.append(path) or "PDF 中的真实简历原文",
    )

    first = parser.extract_resume_text(str(resume))
    second = parser.extract_resume_text(str(resume))

    assert first == second == "PDF 中的真实简历原文"
    assert len(calls) == 1
    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert next(iter(persisted["entries"].values()))["text"] == first


def test_uploaded_resume_is_the_only_original_review_source():
    from job_application_agent_langchain.resume_polish.polisher import _build_original
    from job_application_agent_langchain.user_info.parser import Skill, UserInfo

    info = UserInfo(
        self_introduction="仅用于本地 Web UI 功能测试",
        skills=[Skill(name="Python", level="熟悉")],
    )

    original = _build_original(
        info,
        {
            "raw_resume_text": "PDF 中的真实医疗 AI 项目经历",
            "resume_file_path": r"C:\uploads\candidate.pdf",
        },
    )

    assert original["source_resume_text"] == "PDF 中的真实医疗 AI 项目经历"
    assert original["source_resume_file"] == "candidate.pdf"
    assert original["self_introduction"] == ""
    assert original["skill_highlights"] == []
    assert "功能测试" not in json.dumps(original, ensure_ascii=False)


def test_uploaded_resume_appears_once_in_compact_polish_prompt():
    from job_application_agent_langchain.resume_polish.polisher import (
        _build_polish_prompt,
    )
    from job_application_agent_langchain.user_info.parser import Skill, UserInfo

    raw_resume = "PDF 唯一真实简历原文：医疗 AI 项目"
    info = UserInfo(
        self_introduction="仅用于本地 Web UI 功能测试",
        skills=[Skill(name="测试技能", level="测试")],
    )

    prompt = _build_polish_prompt(
        info,
        {"required_skills": ["Python"], "keywords": ["AI"]},
        {
            "raw_resume_text": raw_resume,
            "resume_file_path": "candidate.pdf",
            "agent_resume_content": raw_resume,
        },
    )

    assert prompt.count(raw_resume) == 1
    assert "Web UI 功能测试" not in prompt
    assert "测试技能" not in prompt


def test_load_user_info_reads_resume_without_personal_info_file(tmp_path):
    from job_application_agent_langchain.user_info.parser import load_user_info

    resume = tmp_path / "resume.txt"
    resume.write_text("真实项目：使用 Python 开发智能体检索系统", encoding="utf-8")

    info = load_user_info(str(tmp_path / "missing.md"), str(resume))

    assert info.resume_file_path == str(resume.resolve())
    assert "智能体检索系统" in info.extra_fields["resume_text"]
    assert "上传简历原文" in info.to_summary()


def test_web_session_uses_archived_profile_version_and_reuses_extraction(monkeypatch):
    from job_application_agent_langchain.application import legacy_profile_bridge as bridge

    pdf = b"%PDF-1.4 archived resume bytes"
    version = SimpleNamespace(
        id="version-1",
        profile_id="profile-1",
        status="active",
        source_file_resource_id="resume-1",
        fields={"full_name": "测试候选人"},
    )

    class Profiles:
        def get_active_version(self):
            return version

    class Files:
        def get_metadata(self, resource_id):
            assert resource_id == "resume-1"
            return {"original_name": "candidate.pdf"}

        def read(self, resource_id):
            assert resource_id == "resume-1"
            return pdf

    class Extractions:
        def get_or_extract(self, resource_id, source_pdf):
            assert resource_id == "resume-1"
            assert source_pdf == pdf
            return (
                {
                    "pages": [{"text": "归档提取记录中的真实简历正文"}],
                    "quality": {"page_count": 1, "character_count": 15},
                },
                False,
            )

    monkeypatch.setattr(bridge, "get_profile_service", lambda: Profiles())
    monkeypatch.setattr(bridge, "get_file_resource_service", lambda: Files())
    monkeypatch.setattr(bridge, "get_resume_extraction_service", lambda: Extractions())

    session = bridge.load_profile_for_legacy_session()
    materialized = Path(session.user_info.resume_file_path)
    try:
        assert session.profile_version_id == "version-1"
        assert session.user_info.personal_info.name == "测试候选人"
        assert session.user_info.extra_fields["resume_text"] == "归档提取记录中的真实简历正文"
        assert session.user_info.extra_fields["resume_extraction_reused"] is True
        assert materialized.read_bytes() == pdf
    finally:
        materialized.unlink(missing_ok=True)


def test_polish_tool_passes_uploaded_resume_text(monkeypatch, tmp_path):
    from job_application_agent_langchain.agents import company_agent, form
    from job_application_agent_langchain.user_info.parser import load_user_info

    resume = tmp_path / "resume.txt"
    resume.write_text("真实经历：Python 智能体项目", encoding="utf-8")
    info = load_user_info(str(tmp_path / "missing.md"), str(resume))
    captured = {}

    async def fake_polish(
        user_info,
        jd,
        llm,
        extra_context=None,
        progress_callback=None,
        stage_timeout=55,
        generation_timeout=None,
    ):
        captured["extra_context"] = extra_context
        return {"original": {}, "polished": {}}

    monkeypatch.setattr(company_agent, "get_company_user_info", lambda: info)
    monkeypatch.setattr(company_agent, "_get_llm", lambda: object())
    monkeypatch.setattr(
        "job_application_agent_langchain.resume_polish.polisher.polish_resume_async",
        fake_polish,
    )

    result = asyncio.run(
        form.polish_resume_for_jd.coroutine(
            jd="智能体算法岗位",
            resume_content="Agent 传入的补充纯文本",
        )
    )

    assert json.loads(result)["polished"] == {}
    assert "Python 智能体项目" in captured["extra_context"]["raw_resume_text"]
    assert (
        captured["extra_context"]["agent_resume_content"]
        == "Agent 传入的补充纯文本"
    )


def test_async_polish_reports_both_llm_stages():
    from job_application_agent_langchain.resume_polish.polisher import (
        polish_resume_async,
    )
    from job_application_agent_langchain.user_info.parser import UserInfo

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        def bind(self, **kwargs):
            return self

        async def ainvoke(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return type(
                    "Response",
                    (),
                    {
                        "content": json.dumps(
                            {
                                "required_skills": ["Python"],
                                "preferred_skills": [],
                                "experience_requirements": "",
                                "keywords": ["Python"],
                                "responsibilities": ["算法开发"],
                                "summary": "算法岗位",
                            },
                            ensure_ascii=False,
                        )
                    },
                )()
            return type(
                "Response",
                (),
                {
                    "content": json.dumps(
                        {
                            "self_introduction": "真实经历的针对性概述",
                            "project_highlights": [],
                            "skill_highlights": [],
                            "work_highlights": [],
                            "summary": "匹配总结",
                        },
                        ensure_ascii=False,
                    )
                },
            )()

    events = []

    async def progress(message):
        events.append(message)

    result = asyncio.run(
        polish_resume_async(
            UserInfo(),
            "负责 Python 算法开发",
            FakeLLM(),
            extra_context={"raw_resume_text": "真实 Python 项目"},
            progress_callback=progress,
            stage_timeout=10,
        )
    )

    assert result["polished"]["summary"] == "匹配总结"
    assert any("步骤 1/2" in event for event in events)
    assert any("步骤 2/2" in event for event in events)
    assert "润色完成" in events[-1]
