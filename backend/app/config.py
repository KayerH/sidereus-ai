from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = Path(__file__).resolve().parents[2]


def _read_local_api_key() -> str:
    key_file = PROJECT_DIR / "API_KEY.txt"
    if not key_file.exists():
        return ""
    return key_file.read_text(encoding="utf-8").strip()


class Settings:
    def __init__(self) -> None:
        load_dotenv(BACKEND_DIR / ".env")
        load_dotenv(PROJECT_DIR / ".env")

        self.app_name = os.getenv("APP_NAME", "AI Resume Analyzer")
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "*").split(",")
            if origin.strip()
        ]

        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "20"))
        self.max_pdf_pages = int(os.getenv("MAX_PDF_PAGES", "20"))
        self.recommended_resume_pages = int(os.getenv("RECOMMENDED_RESUME_PAGES", "5"))
        self.max_pdf_image_pixels = int(os.getenv("MAX_PDF_IMAGE_PIXELS", "25000000"))
        self.max_pdf_objects = int(os.getenv("MAX_PDF_OBJECTS", "5000"))
        self.redis_url = os.getenv("REDIS_URL", "")
        self.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

        self.llm_provider = os.getenv("LLM_PROVIDER", "aliyun-bailian")
        self.llm_api_key = os.getenv("LLM_API_KEY", "") or _read_local_api_key()
        self.llm_base_url = os.getenv(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.llm_model = os.getenv("LLM_MODEL", "qwen-plus")
        self.llm_timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "40"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
