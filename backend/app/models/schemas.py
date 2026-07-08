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
    age: str = ""
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
    raw_description: str = ""
    atomic_requirements: list["AtomicRequirement"] = Field(default_factory=list)


class AtomicRequirement(BaseModel):
    id: str = ""
    text: str = ""
    requirement_type: str = "core"
    capability_category: str = "general"
    capability_name: str = ""
    examples: list[str] = Field(default_factory=list)
    required_concepts: list[str] = Field(default_factory=list)
    acceptable_evidence: list[str] = Field(default_factory=list)
    evidence_logic: str = "PARTIAL_OK"
    logic: str = "OR"
    min_count: int = 1
    proficiency: str = "熟悉"
    is_hard: bool = False
    is_open_ended: bool = True
    weight: float = 10


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
    eligibility: str = "PASS"
    confidence_score: int = 0
    breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    requirement_results: list["RequirementMatch"] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    reason: str = ""
    suggestions: list[str] = Field(default_factory=list)
    ai_review: str = ""


class RequirementMatch(BaseModel):
    requirement_id: str = ""
    requirement: str = ""
    category: str = ""
    weight: float = 0
    status: str = "INSUFFICIENT_EVIDENCE"
    score: float = 0
    semantic_score: float = 0
    evidence_strength: float = 0
    proficiency_score: float = 0
    project_depth: float = 0
    responsibility_score: float = 0
    recency_score: float = 0
    relation: str = "无证据"
    matched_skills: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    direct_evidence: list[str] = Field(default_factory=list)
    inferred_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    rule_score: float = 0
    llm_score: float = 0
    judge_confidence: float = 0
    reason: str = ""
    gaps: list[str] = Field(default_factory=list)
    confidence: float = 0


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
