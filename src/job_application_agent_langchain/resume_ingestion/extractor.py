"""Text-layer first PDF extraction with local OCR fallback."""

from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import re
from typing import Callable

import fitz
from pypdf import PdfReader

from job_application_agent_langchain.resume_ingestion.models import (
    Evidence,
    ExtractionQuality,
    PageResult,
    ProposedField,
    ResumeExtraction,
)


_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_NAME_LABEL = re.compile(r"(?:姓名|Name)\s*[:：]?\s*([\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z .'-]{1,60})", re.I)
_GENDER = re.compile(r"(?:性别|Gender)\s*[:：]?\s*(男|女|male|female)", re.I)
_ADDRESS = re.compile(r"(?:家庭住址|现居地|所在地|Address)\s*[:：]?\s*([^\n]{2,80})", re.I)
_SECTION_HEADINGS = {
    "education": ("教育经历", "教育背景", "education"),
    "work_experience": ("工作经历", "实习经历", "work experience", "experience"),
    "project_experience": ("项目经历", "项目经验", "projects", "project experience"),
    "skills": ("专业技能", "技能", "skills", "technical skills"),
    "awards": ("获奖", "荣誉", "awards", "honors"),
    "self_introduction": ("自我评价", "个人总结", "summary", "profile"),
}


class ResumeExtractor:
    def __init__(
        self,
        *,
        minimum_page_characters: int = 60,
        ocr_factory: Callable[[], object] | None = None,
    ):
        self.minimum_page_characters = minimum_page_characters
        self._ocr_factory = ocr_factory or self._default_ocr_factory
        self._ocr_engine: object | None = None

    @staticmethod
    def _default_ocr_factory():
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()

    def extract(self, pdf_bytes: bytes) -> ResumeExtraction:
        try:
            pdf_reader = PdfReader(BytesIO(pdf_bytes))
            layout_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"无法读取 PDF: {exc}") from exc

        if len(pdf_reader.pages) != layout_document.page_count:
            layout_document.close()
            raise ValueError("PDF 页面结构不一致")

        page_results: list[PageResult] = []
        warnings: list[str] = []
        ocr_pages: list[int] = []
        try:
            for index, pdf_page in enumerate(pdf_reader.pages):
                page_number = index + 1
                layout_page = layout_document[index]
                native_text = (pdf_page.extract_text() or "").strip()
                printable = self._printable_ratio(native_text)
                use_ocr = (
                    len(self._compact(native_text)) < self.minimum_page_characters
                    or printable < 0.85
                )
                if use_ocr:
                    result = self._extract_ocr(layout_page, page_number)
                    ocr_pages.append(page_number)
                    if not result.text:
                        warnings.append(f"第 {page_number} 页 OCR 未识别到文本")
                else:
                    result = self._extract_text_layer(
                        layout_page, page_number, native_text
                    )
                page_results.append(result)
        finally:
            layout_document.close()

        combined = "\n".join(page.text for page in page_results if page.text)
        printable_ratio = self._printable_ratio(combined)
        if not combined.strip():
            warnings.append("整份简历未提取到可用文本")
        if printable_ratio < 0.9:
            warnings.append("提取文本包含较多不可打印或异常字符")

        fields = self._propose_fields(tuple(page_results))
        low_confidence = any(field.confidence < 0.8 for field in fields)
        quality = ExtractionQuality(
            page_count=len(page_results),
            character_count=len(self._compact(combined)),
            printable_ratio=round(printable_ratio, 4),
            ocr_pages=tuple(ocr_pages),
            needs_review=bool(ocr_pages or warnings or low_confidence),
            warnings=tuple(warnings),
        )
        return ResumeExtraction(tuple(page_results), tuple(fields), quality)

    def _extract_text_layer(
        self, layout_page: fitz.Page, page_number: int, fallback_text: str
    ) -> PageResult:
        grouped: dict[tuple[int, int], list[tuple]] = defaultdict(list)
        for word in layout_page.get_text("words", sort=True):
            grouped[(int(word[5]), int(word[6]))].append(word)

        width = max(float(layout_page.rect.width), 1.0)
        height = max(float(layout_page.rect.height), 1.0)
        evidence: list[Evidence] = []
        for words in grouped.values():
            text = " ".join(str(word[4]) for word in words).strip()
            if not text:
                continue
            evidence.append(
                Evidence(
                    page=page_number,
                    text=text,
                    bbox=(
                        round(min(float(word[0]) for word in words) / width, 5),
                        round(min(float(word[1]) for word in words) / height, 5),
                        round(max(float(word[2]) for word in words) / width, 5),
                        round(max(float(word[3]) for word in words) / height, 5),
                    ),
                    method="text_layer",
                    confidence=0.98,
                )
            )
        text = "\n".join(item.text for item in evidence) or fallback_text
        if not evidence and fallback_text:
            evidence.append(
                Evidence(page_number, fallback_text, (0.0, 0.0, 1.0, 1.0), "text_layer", 0.8)
            )
        return PageResult(page_number, text, "text_layer", 0.98, tuple(evidence))

    def _extract_ocr(self, page: fitz.Page, page_number: int) -> PageResult:
        if self._ocr_engine is None:
            self._ocr_engine = self._ocr_factory()
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        raw_result, _ = self._ocr_engine(pixmap.tobytes("png"))
        width = max(float(pixmap.width), 1.0)
        height = max(float(pixmap.height), 1.0)
        evidence: list[Evidence] = []
        for item in raw_result or []:
            box, text, score = item
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            cleaned = str(text).strip()
            if not cleaned:
                continue
            evidence.append(
                Evidence(
                    page_number,
                    cleaned,
                    (
                        round(min(xs) / width, 5),
                        round(min(ys) / height, 5),
                        round(max(xs) / width, 5),
                        round(max(ys) / height, 5),
                    ),
                    "ocr",
                    round(float(score), 4),
                )
            )
        text = "\n".join(item.text for item in evidence)
        confidence = (
            sum(item.confidence for item in evidence) / len(evidence)
            if evidence
            else 0.0
        )
        return PageResult(page_number, text, "ocr", round(confidence, 4), tuple(evidence))

    def _propose_fields(self, pages: tuple[PageResult, ...]) -> list[ProposedField]:
        all_evidence = [evidence for page in pages for evidence in page.evidence]
        combined = "\n".join(item.text for item in all_evidence)
        proposed: list[ProposedField] = []

        for key, pattern in (("email", _EMAIL), ("phone", _PHONE)):
            match = pattern.search(combined)
            if match:
                value = match.group(0)
                evidence = self._matching_evidence(all_evidence, value)
                proposed.append(ProposedField(key, value, self._confidence(evidence), evidence))

        name_match = _NAME_LABEL.search(combined)
        if name_match:
            value = name_match.group(1).strip()
            evidence = self._matching_evidence(all_evidence, value)
            proposed.append(ProposedField("full_name", value, self._confidence(evidence), evidence))

        if not name_match:
            for item in all_evidence:
                compact = re.sub(r"\s+", "", item.text)
                if item.page == 1 and item.bbox[1] < 0.16 and re.fullmatch(r"[\u4e00-\u9fff]{2,6}", compact):
                    proposed.append(ProposedField("full_name", compact, 0.75, (item,)))
                    break

        for field_key, pattern in (("gender", _GENDER), ("address", _ADDRESS)):
            match = pattern.search(combined)
            if match:
                value = match.group(1).strip()
                evidence = self._matching_evidence(all_evidence, value)
                proposed.append(ProposedField(field_key, value, self._confidence(evidence), evidence))

        lines = [item for item in all_evidence if item.text.strip()]
        heading_index: list[tuple[int, str]] = []
        for index, item in enumerate(lines):
            normalized = re.sub(r"\s+", " ", item.text).strip().lower().rstrip(":：")
            for field_key, headings in _SECTION_HEADINGS.items():
                if any(normalized == heading.lower() for heading in headings):
                    heading_index.append((index, field_key))
                    break
        for position, (start, field_key) in enumerate(heading_index):
            end = heading_index[position + 1][0] if position + 1 < len(heading_index) else len(lines)
            section_evidence = tuple(lines[start + 1 : end])
            value = "\n".join(item.text for item in section_evidence).strip()
            if value:
                proposed.append(
                    ProposedField(
                        field_key,
                        value,
                        self._confidence(section_evidence),
                        section_evidence,
                    )
                )

        if not any(field.field_key == "skills" for field in proposed) and heading_index:
            first_heading = heading_index[0][0]
            preamble = tuple(
                item
                for item in lines[:first_heading]
                if not _EMAIL.search(item.text)
                and not _PHONE.search(item.text)
                and not _NAME_LABEL.search(item.text)
                and not re.fullmatch(r"\s*[\u4e00-\u9fff]{2,6}\s*", item.text)
            )
            skill_text = "\n".join(item.text for item in preamble).strip()
            if skill_text:
                proposed.append(
                    ProposedField("skills", skill_text, self._confidence(preamble), preamble)
                )
        return proposed

    @staticmethod
    def _matching_evidence(evidence: list[Evidence], value: str) -> tuple[Evidence, ...]:
        return tuple(item for item in evidence if value.lower() in item.text.lower())[:3]

    @staticmethod
    def _confidence(evidence: tuple[Evidence, ...]) -> float:
        return round(min((item.confidence for item in evidence), default=0.5), 4)

    @staticmethod
    def _compact(text: str) -> str:
        return re.sub(r"\s+", "", text)

    @staticmethod
    def _printable_ratio(text: str) -> float:
        if not text:
            return 0.0
        printable = sum(character.isprintable() or character.isspace() for character in text)
        return printable / len(text)
