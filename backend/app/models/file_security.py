from __future__ import annotations

from pydantic import BaseModel, Field


class FileSecurityReport(BaseModel):
    filename: str = ""
    content_type: str = ""
    size_bytes: int = 0
    file_hash: str = ""
    extension_valid: bool = False
    mime_valid: bool = False
    header_valid: bool = False
    openable: bool = False
    encrypted: bool = False
    needs_password: bool = False
    page_count: int = 0
    object_count: int = 0
    max_image_pixels: int = 0
    warnings: list[str] = Field(default_factory=list)
