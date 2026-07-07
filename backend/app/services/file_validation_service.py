from __future__ import annotations

import mimetypes
from pathlib import PurePath

import fitz
from fastapi import HTTPException, UploadFile

from app.config import get_settings
from app.models.file_security import FileSecurityReport
from app.utils.hash import sha256_bytes


PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
PDF_HEADER = b"%PDF-"


class FileValidationService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def receive_and_validate_pdf(self, file: UploadFile) -> tuple[bytes, FileSecurityReport]:
        content = await file.read()
        return self.validate_pdf(
            content=content,
            filename=file.filename or "",
            content_type=file.content_type or "",
        )

    def validate_pdf(self, content: bytes, filename: str, content_type: str = "") -> tuple[bytes, FileSecurityReport]:
        safe_filename = PurePath(filename).name
        report = FileSecurityReport(
            filename=safe_filename,
            content_type=content_type,
            size_bytes=len(content),
            file_hash=sha256_bytes(content) if content else "",
        )

        self._validate_basic_file_attributes(content, safe_filename, content_type, report)
        self._validate_pdf_structure(content, report)
        return content, report

    def _validate_basic_file_attributes(
        self,
        content: bytes,
        filename: str,
        content_type: str,
        report: FileSecurityReport,
    ) -> None:
        if not filename:
            raise HTTPException(status_code=400, detail="缺少上传文件名")

        report.extension_valid = filename.lower().endswith(".pdf")
        if not report.extension_valid:
            raise HTTPException(status_code=400, detail="仅支持上传 PDF 格式的简历文件")

        if not content:
            raise HTTPException(status_code=400, detail="上传的 PDF 文件为空")

        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"文件过大，请上传不超过 {self.settings.max_upload_mb}MB 的 PDF",
            )

        guessed_type, _encoding = mimetypes.guess_type(filename)
        report.mime_valid = content_type in PDF_MIME_TYPES or guessed_type in PDF_MIME_TYPES
        if content_type and content_type not in PDF_MIME_TYPES:
            raise HTTPException(status_code=400, detail="文件 MIME 类型不是 application/pdf")

        report.header_valid = content.startswith(PDF_HEADER)
        if not report.header_valid:
            raise HTTPException(status_code=400, detail="文件头不是合法 PDF，可能不是标准 PDF 文件")

    def _validate_pdf_structure(self, content: bytes, report: FileSecurityReport) -> None:
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                report.openable = True
                report.encrypted = bool(document.is_encrypted)
                report.needs_password = bool(document.needs_pass)
                report.page_count = document.page_count
                report.object_count = document.xref_length()

                if report.encrypted or report.needs_password:
                    raise HTTPException(status_code=400, detail="暂不支持加密或需要密码的 PDF")

                if report.page_count <= 0:
                    raise HTTPException(status_code=400, detail="PDF 页数异常，未检测到有效页面")

                if report.page_count > self.settings.max_pdf_pages:
                    raise HTTPException(
                        status_code=413,
                        detail=f"PDF 页数过多，请上传不超过 {self.settings.max_pdf_pages} 页的简历",
                    )

                if report.page_count > self.settings.recommended_resume_pages:
                    report.warnings.append(
                        f"简历页数为 {report.page_count} 页，超过常见简历建议页数 {self.settings.recommended_resume_pages} 页"
                    )

                if report.object_count > self.settings.max_pdf_objects:
                    raise HTTPException(status_code=413, detail="PDF 内部对象数量异常，存在资源耗尽风险")

                self._validate_images(document, report)
        except HTTPException:
            raise
        except fitz.FileDataError as exc:
            raise HTTPException(status_code=400, detail="PDF 文件损坏或不是标准 PDF") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail="PDF 无法打开，可能已损坏或格式异常") from exc

    def _validate_images(self, document: fitz.Document, report: FileSecurityReport) -> None:
        for page_index in range(document.page_count):
            page = document[page_index]
            for image in page.get_images(full=True):
                xref = image[0]
                try:
                    pixmap = fitz.Pixmap(document, xref)
                except RuntimeError:
                    continue
                pixels = pixmap.width * pixmap.height
                pixmap = None
                report.max_image_pixels = max(report.max_image_pixels, pixels)
                if pixels > self.settings.max_pdf_image_pixels:
                    raise HTTPException(status_code=413, detail="PDF 包含超大图片，存在资源耗尽风险")
