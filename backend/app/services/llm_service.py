from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from app.config import get_settings


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.enabled = bool(self.settings.llm_api_key)
        self.client = (
            OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout_seconds,
            )
            if self.enabled
            else None
        )

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.client:
            return {}

        try:
            completion = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            content = completion.choices[0].message.content or ""
            return self._extract_json(content)
        except Exception:
            return {}

    def chat_text(self, system_prompt: str, user_prompt: str) -> str:
        if not self.client:
            return ""

        try:
            completion = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            return completion.choices[0].message.content or ""
        except Exception:
            return ""

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        content = content.strip()
        if not content:
            return {}

        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S)
        candidate = fenced.group(1) if fenced else content

        if not candidate.startswith("{"):
            start = candidate.find("{")
            end = candidate.rfind("}")
            candidate = candidate[start : end + 1] if start != -1 and end != -1 else candidate

        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
