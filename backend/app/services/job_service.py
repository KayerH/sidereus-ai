from __future__ import annotations

from typing import Any

from app.models.schemas import JobRequirement
from app.services.extraction_service import COMMON_SKILLS
from app.services.llm_service import LLMService
from app.utils.text import truncate_text, unique_keep_order


class JobRequirementService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def analyze(self, job_description: str) -> JobRequirement:
        fallback = self._rule_based_analyze(job_description)
        ai_result = self._ai_analyze(job_description)
        if not ai_result:
            return fallback

        merged = self._merge(fallback.model_dump(), ai_result)
        try:
            return JobRequirement.model_validate(merged)
        except Exception:
            return fallback

    def _ai_analyze(self, job_description: str) -> dict[str, Any]:
        system_prompt = (
            "你是招聘岗位需求分析助手。请只返回合法 JSON，"
            "不要输出 Markdown，不要添加额外解释。"
        )
        user_prompt = f"""
请分析下面的岗位描述，抽取岗位关键词和要求。字段缺失时返回空字符串或空数组。

返回 JSON 结构必须符合：
{{
  "required_skills": [],
  "preferred_skills": [],
  "experience_requirements": "",
  "education_requirements": "",
  "job_keywords": [],
  "responsibilities": []
}}

岗位描述：
{truncate_text(job_description, 6000)}
"""
        return self.llm.chat_json(system_prompt, user_prompt)

    @staticmethod
    def _rule_based_analyze(job_description: str) -> JobRequirement:
        required_skills = unique_keep_order(
            skill for skill in COMMON_SKILLS if skill.lower() in job_description.lower()
        )
        keywords = unique_keep_order(required_skills + _extract_chinese_keywords(job_description))
        return JobRequirement(
            required_skills=required_skills,
            preferred_skills=[],
            experience_requirements=_first_requirement(job_description, "经验"),
            education_requirements=_first_requirement(job_description, "本科|硕士|博士|大专|学历"),
            job_keywords=keywords[:20],
            responsibilities=_split_sentences(job_description)[:6],
        )

    @staticmethod
    def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        for key, value in incoming.items():
            if value not in ("", None, [], {}):
                base[key] = value
        return base


def _split_sentences(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    chunks = []
    for raw in normalized.replace("；", "。").replace(";", "。").split("。"):
        chunk = raw.strip(" \n\t-•0123456789.、")
        if 6 <= len(chunk) <= 120:
            chunks.append(chunk)
    return chunks


def _extract_chinese_keywords(text: str) -> list[str]:
    candidates = [
        "后端",
        "前端",
        "全栈",
        "算法",
        "AI",
        "简历解析",
        "PDF",
        "缓存",
        "接口",
        "数据库",
        "云服务",
        "函数计算",
        "阿里云",
        "工程化",
        "测试",
        "部署",
    ]
    return [keyword for keyword in candidates if keyword.lower() in text.lower()]


def _first_requirement(text: str, keyword_pattern: str) -> str:
    for sentence in _split_sentences(text):
        if any(token in sentence for token in keyword_pattern.split("|")):
            return sentence
    return ""
