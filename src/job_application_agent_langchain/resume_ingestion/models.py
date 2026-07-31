"""Serializable extraction results; extracted values are proposals, not facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ExtractionMethod = Literal["text_layer", "ocr"]


@dataclass(frozen=True, slots=True)
class Evidence:
    page: int
    text: str
    bbox: tuple[float, float, float, float]
    method: ExtractionMethod
    confidence: float


@dataclass(frozen=True, slots=True)
class PageResult:
    page: int
    text: str
    method: ExtractionMethod
    confidence: float
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class ProposedField:
    field_key: str
    value: Any
    confidence: float
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ExtractionQuality:
    page_count: int
    character_count: int
    printable_ratio: float
    ocr_pages: tuple[int, ...]
    needs_review: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResumeExtraction:
    pages: tuple[PageResult, ...]
    proposed_fields: tuple[ProposedField, ...]
    quality: ExtractionQuality

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
