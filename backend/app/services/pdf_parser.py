from __future__ import annotations

import re
import unicodedata
from functools import cached_property
from statistics import mean
from typing import Any

import fitz
from fastapi import HTTPException, UploadFile

from app.config import get_settings
from app.models.file_security import FileSecurityReport
from app.models.pdf_document import (
    DocumentAnalysis,
    ImageBlock,
    OCRBlock,
    PageAnalysis,
    PageQuality,
    PageRoute,
    TextBlock,
    TextLine,
    TextSpan,
)
from app.services.file_validation_service import FileValidationService
from app.utils.text import clean_text, normalize_resume_text, unique_keep_order


RESUME_SEMANTIC_TERMS = [
    "教育背景",
    "教育经历",
    "工作经历",
    "项目经历",
    "实习经历",
    "社会实践",
    "专业技能",
    "个人技能",
    "自我评价",
    "获奖",
    "荣誉",
    "科研经历",
    "本科",
    "硕士",
    "博士",
    "大学",
    "学院",
    "公司",
    "工程师",
    "开发",
    "Java",
    "Python",
    "Redis",
    "MySQL",
    "Spring",
]

COMMON_PUNCTUATION = set("，。！？；：、,.!?;:()（）[]【】{}<>《》/\\-+_@#&%·'\"“”‘’|")
PHONE_RE = re.compile(r"(?:\+?86[- ]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\s*\.\s*[A-Za-z]{2,}")
DATE_RE = re.compile(r"(?:19|20)\d{2}[./年-]?\s?(?:1[0-2]|0?[1-9])?")


class PDFParser:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.file_validator = FileValidationService()

    async def read_pdf_bytes(self, file: UploadFile) -> bytes:
        content, _report = await self.read_pdf_with_report(file)
        return content

    async def read_pdf_with_report(self, file: UploadFile) -> tuple[bytes, FileSecurityReport]:
        return await self.file_validator.receive_and_validate_pdf(file)

    def extract_text(self, content: bytes) -> tuple[str, int]:
        analysis = self.analyze_document(content)
        if not analysis.selected_text:
            raise HTTPException(
                status_code=422,
                detail="未能从 PDF 中提取文本，可能是扫描件、图片型简历或缺少 OCR 依赖",
            )
        return analysis.selected_text, analysis.page_count

    def analyze_document(self, content: bytes) -> DocumentAnalysis:
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                pages = [self._analyze_page(page, index + 1) for index, page in enumerate(document)]
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail="PDF 解析失败，请检查文件是否损坏") from exc

        selected_text = normalize_resume_text("\n\n".join(page.selected_text for page in pages))
        return DocumentAnalysis(
            page_count=len(pages),
            pages=pages,
            selected_text=selected_text,
            document_type=self._classify_document(pages),
        )

    def _analyze_page(self, page: fitz.Page, page_number: int) -> PageAnalysis:
        text_blocks, image_blocks = self._extract_native_blocks(page)
        native_text = self._restore_reading_order(text_blocks, page.rect.width)
        native_quality = self._evaluate_text_quality(
            native_text,
            text_blocks,
            image_blocks,
            page.rect.width,
            page.rect.height,
        )
        route = self._choose_route(page_number, native_text, native_quality)
        native_quality.route = route

        analysis = PageAnalysis(
            page_number=page_number,
            width=page.rect.width,
            height=page.rect.height,
            rotation=page.rotation,
            text_blocks=text_blocks,
            image_blocks=image_blocks,
            links=page.get_links(),
            native_text=native_text,
            native_quality=native_quality,
            route=route,
        )

        if route == PageRoute.TEXT:
            analysis.selected_text = native_text
            analysis.selected_source = "native"
            return analysis

        if route == PageRoute.REGION_OCR:
            region_blocks = self._ocr_regions(page, page_number)
            analysis.ocr_blocks = region_blocks
            analysis.selected_text = self._merge_native_with_ocr_fields(native_text, region_blocks)
            analysis.selected_source = "native+region_ocr"
            return analysis

        ocr_blocks = self._ocr_page(page, page_number, dpi=220)
        ocr_text = self._restore_reading_order(
            [self._ocr_to_text_block(block) for block in ocr_blocks],
            page.rect.width,
        )
        ocr_quality = self._evaluate_text_quality(
            ocr_text,
            [self._ocr_to_text_block(block) for block in ocr_blocks],
            [],
            page.rect.width,
            page.rect.height,
            ocr_confidence=self._average_confidence(ocr_blocks),
        )
        analysis.ocr_blocks = ocr_blocks
        analysis.ocr_quality = ocr_quality

        if route == PageRoute.OCR or self._should_prefer_ocr(native_text, ocr_text, native_quality, ocr_quality):
            analysis.selected_text = ocr_text
            analysis.selected_source = "ocr"
        else:
            analysis.selected_text = self._merge_native_with_ocr_fields(native_text, ocr_blocks)
            analysis.selected_source = "native+ocr_fields"
        return analysis

    def _extract_native_blocks(self, page: fitz.Page) -> tuple[list[TextBlock], list[ImageBlock]]:
        raw = page.get_text("dict")
        text_blocks: list[TextBlock] = []
        image_blocks: list[ImageBlock] = []

        for block in raw.get("blocks", []):
            block_type = block.get("type")
            bbox = self._bbox_tuple(block.get("bbox", (0, 0, 0, 0)))

            if block_type == 1:
                image_blocks.append(
                    ImageBlock(
                        bbox=bbox,
                        width=int(block.get("width", 0) or 0),
                        height=int(block.get("height", 0) or 0),
                    )
                )
                continue

            if block_type != 0:
                continue

            lines: list[TextLine] = []
            for raw_line in block.get("lines", []):
                spans = [
                    TextSpan(
                        text=span.get("text", ""),
                        bbox=self._bbox_tuple(span.get("bbox", (0, 0, 0, 0))),
                        size=float(span.get("size", 0) or 0),
                        font=span.get("font", ""),
                        flags=int(span.get("flags", 0) or 0),
                        color=int(span.get("color", 0) or 0),
                    )
                    for span in raw_line.get("spans", [])
                    if span.get("text", "").strip()
                ]
                line_text = "".join(span.text for span in spans).strip()
                if not line_text:
                    continue
                lines.append(
                    TextLine(
                        text=line_text,
                        bbox=self._bbox_tuple(raw_line.get("bbox", (0, 0, 0, 0))),
                        spans=spans,
                    )
                )

            block_text = "\n".join(line.text for line in lines).strip()
            if block_text:
                text_blocks.append(TextBlock(text=block_text, bbox=bbox, lines=lines))

        return text_blocks, image_blocks

    def _evaluate_text_quality(
        self,
        text: str,
        text_blocks: list[TextBlock],
        image_blocks: list[ImageBlock],
        page_width: float,
        page_height: float,
        ocr_confidence: float = 0,
    ) -> PageQuality:
        compact = "".join(ch for ch in text if not ch.isspace())
        line_texts = [line.strip() for line in text.splitlines() if line.strip()]
        valid_chars = sum(1 for ch in compact if self._is_valid_resume_char(ch))
        abnormal_chars = sum(1 for ch in compact if self._is_abnormal_char(ch))
        semantic_score = self._semantic_score(text)
        fragmentation = self._fragmentation_score(text_blocks)
        reading_order = self._reading_order_score(text_blocks)
        repetition = self._repetition_ratio(line_texts)
        image_coverage = self._image_coverage_ratio(image_blocks, page_width, page_height)

        valid_ratio = valid_chars / max(len(compact), 1)
        abnormal_ratio = abnormal_chars / max(len(compact), 1)
        char_volume = min(len(compact) / 500, 1)
        overall = (
            valid_ratio * 0.28
            + semantic_score * 0.24
            + reading_order * 0.16
            + (1 - fragmentation) * 0.12
            + (1 - repetition) * 0.10
            + char_volume * 0.10
        )
        if abnormal_ratio > 0.08:
            overall -= 0.2
        if ocr_confidence:
            overall = overall * 0.8 + ocr_confidence * 0.2

        return PageQuality(
            non_space_chars=len(compact),
            chinese_chars=sum(1 for ch in compact if "\u4e00" <= ch <= "\u9fff"),
            english_chars=sum(1 for ch in compact if ch.isascii() and ch.isalpha()),
            digit_chars=sum(1 for ch in compact if ch.isdigit()),
            line_count=len(line_texts),
            text_block_count=len(text_blocks),
            average_line_length=mean([len(line) for line in line_texts]) if line_texts else 0,
            valid_char_ratio=round(valid_ratio, 3),
            abnormal_char_ratio=round(abnormal_ratio, 3),
            semantic_score=round(semantic_score, 3),
            image_coverage_ratio=round(image_coverage, 3),
            fragmentation_score=round(fragmentation, 3),
            reading_order_score=round(reading_order, 3),
            repetition_ratio=round(repetition, 3),
            ocr_average_confidence=round(ocr_confidence, 3),
            overall_score=round(max(min(overall, 1), 0), 3),
        )

    def _choose_route(self, page_number: int, native_text: str, quality: PageQuality) -> PageRoute:
        scanned_page = quality.image_coverage_ratio > 0.7 and quality.non_space_chars < 50
        broken_text = quality.valid_char_ratio < 0.65 or quality.abnormal_char_ratio > 0.1

        if scanned_page or quality.non_space_chars < 15:
            return PageRoute.OCR
        if broken_text or quality.overall_score < 0.42:
            return PageRoute.COMPARE
        if (
            page_number == 1
            and quality.overall_score >= 0.5
            and self._missing_contact_fields(native_text)
            and (quality.text_block_count > 18 or quality.fragmentation_score > 0.25)
        ):
            return PageRoute.COMPARE
        if page_number == 1 and quality.overall_score >= 0.5 and self._missing_contact_fields(native_text):
            return PageRoute.REGION_OCR
        if quality.fragmentation_score > 0.65 or quality.reading_order_score < 0.45:
            return PageRoute.COMPARE
        return PageRoute.TEXT

    def _ocr_page(self, page: fitz.Page, page_number: int, dpi: int = 220) -> list[OCRBlock]:
        return self._run_ocr(page, page_number, dpi=dpi)

    def _ocr_regions(self, page: fitz.Page, page_number: int) -> list[OCRBlock]:
        width = page.rect.width
        height = page.rect.height
        regions = [
            fitz.Rect(0, 0, width, height * 0.34),
            fitz.Rect(0, 0, width * 0.38, height),
            fitz.Rect(width * 0.62, 0, width, height * 0.42),
        ]
        blocks: list[OCRBlock] = []
        for region in regions:
            blocks.extend(self._run_ocr(page, page_number, dpi=260, clip=region))
        return self._deduplicate_ocr_blocks(blocks)

    def _run_ocr(
        self,
        page: fitz.Page,
        page_number: int,
        dpi: int,
        clip: fitz.Rect | None = None,
    ) -> list[OCRBlock]:
        try:
            import numpy as np
            from PIL import Image, ImageEnhance, ImageOps
        except ImportError as exc:
            raise HTTPException(status_code=422, detail="PDF 文本不可用，请安装 OCR 图像依赖后重试") from exc

        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, clip=clip)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        image = self._preprocess_for_ocr(image)

        result, _elapsed = self.ocr_engine(np.array(image))
        blocks: list[OCRBlock] = []
        x_offset = clip.x0 if clip else 0
        y_offset = clip.y0 if clip else 0
        scale = 72 / dpi

        for order, item in enumerate(result or []):
            if len(item) < 3:
                continue
            points, text, confidence = item[0], item[1], item[2]
            if not isinstance(text, str) or not text.strip():
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bbox = (
                min(xs) * scale + x_offset,
                min(ys) * scale + y_offset,
                max(xs) * scale + x_offset,
                max(ys) * scale + y_offset,
            )
            blocks.append(
                OCRBlock(
                    text=text.strip(),
                    bbox=bbox,
                    confidence=float(confidence or 0),
                    page_number=page_number,
                    order=order,
                    dpi=dpi,
                )
            )
        return blocks

    @cached_property
    def ocr_engine(self) -> Any:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise HTTPException(status_code=422, detail="PDF 文本不可用，请安装 OCR 依赖后重试") from exc
        return RapidOCR()

    @staticmethod
    def _preprocess_for_ocr(image: Any) -> Any:
        from PIL import ImageEnhance, ImageOps

        grayscale = ImageOps.grayscale(image)
        contrast = ImageEnhance.Contrast(grayscale).enhance(1.25)
        return contrast.convert("RGB")

    def _restore_reading_order(self, text_blocks: list[TextBlock], page_width: float) -> str:
        if not text_blocks:
            return ""

        line_blocks = self._flatten_lines(text_blocks)
        rows: list[list[TextBlock]] = []
        for block in sorted(line_blocks, key=lambda item: (item.bbox[1], item.bbox[0])):
            if rows and abs(rows[-1][0].bbox[1] - block.bbox[1]) <= max(6, self._height(block) * 0.45):
                rows[-1].append(block)
            else:
                rows.append([block])

        ordered_lines = []
        for row in rows:
            sorted_row = sorted(row, key=lambda item: item.bbox[0])
            ordered_lines.append(" ".join(block.text for block in sorted_row if block.text.strip()))

        return clean_text("\n".join(ordered_lines))

    @staticmethod
    def _flatten_lines(text_blocks: list[TextBlock]) -> list[TextBlock]:
        lines: list[TextBlock] = []
        for block in text_blocks:
            if block.lines:
                lines.extend(TextBlock(text=line.text, bbox=line.bbox, source=block.source) for line in block.lines)
            else:
                lines.append(block)
        return lines

    def _merge_native_with_ocr_fields(self, native_text: str, ocr_blocks: list[OCRBlock]) -> str:
        ocr_text = self._restore_reading_order(
            [self._ocr_to_text_block(block) for block in ocr_blocks],
            page_width=10_000,
        )
        evidence_lines = []
        for line in ocr_text.splitlines():
            if any(token in line for token in ["姓名", "电话", "手机", "邮箱", "籍贯", "地址", "现居", "所在地"]):
                evidence_lines.append(line)
            elif PHONE_RE.search(line):
                evidence_lines.append(f"电话：{PHONE_RE.search(line).group(0)}")
            elif EMAIL_RE.search(line):
                evidence_lines.append(f"邮箱：{EMAIL_RE.search(line).group(0)}")

        merged_lines = unique_keep_order(evidence_lines + native_text.splitlines())
        return normalize_resume_text("\n".join(merged_lines))

    @staticmethod
    def _ocr_to_text_block(block: OCRBlock) -> TextBlock:
        return TextBlock(text=block.text, bbox=block.bbox, source="ocr")

    @staticmethod
    def _should_prefer_ocr(
        native_text: str,
        ocr_text: str,
        native_quality: PageQuality,
        ocr_quality: PageQuality,
    ) -> bool:
        native_missing_contact = PDFParser._missing_contact_fields(native_text)
        ocr_has_contact = not PDFParser._missing_contact_fields(ocr_text)
        if native_missing_contact and ocr_has_contact and ocr_quality.overall_score >= native_quality.overall_score - 0.18:
            return True
        return ocr_quality.overall_score >= native_quality.overall_score + 0.08

    @staticmethod
    def _average_confidence(blocks: list[OCRBlock]) -> float:
        return mean([block.confidence for block in blocks]) if blocks else 0

    @staticmethod
    def _deduplicate_ocr_blocks(blocks: list[OCRBlock]) -> list[OCRBlock]:
        seen: set[tuple[str, int, int]] = set()
        result: list[OCRBlock] = []
        for block in sorted(blocks, key=lambda item: (item.bbox[1], item.bbox[0])):
            key = (block.text.casefold(), round(block.bbox[0] / 10), round(block.bbox[1] / 10))
            if key in seen:
                continue
            seen.add(key)
            result.append(block)
        return result

    @staticmethod
    def _is_valid_resume_char(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff" or ch.isascii() and ch.isalnum() or ch in COMMON_PUNCTUATION

    @staticmethod
    def _is_abnormal_char(ch: str) -> bool:
        codepoint = ord(ch)
        category = unicodedata.category(ch)
        return ch == "\ufffd" or category.startswith("C") or 0xE000 <= codepoint <= 0xF8FF

    @staticmethod
    def _semantic_score(text: str) -> float:
        hits = sum(1 for term in RESUME_SEMANTIC_TERMS if term.lower() in text.lower())
        has_date = bool(DATE_RE.search(text))
        has_sentence = any(token in text for token in ["经历", "项目", "负责", "技术", "课程", "能力"])
        return min((hits / 8) + (0.1 if has_date else 0) + (0.1 if has_sentence else 0), 1)

    @staticmethod
    def _fragmentation_score(text_blocks: list[TextBlock]) -> float:
        if not text_blocks:
            return 1
        lengths = [len(block.text.strip()) for block in text_blocks]
        single_char_ratio = sum(1 for length in lengths if length <= 1) / len(lengths)
        short_block_ratio = sum(1 for length in lengths if length <= 4) / len(lengths)
        return min(single_char_ratio * 0.7 + short_block_ratio * 0.3, 1)

    @staticmethod
    def _reading_order_score(text_blocks: list[TextBlock]) -> float:
        if len(text_blocks) <= 1:
            return 1
        jumps = 0
        previous_y = text_blocks[0].bbox[1]
        for block in text_blocks[1:]:
            if block.bbox[1] + 8 < previous_y:
                jumps += 1
            previous_y = block.bbox[1]
        return max(0, 1 - jumps / max(len(text_blocks) - 1, 1))

    @staticmethod
    def _repetition_ratio(lines: list[str]) -> float:
        if not lines:
            return 0
        normalized = [line.casefold() for line in lines if len(line) > 3]
        if not normalized:
            return 0
        return 1 - len(set(normalized)) / len(normalized)

    @staticmethod
    def _image_coverage_ratio(image_blocks: list[ImageBlock], width: float, height: float) -> float:
        page_area = max(width * height, 1)
        image_area = sum(max(block.bbox[2] - block.bbox[0], 0) * max(block.bbox[3] - block.bbox[1], 0) for block in image_blocks)
        return min(image_area / page_area, 1)

    @staticmethod
    def _height(block: TextBlock) -> float:
        return max(block.bbox[3] - block.bbox[1], 1)

    @staticmethod
    def _missing_contact_fields(text: str) -> bool:
        return not (PHONE_RE.search(text) and EMAIL_RE.search(text))

    @staticmethod
    def _bbox_tuple(raw_bbox: Any) -> tuple[float, float, float, float]:
        return tuple(float(value) for value in raw_bbox[:4])  # type: ignore[index]

    @staticmethod
    def _classify_document(pages: list[PageAnalysis]) -> str:
        if not pages:
            return "empty"
        routes = [page.route for page in pages]
        if all(route == PageRoute.TEXT for route in routes):
            return "native_text"
        if all(route == PageRoute.OCR for route in routes):
            return "scanned_image"
        if any(route == PageRoute.COMPARE for route in routes):
            return "pseudo_or_damaged_text"
        return "mixed"
