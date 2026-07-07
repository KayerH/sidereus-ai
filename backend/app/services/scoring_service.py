from __future__ import annotations

import re

from app.models.schemas import (
    JobRequirement,
    MatchResult,
    ResumeExtraction,
    ScoreBreakdown,
    ScoringWeights,
)
from app.services.llm_service import LLMService
from app.utils.text import unique_keep_order


class ScoringService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def score(
        self,
        resume: ResumeExtraction,
        job: JobRequirement,
        weights: ScoringWeights | None = None,
    ) -> MatchResult:
        weights = weights or ScoringWeights()
        resume_text = self._resume_search_text(resume)
        required_keywords = unique_keep_order(job.required_skills + job.job_keywords)
        preferred_keywords = unique_keep_order(job.preferred_skills)
        all_keywords = unique_keep_order(required_keywords + preferred_keywords)

        matched = [item for item in all_keywords if self._contains(resume_text, item)]
        missing = [item for item in required_keywords if item not in matched]

        skill_score = self._ratio_score(matched, unique_keep_order(job.required_skills + job.preferred_skills))
        keyword_score = self._ratio_score(matched, all_keywords)
        experience_score = self._experience_score(resume, job)
        project_score = self._project_score(resume, required_keywords)
        education_score = self._education_score(resume, job)

        breakdown = ScoreBreakdown(
            skill_match=round(skill_score, 1),
            experience_relevance=round(experience_score, 1),
            project_relevance=round(project_score, 1),
            education_fit=round(education_score, 1),
            keyword_coverage=round(keyword_score, 1),
        )
        normalized = weights.normalized()
        total_score = round(
            breakdown.skill_match * normalized["skill_match"]
            + breakdown.experience_relevance * normalized["experience_relevance"]
            + breakdown.project_relevance * normalized["project_relevance"]
            + breakdown.education_fit * normalized["education_fit"]
            + breakdown.keyword_coverage * normalized["keyword_coverage"]
        )

        result = MatchResult(
            score=max(0, min(100, total_score)),
            level=self._level(total_score),
            breakdown=breakdown,
            weights=weights,
            matched_keywords=matched,
            missing_keywords=missing,
            reason=self._reason(total_score, matched, missing),
            suggestions=self._suggestions(missing, job),
            ai_review=self._ai_review(resume, job, total_score),
        )
        return result

    @staticmethod
    def _contains(text: str, keyword: str) -> bool:
        return bool(keyword and keyword.casefold() in text.casefold())

    @staticmethod
    def _ratio_score(matched: list[str], expected: list[str]) -> float:
        if not expected:
            return 70
        matched_set = {item.casefold() for item in matched}
        expected_set = {item.casefold() for item in expected}
        return len(matched_set & expected_set) / len(expected_set) * 100

    def _experience_score(self, resume: ResumeExtraction, job: JobRequirement) -> float:
        required_years = self._extract_year(job.experience_requirements)
        resume_years = self._extract_year(resume.background.years_of_experience)
        if not required_years:
            return 75 if resume.background.work_experience or resume.background.projects else 60
        if not resume_years:
            return 45
        return min(100, resume_years / required_years * 100)

    @staticmethod
    def _project_score(resume: ResumeExtraction, required_keywords: list[str]) -> float:
        if not resume.background.projects:
            return 45 if required_keywords else 60
        project_text = " ".join(
            [
                project.name
                + " "
                + project.description
                + " "
                + " ".join(project.technologies)
                + " "
                + " ".join(project.highlights)
                for project in resume.background.projects
            ]
        )
        if not required_keywords:
            return 75
        hit_count = sum(1 for keyword in required_keywords if keyword.casefold() in project_text.casefold())
        return min(100, 35 + hit_count / max(len(required_keywords), 1) * 65)

    def _education_score(self, resume: ResumeExtraction, job: JobRequirement) -> float:
        required_rank = self._degree_rank(job.education_requirements)
        resume_rank = max(
            [self._degree_rank(item.degree + item.school + item.major) for item in resume.background.education]
            or [0]
        )
        if not required_rank:
            return 75 if resume_rank else 60
        if not resume_rank:
            return 45
        return 100 if resume_rank >= required_rank else 60

    @staticmethod
    def _extract_year(text: str) -> int:
        match = re.search(r"(\d+)\s*年", text or "")
        return int(match.group(1)) if match else 0

    @staticmethod
    def _degree_rank(text: str) -> int:
        if any(token in text for token in ["博士", "PhD"]):
            return 5
        if any(token in text for token in ["硕士", "研究生", "Master"]):
            return 4
        if any(token in text for token in ["本科", "学士", "Bachelor"]):
            return 3
        if any(token in text for token in ["大专", "专科"]):
            return 2
        return 0

    @staticmethod
    def _level(score: int | float) -> str:
        if score >= 90:
            return "高度匹配"
        if score >= 75:
            return "较匹配"
        if score >= 60:
            return "基本匹配"
        return "匹配度较低"

    @staticmethod
    def _reason(score: int, matched: list[str], missing: list[str]) -> str:
        hit_text = "、".join(matched[:8]) if matched else "暂无明显关键词"
        miss_text = "、".join(missing[:6]) if missing else "核心要求覆盖较完整"
        return f"综合评分 {score} 分，已匹配关键词：{hit_text}；待补充或未体现：{miss_text}。"

    @staticmethod
    def _suggestions(missing: list[str], job: JobRequirement) -> list[str]:
        suggestions = [f"简历中可以补充或突出 {keyword} 相关经历。" for keyword in missing[:5]]
        if job.experience_requirements:
            suggestions.append("建议在工作/项目经历中明确写出职责、技术栈、成果指标和持续时间。")
        if not suggestions:
            suggestions.append("当前简历与岗位要求覆盖较好，可进一步量化项目成果。")
        return suggestions

    def _ai_review(self, resume: ResumeExtraction, job: JobRequirement, score: int) -> str:
        system_prompt = "你是招聘简历匹配评估助手，请用 80 字以内给出客观评语。"
        user_prompt = (
            f"简历摘要：{resume.summary}\n"
            f"简历技能：{resume.background.skills}\n"
            f"岗位要求：{job.model_dump()}\n"
            f"规则评分：{score}\n"
            "请给出简短匹配评语。"
        )
        return self.llm.chat_text(system_prompt, user_prompt).strip()

    @staticmethod
    def _resume_search_text(resume: ResumeExtraction) -> str:
        return str(resume.model_dump())
