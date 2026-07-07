from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PageRoute(str, Enum):
    TEXT = "TEXT"
    OCR = "OCR"
    COMPARE = "COMPARE"
    REGION_OCR = "REGION_OCR"


@dataclass(slots=True)
class TextSpan:
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    font: str
    flags: int
    color: int

    @property
    def bold(self) -> bool:
        return "bold" in self.font.lower() or bool(self.flags & 16)


@dataclass(slots=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]
    spans: list[TextSpan] = field(default_factory=list)


@dataclass(slots=True)
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]
    lines: list[TextLine] = field(default_factory=list)
    source: str = "native"


@dataclass(slots=True)
class ImageBlock:
    bbox: tuple[float, float, float, float]
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class OCRBlock:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float
    page_number: int
    order: int
    dpi: int
    engine: str = "rapidocr-onnxruntime"


@dataclass(slots=True)
class PageQuality:
    non_space_chars: int = 0
    chinese_chars: int = 0
    english_chars: int = 0
    digit_chars: int = 0
    line_count: int = 0
    text_block_count: int = 0
    average_line_length: float = 0
    valid_char_ratio: float = 0
    abnormal_char_ratio: float = 0
    semantic_score: float = 0
    image_coverage_ratio: float = 0
    fragmentation_score: float = 0
    reading_order_score: float = 0
    repetition_ratio: float = 0
    ocr_average_confidence: float = 0
    overall_score: float = 0
    route: PageRoute = PageRoute.TEXT


@dataclass(slots=True)
class PageAnalysis:
    page_number: int
    width: float
    height: float
    rotation: int
    text_blocks: list[TextBlock]
    image_blocks: list[ImageBlock]
    links: list[dict[str, Any]]
    native_text: str
    native_quality: PageQuality
    route: PageRoute
    selected_text: str = ""
    ocr_blocks: list[OCRBlock] = field(default_factory=list)
    ocr_quality: PageQuality | None = None
    selected_source: str = "native"


@dataclass(slots=True)
class DocumentAnalysis:
    page_count: int
    pages: list[PageAnalysis]
    selected_text: str
    document_type: str
