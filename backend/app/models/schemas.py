from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExtractedField(BaseModel):
    raw_value: str = ""
    normalized_value: str = ""
    source: str = ""
    confidence: float = 0
    status: str = "MISSING"
    page_number: int | None = None
    bbox: list[float] | None = None
    evidence: str = ""
    normalized: bool = False
    candidates: list[str] = Field(default_factory=list)


class ResumeSection(BaseModel):
    name: str
    title: str = ""
    text: str = ""
    start_line: int = 0
    end_line: int = 0


class EducationItem(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    period: str = ""


class ProjectItem(BaseModel):
    name: str = ""
    role: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class BasicInfo(BaseModel):
    name: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""


class JobIntention(BaseModel):
    position: str = ""
    expected_salary: str = ""


class BackgroundInfo(BaseModel):
    years_of_experience: str = ""
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    work_experience: list[str] = Field(default_factory=list)
    research_experience: list[str] = Field(default_factory=list)
    honors: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    self_evaluation: str = ""


class ResumeExtraction(BaseModel):
    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    job_intention: JobIntention = Field(default_factory=JobIntention)
    background: BackgroundInfo = Field(default_factory=BackgroundInfo)
    summary: str = ""
    sections: dict[str, ResumeSection] = Field(default_factory=dict)
    field_details: dict[str, ExtractedField] = Field(default_factory=dict)
    extraction_warnings: list[str] = Field(default_factory=list)


class JobRequirement(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    experience_requirements: str = ""
    education_requirements: str = ""
    job_keywords: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class ScoringWeights(BaseModel):
    skill_match: float = 40
    experience_relevance: float = 25
    project_relevance: float = 20
    education_fit: float = 10
    keyword_coverage: float = 5

    def normalized(self) -> dict[str, float]:
        weights = {
            "skill_match": max(self.skill_match, 0),
            "experience_relevance": max(self.experience_relevance, 0),
            "project_relevance": max(self.project_relevance, 0),
            "education_fit": max(self.education_fit, 0),
            "keyword_coverage": max(self.keyword_coverage, 0),
        }
        total = sum(weights.values()) or 1
        return {key: value / total for key, value in weights.items()}


class ScoreBreakdown(BaseModel):
    skill_match: float = 0
    experience_relevance: float = 0
    project_relevance: float = 0
    education_fit: float = 0
    keyword_coverage: float = 0


class MatchResult(BaseModel):
    score: int = 0
    level: str = "匹配度较低"
    breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    reason: str = ""
    suggestions: list[str] = Field(default_factory=list)
    ai_review: str = ""


class AnalyzeFullResponse(BaseModel):
    resume_id: str
    file_hash: str
    parsed_from_cache: bool = False
    matched_from_cache: bool = False
    raw_text_preview: str = ""
    resume: ResumeExtraction
    job_requirement: JobRequirement
    match: MatchResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str
