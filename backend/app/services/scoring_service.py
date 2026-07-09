from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from app.models.schemas import (
    AtomicRequirement,
    JobRequirement,
    MatchResult,
    RequirementMatch,
    ResumeExtraction,
    ScoreBreakdown,
    ScoringWeights,
)
from app.services.llm_service import LLMService
from app.services.requirement_judge_service import JudgeEvidence, LLMRequirementJudge, RequirementJudgeResult
from app.utils.skill_match import contains_any, contains_term
from app.utils.text import unique_keep_order


MATCH_STATUS_SCORE = {
    "FULLY_MATCHED": 95,
    "MOSTLY_MATCHED": 82,
    "PARTIALLY_MATCHED": 55,
    "INSUFFICIENT_EVIDENCE": 22,
    "NOT_MATCHED": 0,
    "CONFLICTED": 10,
}

TECH_ALIASES = {
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node js": "Node.js",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "mybatis plus": "MyBatis-Plus",
    "mybatis-plus": "MyBatis-Plus",
    "elastic search": "Elasticsearch",
    "elasticsearch": "Elasticsearch",
    "redis缓存": "Redis",
}

CAPABILITY_SKILLS = {
    "backend_language": ["Java", "Python", "Go", "Node.js", "C#", "PHP", "Kotlin", "Rust"],
    "data_storage": ["MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch", "Oracle", "SQL Server"],
    "cache": ["Redis", "Memcached", "Caffeine"],
    "message_queue": ["Kafka", "RabbitMQ", "RocketMQ", "Pulsar", "ActiveMQ"],
    "web_backend": ["Spring Boot", "FastAPI", "Django", "Flask", "Node.js", "Java Web", "WebSocket", "Netty"],
    "ai_collaboration": ["ChatGPT", "Claude Code", "Cursor", "AI Agent", "Agent", "RAG", "MCP", "Spring AI", "大模型"],
    "analytics_reporting": ["统计分析", "指标体系", "数据报表", "数据分析", "可视化", "报表", "指标", "CRITIC", "熵权法"],
    "cs_fundamentals": ["HTTP", "请求响应", "数据库读写", "前端渲染", "计算机基础", "接口文档"],
    "crud_project": ["CRUD", "Side Project", "课程项目", "前后端"],
    "sql_crud": ["SQL", "MySQL", "PostgreSQL", "增删改查", "CRUD", "联表", "表名", "字段名"],
    "frontend_basic": ["HTML", "CSS", "JavaScript", "React", "Vue", "WebSocket"],
    "git_workflow": ["Git", "branch", "commit", "PR", "Pull Request", "版本管理"],
    "internship_availability": ["实习", "每周", "4天", "3个月"],
    "confirmation_required": ["到岗", "入职", "base", "现场", "远程", "薪资", "毕业", "转正"],
}

SKILL_CATEGORY = {
    skill.casefold(): category
    for category, skills in CAPABILITY_SKILLS.items()
    for skill in skills
}

PROJECT_DEPTH_MARKERS = ["设计", "优化", "架构", "封装", "实现", "解决", "提升", "降低", "吞吐", "高并发", "幂等", "解耦", "%"]
RESPONSIBILITY_MARKERS = ["负责", "主导", "独立", "设计", "搭建", "封装", "引入", "实现", "核心", "第一作者"]
PRODUCT_MARKERS = ["用户", "业务", "场景", "流程", "体验", "需求", "优化", "闭环", "自动化", "提示", "异常", "设计"]


@dataclass(slots=True)
class Evidence:
    text: str
    source: str
    strength: float
    skills: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateProfile:
    skills: list[str]
    skill_sources: dict[str, list[Evidence]]
    project_evidence: list[Evidence]
    general_evidence: list[Evidence]
    education_rank: int
    education_text: str
    resume_text: str


class ScoringService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm
        self.requirement_judge = LLMRequirementJudge(llm)

    def score(
        self,
        resume: ResumeExtraction,
        job: JobRequirement,
        weights: ScoringWeights | None = None,
    ) -> MatchResult:
        weights = weights or ScoringWeights()
        profile = self._build_candidate_profile(resume)
        requirements = job.atomic_requirements or self._fallback_requirements(job)
        requirement_results = [self._score_requirement(requirement, profile) for requirement in requirements]

        breakdown = self._build_breakdown(requirement_results)
        eligibility = self._eligibility(requirement_results)
        score = self._aggregate_score(requirement_results, breakdown, weights, eligibility)
        confidence = self._confidence_score(requirement_results, profile)

        matched_keywords = unique_keep_order(
            skill
            for result in requirement_results
            for skill in result.matched_skills
            if result.score >= 45
        )
        missing_keywords = unique_keep_order(
            example
            for requirement, result in zip(requirements, requirement_results)
            if result.score < 60
            for example in (requirement.examples or [requirement.text])
        )

        result = MatchResult(
            score=score,
            level=self._level(score, eligibility),
            eligibility=eligibility,
            confidence_score=confidence,
            breakdown=breakdown,
            weights=weights,
            matched_keywords=matched_keywords,
            missing_keywords=missing_keywords[:12],
            requirement_results=requirement_results,
            strengths=self._strengths(requirement_results),
            gaps=self._gaps(requirement_results),
            risks=self._risks(requirement_results, confidence),
            reason=self._reason(score, eligibility, requirement_results),
            suggestions=self._suggestions(requirement_results),
            ai_review=self._ai_review(resume, job, score, requirement_results),
        )
        return result

    def _build_candidate_profile(self, resume: ResumeExtraction) -> CandidateProfile:
        skill_sources: dict[str, list[Evidence]] = {}
        project_evidence: list[Evidence] = []
        general_evidence: list[Evidence] = []

        for skill in resume.background.skills:
            normalized = self._normalize_skill(skill)
            evidence = Evidence(text=f"技能栏：{skill}", source="skill_section", strength=55, skills=[normalized])
            skill_sources.setdefault(normalized, []).append(evidence)
            general_evidence.append(evidence)

        for project in resume.background.projects:
            text = " ".join(
                [
                    project.name,
                    project.description,
                    " ".join(project.technologies),
                    " ".join(project.highlights),
                ]
            ).strip()
            if not text:
                continue
            skills = unique_keep_order([self._normalize_skill(skill) for skill in project.technologies] + self._extract_known_skills(text))
            strength = self._evidence_strength(text, "project")
            evidence = Evidence(text=text, source=f"project:{project.name}", strength=strength, skills=skills)
            project_evidence.append(evidence)
            general_evidence.append(evidence)
            for skill in skills:
                skill_sources.setdefault(skill, []).append(evidence)

        for section_name, section in resume.sections.items():
            if section_name in {"project", "skills", "full_text", "basic_info"}:
                continue
            if section.text:
                evidence = Evidence(
                    text=section.text,
                    source=f"section:{section_name}",
                    strength=self._evidence_strength(section.text, section_name),
                    skills=self._extract_known_skills(section.text),
                )
                general_evidence.append(evidence)
                for skill in evidence.skills:
                    skill_sources.setdefault(skill, []).append(evidence)

        education_text = " ".join(item.school + item.degree + item.major for item in resume.background.education)
        education_rank = max([self._degree_rank(item.degree + item.school + item.major) for item in resume.background.education] or [0])

        return CandidateProfile(
            skills=unique_keep_order(skill_sources.keys()),
            skill_sources=skill_sources,
            project_evidence=project_evidence,
            general_evidence=general_evidence,
            education_rank=education_rank,
            education_text=education_text,
            resume_text=str(resume.model_dump()),
        )

    def _score_requirement(self, requirement: AtomicRequirement, profile: CandidateProfile) -> RequirementMatch:
        if requirement.capability_category == "education":
            return self._score_education_requirement(requirement, profile)
        if self._is_confirmation_requirement(requirement):
            return self._score_confirmation_requirement(requirement, profile)

        evidence = self._retrieve_evidence(requirement, profile)
        relation, semantic_score, matched_skills = self._semantic_match(requirement, profile, evidence)
        if relation == "无证据":
            evidence = []
        evidence_strength = max([item.strength for item in evidence] or [0])
        proficiency_score = self._proficiency_score(requirement, evidence)
        project_depth = self._project_depth(evidence)
        responsibility_score = self._responsibility_score(evidence)
        recency_score = self._recency_score(evidence)

        raw_score = (
            semantic_score * 0.30
            + evidence_strength * 0.25
            + proficiency_score * 0.15
            + project_depth * 0.15
            + responsibility_score * 0.10
            + recency_score * 0.05
        )
        raw_score = self._apply_requirement_caps(requirement, raw_score, semantic_score, matched_skills)
        rule_score = raw_score
        evidence_pool = self._build_evidence_pool(requirement, profile, evidence)
        judge_result = (
            self.requirement_judge.judge(requirement, evidence_pool, rule_score)
            if self._should_use_judge(requirement, rule_score, evidence, profile)
            else None
        )
        fusion_evidence_strength = evidence_strength
        if judge_result and (judge_result.direct_evidence or judge_result.inferred_evidence):
            fusion_evidence_strength = max(fusion_evidence_strength, max([item.strength for item in evidence_pool] or [0]))
        raw_score = self._fuse_judge_score(requirement, rule_score, fusion_evidence_strength, judge_result)
        status = self._judge_status(raw_score, evidence, judge_result)
        confidence = self._requirement_confidence(semantic_score, evidence_strength, evidence)
        if judge_result:
            confidence = round(confidence * 0.55 + judge_result.confidence * 0.45, 1)
        reason = self._requirement_reason(requirement, relation, matched_skills, evidence, status)
        if judge_result and judge_result.reason:
            reason = judge_result.reason

        return RequirementMatch(
            requirement_id=requirement.id,
            requirement=requirement.text,
            category=requirement.capability_category,
            weight=requirement.weight,
            status=status,
            score=round(max(0, min(raw_score, 100)), 1),
            semantic_score=round(semantic_score, 1),
            evidence_strength=round(evidence_strength, 1),
            proficiency_score=round(proficiency_score, 1),
            project_depth=round(project_depth, 1),
            responsibility_score=round(responsibility_score, 1),
            recency_score=round(recency_score, 1),
            relation=relation,
            matched_skills=matched_skills,
            evidence=[item.text[:260] for item in evidence[:4]],
            direct_evidence=self._direct_evidence_text(evidence, judge_result, status),
            inferred_evidence=judge_result.inferred_evidence if judge_result else [],
            missing_evidence=judge_result.missing_evidence if judge_result else self._requirement_gaps(requirement, matched_skills, status),
            rule_score=round(rule_score, 1),
            llm_score=round(judge_result.score, 1) if judge_result else 0,
            judge_confidence=round(judge_result.confidence, 1) if judge_result else 0,
            reason=reason,
            gaps=judge_result.missing_evidence if judge_result else self._requirement_gaps(requirement, matched_skills, status),
            confidence=round(confidence, 1),
        )

    def _score_confirmation_requirement(self, requirement: AtomicRequirement, profile: CandidateProfile) -> RequirementMatch:
        evidence = self._retrieve_evidence(requirement, profile)
        has_direct_evidence = bool(evidence)
        score = 88 if has_direct_evidence else 50
        status = "MOSTLY_MATCHED" if has_direct_evidence else "INSUFFICIENT_EVIDENCE"
        reason = (
            "简历中发现该确定性条件的直接证据"
            if has_direct_evidence
            else "简历未写明该确定性条件，需要单独确认，不能据此判定不满足"
        )
        missing = [] if has_direct_evidence else [f"需确认：{requirement.text}"]
        return RequirementMatch(
            requirement_id=requirement.id,
            requirement=requirement.text,
            category=requirement.capability_category,
            weight=requirement.weight,
            status=status,
            score=score,
            semantic_score=88 if has_direct_evidence else 50,
            evidence_strength=max([item.strength for item in evidence] or [0]),
            proficiency_score=60,
            project_depth=0,
            responsibility_score=0,
            recency_score=60,
            relation="确定性条件需确认" if not has_direct_evidence else "直接证据匹配",
            matched_skills=[],
            evidence=[item.text[:260] for item in evidence[:4]],
            direct_evidence=[item.text[:260] for item in evidence[:4]],
            inferred_evidence=[],
            missing_evidence=missing,
            rule_score=score,
            llm_score=0,
            judge_confidence=0,
            reason=reason,
            gaps=missing,
            confidence=80 if has_direct_evidence else 35,
        )

    def _build_evidence_pool(
        self,
        requirement: AtomicRequirement,
        profile: CandidateProfile,
        rule_evidence: list[Evidence],
    ) -> list[JudgeEvidence]:
        evidence: list[Evidence] = list(rule_evidence)
        allow_inference = requirement.evidence_logic in {"INFER_ALLOWED", "PARTIAL_OK"} and not requirement.is_hard
        if allow_inference:
            evidence.extend(profile.project_evidence)
            evidence.extend(item for item in profile.general_evidence if item.source == "skill_section")
        elif requirement.capability_category == "education" and profile.education_text:
            evidence.append(Evidence(text=profile.education_text, source="education", strength=90))

        deduped = self._dedupe_evidence(evidence)
        return [
            JudgeEvidence(source=item.source, text=item.text, strength=item.strength)
            for item in deduped[:8]
            if item.text.strip()
        ]

    def _should_use_judge(
        self,
        requirement: AtomicRequirement,
        rule_score: float,
        evidence: list[Evidence],
        profile: CandidateProfile,
    ) -> bool:
        if not self.llm.enabled:
            return False
        if self._is_confirmation_requirement(requirement):
            return False
        if requirement.is_hard or requirement.evidence_logic == "DIRECT_ONLY":
            return False
        if requirement.capability_category in {"education", "internship_availability", "confirmation_required"}:
            return False
        if rule_score >= 85 and evidence:
            return False

        inferable_categories = {
            "cs_fundamentals",
            "crud_project",
            "sql_crud",
            "frontend_basic",
            "ai_collaboration",
            "product_creativity",
            "analytics_reporting",
        }
        if requirement.evidence_logic == "INFER_ALLOWED":
            return bool(profile.project_evidence or evidence)
        if requirement.capability_category in inferable_categories and rule_score < 75:
            return bool(profile.project_evidence or evidence)
        return False

    def _fuse_judge_score(
        self,
        requirement: AtomicRequirement,
        rule_score: float,
        evidence_strength: float,
        judge_result: RequirementJudgeResult | None,
    ) -> float:
        if not judge_result:
            return rule_score

        if requirement.evidence_logic == "DIRECT_ONLY" and not judge_result.direct_evidence:
            return min(rule_score, judge_result.score, 45)

        if not judge_result.direct_evidence and not judge_result.inferred_evidence:
            if rule_score >= 75 and evidence_strength >= 50:
                return max(rule_score * 0.85 + judge_result.score * 0.15, 70)
            return min(rule_score, judge_result.score, 25)

        llm_weight = 0.30 if judge_result.confidence >= 60 else 0.15
        rule_weight = 0.50 if judge_result.confidence >= 60 else 0.65
        evidence_weight = 1 - rule_weight - llm_weight
        fused = rule_score * rule_weight + judge_result.score * llm_weight + evidence_strength * evidence_weight

        if not judge_result.direct_evidence and judge_result.inferred_evidence:
            fused = min(max(fused, judge_result.score), 72)
        return max(0, min(fused, 100))

    def _judge_status(
        self,
        score: float,
        evidence: list[Evidence],
        judge_result: RequirementJudgeResult | None,
    ) -> str:
        if judge_result and not judge_result.direct_evidence and not judge_result.inferred_evidence:
            if score >= 70 and evidence:
                return self._status_from_score(score, evidence)
            return "NOT_MATCHED"
        if judge_result and judge_result.status == "INSUFFICIENT_EVIDENCE" and score < 60:
            return "INSUFFICIENT_EVIDENCE"
        return self._status_from_score(score, evidence)

    @staticmethod
    def _direct_evidence_text(
        evidence: list[Evidence],
        judge_result: RequirementJudgeResult | None,
        status: str,
    ) -> list[str]:
        if judge_result and judge_result.direct_evidence:
            return judge_result.direct_evidence
        if judge_result and status in {"FULLY_MATCHED", "MOSTLY_MATCHED"} and evidence:
            return [item.text[:260] for item in evidence[:4]]
        if judge_result:
            return []
        return [item.text[:260] for item in evidence[:4]]

    def _score_education_requirement(self, requirement: AtomicRequirement, profile: CandidateProfile) -> RequirementMatch:
        required_rank = self._required_degree_rank(requirement.text)
        degree_matched = profile.education_rank >= required_rank if required_rank else bool(profile.education_rank)
        major_required = self._requires_computer_related_major(requirement.text)
        major_matched = self._has_computer_related_major(profile.education_text) if major_required else True

        if degree_matched and major_matched:
            semantic_score = 100
        elif degree_matched and major_required:
            semantic_score = 65
        elif not required_rank and profile.education_rank:
            semantic_score = 80
        else:
            semantic_score = 0
        status = "FULLY_MATCHED" if semantic_score >= 90 else "NOT_MATCHED"
        evidence_strength = 90 if profile.education_text else 0
        score = 100 if semantic_score >= 90 else 0
        missing_evidence = self._education_missing_evidence(required_rank, degree_matched, major_required, major_matched)
        return RequirementMatch(
            requirement_id=requirement.id,
            requirement=requirement.text,
            category=requirement.capability_category,
            weight=requirement.weight,
            status=status,
            score=score,
            semantic_score=semantic_score,
            evidence_strength=evidence_strength,
            proficiency_score=100 if score else 0,
            project_depth=60 if score else 0,
            responsibility_score=60 if score else 0,
            recency_score=80 if score else 0,
            relation="硬性学历条件",
            matched_skills=[],
            evidence=[profile.education_text] if profile.education_text else [],
            direct_evidence=[profile.education_text] if profile.education_text else [],
            inferred_evidence=[],
            missing_evidence=missing_evidence,
            rule_score=score,
            llm_score=0,
            judge_confidence=0,
            reason="学历满足岗位要求" if score else "未发现满足岗位要求的学历证据",
            gaps=missing_evidence,
            confidence=95 if profile.education_text else 45,
        )

    def _retrieve_evidence(self, requirement: AtomicRequirement, profile: CandidateProfile) -> list[Evidence]:
        query_terms = unique_keep_order(requirement.examples + self._category_terms(requirement.capability_category) + [requirement.text])
        evidence: list[Evidence] = []

        for skill in self._candidate_skills_for_requirement(requirement):
            normalized = self._normalize_skill(skill)
            evidence.extend(profile.skill_sources.get(normalized, []))

        for item in profile.general_evidence:
            if item.source.startswith("section:full_text") or item.source.startswith("section:basic_info"):
                continue
            if contains_any(item.text, query_terms):
                evidence.append(item)
            elif requirement.capability_category == "product_creativity" and any(marker in item.text for marker in PRODUCT_MARKERS):
                evidence.append(item)
            elif requirement.capability_category == "analytics_reporting" and any(marker in item.text for marker in ["指标", "统计", "报表", "数据", "分析", "实验"]):
                evidence.append(item)

        return self._dedupe_evidence(evidence)[:6]

    def _semantic_match(
        self,
        requirement: AtomicRequirement,
        profile: CandidateProfile,
        evidence: list[Evidence],
    ) -> tuple[str, float, list[str]]:
        category = requirement.capability_category
        explicit_examples = [self._normalize_skill(skill) for skill in requirement.examples]
        matched_exact = [skill for skill in explicit_examples if self._normalize_skill(skill) in profile.skill_sources]
        if requirement.logic == "AND" and requirement.min_count > 1:
            matched_components = unique_keep_order(matched_exact + self._evidence_term_hits(requirement, evidence, include_category=False))
            if requirement.capability_category == "crud_project" and profile.project_evidence:
                matched_components.append("项目经历")
                matched_components = unique_keep_order(matched_components)
            if len(matched_components) >= requirement.min_count:
                return "多条件证据满足", 92, matched_components
            if matched_components:
                return "部分条件匹配", 45 + min(len(matched_components) * 10, 25), matched_components
            return "无证据", 0, []

        if matched_exact:
            return "精确或等价匹配", 100, unique_keep_order(matched_exact)

        category_skills = CAPABILITY_SKILLS.get(category, [])
        matched_category = [skill for skill in category_skills if self._normalize_skill(skill) in profile.skill_sources]
        if category == "ai_collaboration" and requirement.examples:
            if evidence:
                hits = self._evidence_term_hits(requirement, evidence, include_category=False)
                if hits:
                    return "AI 工具证据匹配", 82, hits
                broad_hits = [skill for skill in matched_category if skill not in {"Cursor", "Claude Code", "Claude", "ChatGPT"}]
                if broad_hits:
                    return "AI 相关经历弱匹配", 55, unique_keep_order(broad_hits)
            return "无证据", 0, []
        if matched_category and (requirement.is_open_ended or not requirement.examples):
            return "同类能力满足", 95, unique_keep_order(matched_category)

        if category == "web_cache_mq":
            components = []
            for sub_category in ["web_backend", "cache", "message_queue"]:
                hits = [skill for skill in CAPABILITY_SKILLS[sub_category] if self._normalize_skill(skill) in profile.skill_sources]
                if hits:
                    components.append(hits[0])
            if len(components) >= requirement.min_count:
                return "组合能力满足", 92, unique_keep_order(components)
            if components:
                return "部分组件匹配", 58, unique_keep_order(components)

        if category == "data_storage":
            storage_hits = [skill for skill in CAPABILITY_SKILLS["data_storage"] if self._normalize_skill(skill) in profile.skill_sources]
            if storage_hits:
                return "同类存储能力满足", 90, unique_keep_order(storage_hits)

        if category == "analytics_reporting" and evidence:
            return "业务语义证据匹配", 76 if len(evidence) >= 2 else 58, self._skills_from_evidence(evidence)

        if category == "ai_collaboration" and evidence:
            return "AI 协同证据匹配", 82, self._skills_from_evidence(evidence)

        if category == "product_creativity" and evidence:
            return "软能力行为证据", 62, self._skills_from_evidence(evidence)

        if category in {"cs_fundamentals", "crud_project", "sql_crud", "frontend_basic", "git_workflow"} and evidence:
            hits = self._evidence_term_hits(requirement, evidence)
            if hits:
                return "要求证据匹配", 68, hits
            return "弱证据关联", 35, self._skills_from_evidence(evidence)

        if category in {"internship_availability", "confirmation_required"} and evidence:
            hits = self._evidence_term_hits(requirement, evidence)
            return "实习时间证据匹配", 80 if hits else 35, hits

        if evidence:
            return "弱语义关联", 35, self._skills_from_evidence(evidence)
        return "无证据", 0, []

    def _llm_requirement_review(
        self,
        requirement: AtomicRequirement,
        evidence: list[Evidence],
        rule_score: float,
    ) -> dict[str, Any]:
        if not self.llm.enabled or requirement.capability_category not in {"analytics_reporting", "ai_collaboration", "product_creativity"}:
            return {}
        system_prompt = (
            "你是受约束的招聘匹配评审器。只能根据给定简历证据判断，"
            "不得补充不存在的信息。请只返回 JSON。"
        )
        user_prompt = {
            "requirement": requirement.model_dump(),
            "evidence": [item.text[:500] for item in evidence[:4]],
            "rule_score": round(rule_score, 1),
            "output_schema": {
                "status": "FULLY_MATCHED|MOSTLY_MATCHED|PARTIALLY_MATCHED|INSUFFICIENT_EVIDENCE|NOT_MATCHED",
                "reason": "引用证据说明判断",
                "confidence": 0,
            },
        }
        return self.llm.chat_json(system_prompt, str(user_prompt))

    def _aggregate_score(
        self,
        results: list[RequirementMatch],
        breakdown: ScoreBreakdown,
        weights: ScoringWeights,
        eligibility: str,
    ) -> int:
        if not results:
            return 0
        total_weight = sum(max(result.weight, 0) for result in results) or 1
        requirement_score = sum(result.score * max(result.weight, 0) for result in results) / total_weight
        normalized_weights = weights.normalized()
        dimension_score = (
            breakdown.skill_match * normalized_weights["skill_match"]
            + breakdown.experience_relevance * normalized_weights["experience_relevance"]
            + breakdown.project_relevance * normalized_weights["project_relevance"]
            + breakdown.education_fit * normalized_weights["education_fit"]
            + breakdown.keyword_coverage * normalized_weights["keyword_coverage"]
        )
        # JD 原子要求决定主要结论，前端权重用于微调不同评分维度的侧重。
        score = requirement_score * 0.75 + dimension_score * 0.25
        if eligibility == "FAIL":
            score = min(score, 59)
        elif eligibility == "CONDITIONAL":
            score = min(score, 82)
        return round(max(0, min(score, 100)))

    @staticmethod
    def _eligibility(results: list[RequirementMatch]) -> str:
        hard_results = [result for result in results if result.category == "education" or "硬性" in result.relation]
        if any(result.status == "NOT_MATCHED" for result in hard_results):
            return "FAIL"
        if any(result.status == "INSUFFICIENT_EVIDENCE" for result in hard_results):
            return "CONDITIONAL"
        return "PASS"

    @staticmethod
    def _confidence_score(results: list[RequirementMatch], profile: CandidateProfile) -> int:
        if not results:
            return 0
        evidence_completeness = mean([result.evidence_strength for result in results])
        directness = mean([result.semantic_score for result in results])
        rule_pass = mean([result.confidence for result in results])
        parse_quality = 90 if profile.resume_text else 40
        confidence = evidence_completeness * 0.25 + directness * 0.20 + rule_pass * 0.40 + parse_quality * 0.15
        return round(max(0, min(confidence, 100)))

    def _build_breakdown(self, results: list[RequirementMatch]) -> ScoreBreakdown:
        def avg_selected(selected: list[float], default: float = 60) -> float:
            return round(mean(selected), 1) if selected else default

        confirmation_categories = {"internship_availability", "confirmation_required"}
        education_scores = [result.score for result in results if result.category == "education"]
        confirmation_scores = [result.score for result in results if result.category in confirmation_categories]
        non_confirmation = [result for result in results if result.category not in confirmation_categories]
        ability_results = [
            result
            for result in non_confirmation
            if result.category != "education" and not self._looks_like_project_or_soft_requirement(result)
        ]
        project_results = [
            result
            for result in non_confirmation
            if result.category != "education"
            and (
                self._looks_like_project_or_soft_requirement(result)
                or result.project_depth >= 55
                or bool(result.inferred_evidence)
            )
        ]
        evidence_experience_scores = [
            self._evidence_aware_score(result)
            for result in non_confirmation
            if result.direct_evidence or result.inferred_evidence
        ]

        return ScoreBreakdown(
            skill_match=avg_selected([self._evidence_aware_score(result) for result in ability_results], 60),
            experience_relevance=avg_selected(
                confirmation_scores + evidence_experience_scores,
                avg_selected(evidence_experience_scores, 65),
            ),
            project_relevance=avg_selected([self._project_dimension_score(result) for result in project_results], 50),
            education_fit=avg_selected(education_scores, 60),
            keyword_coverage=avg_selected([result.score for result in non_confirmation], 0),
        )

    @staticmethod
    def _looks_like_project_or_soft_requirement(result: RequirementMatch) -> bool:
        return result.category in {
            "crud_project",
            "analytics_reporting",
            "product_creativity",
            "cs_fundamentals",
            "sql_crud",
            "frontend_basic",
        }

    @staticmethod
    def _evidence_aware_score(result: RequirementMatch) -> float:
        if result.llm_score and result.inferred_evidence:
            return max(result.score, min(result.llm_score, 72))
        return result.score

    @staticmethod
    def _project_dimension_score(result: RequirementMatch) -> float:
        evidence_bonus = 8 if result.inferred_evidence else 0
        direct_bonus = 5 if result.direct_evidence else 0
        return max(result.score, min(100, result.project_depth + evidence_bonus + direct_bonus))

    @staticmethod
    def _status_from_score(score: float, evidence: list[Evidence]) -> str:
        if score >= 88:
            return "FULLY_MATCHED"
        if score >= 72:
            return "MOSTLY_MATCHED"
        if score >= 45:
            return "PARTIALLY_MATCHED"
        if evidence:
            return "INSUFFICIENT_EVIDENCE"
        return "NOT_MATCHED"

    @staticmethod
    def _apply_requirement_caps(
        requirement: AtomicRequirement,
        raw_score: float,
        semantic_score: float,
        matched_skills: list[str],
    ) -> float:
        if requirement.logic == "AND" and requirement.min_count > 1 and len(matched_skills) < requirement.min_count:
            return min(raw_score, 58 if matched_skills else 35)
        if semantic_score <= 0:
            return min(raw_score, 25)
        if requirement.capability_category in {"git_workflow", "internship_availability", "confirmation_required"} and not matched_skills:
            return min(raw_score, 35)
        if requirement.capability_category == "ai_collaboration" and semantic_score < 70:
            return min(raw_score, 62)
        return raw_score

    @staticmethod
    def _level(score: int | float, eligibility: str = "PASS") -> str:
        if eligibility == "FAIL":
            return "硬性条件不满足"
        if score >= 90:
            return "极高匹配"
        if score >= 80:
            return "高度匹配"
        if score >= 70:
            return "较为匹配"
        if score >= 60:
            return "部分匹配"
        return "低匹配"

    @staticmethod
    def _reason(score: int, eligibility: str, results: list[RequirementMatch]) -> str:
        top = [result for result in results if result.score >= 75][:3]
        weak = [result for result in results if result.score < 60][:3]
        top_text = "；".join(f"{item.requirement_id}:{item.reason}" for item in top) or "暂无强匹配项"
        weak_text = "；".join(f"{item.requirement_id}:{item.reason}" for item in weak) or "主要要求覆盖较完整"
        return f"资格状态 {eligibility}，综合匹配分 {score}。优势：{top_text}。缺口：{weak_text}。"

    @staticmethod
    def _suggestions(results: list[RequirementMatch]) -> list[str]:
        suggestions = []
        for result in results:
            if result.score < 70:
                suggestions.extend(result.gaps or [f"补充 {result.requirement} 的项目证据。"])
        if not suggestions:
            suggestions.append("当前岗位要求覆盖较好，可进一步量化项目成果和职责边界。")
        return unique_keep_order(suggestions)[:6]

    @staticmethod
    def _strengths(results: list[RequirementMatch]) -> list[str]:
        return [f"{result.requirement}：{result.reason}" for result in results if result.score >= 75][:5]

    @staticmethod
    def _gaps(results: list[RequirementMatch]) -> list[str]:
        gaps = [gap for result in results if result.score < 70 for gap in result.gaps]
        return unique_keep_order(gaps)[:6]

    @staticmethod
    def _risks(results: list[RequirementMatch], confidence: int) -> list[str]:
        risks = []
        if confidence < 70:
            risks.append("评分置信度偏低，建议人工复核关键证据。")
        risks.extend(
            f"{result.requirement} 证据不足"
            for result in results
            if result.status == "INSUFFICIENT_EVIDENCE"
        )
        return unique_keep_order(risks)[:5]

    def _ai_review(
        self,
        resume: ResumeExtraction,
        job: JobRequirement,
        score: int,
        results: list[RequirementMatch],
    ) -> str:
        system_prompt = "你是招聘简历匹配评估助手，请基于分项证据用 100 字以内给出客观评语。"
        user_prompt = (
            f"简历摘要：{resume.summary}\n"
            f"岗位要求：{job.raw_description or job.model_dump()}\n"
            f"系统分项：{[result.model_dump() for result in results]}\n"
            f"规则总分：{score}\n"
            "请给出简短匹配评语，不要改分。"
        )
        return self.llm.chat_text(system_prompt, user_prompt).strip()

    def _fallback_requirements(self, job: JobRequirement) -> list[AtomicRequirement]:
        requirements: list[AtomicRequirement] = []
        if job.education_requirements:
            requirements.append(
                AtomicRequirement(
                    id="R1",
                    text=job.education_requirements,
                    requirement_type="hard",
                    capability_category="education",
                    is_hard=True,
                    is_open_ended=False,
                    weight=10,
                )
            )
        if job.required_skills:
            requirements.append(
                AtomicRequirement(
                    id=f"R{len(requirements)+1}",
                    text="、".join(job.required_skills),
                    requirement_type="core",
                    capability_category="general",
                    examples=job.required_skills,
                    logic="OR",
                    min_count=1,
                    weight=70,
                )
            )
        if job.job_keywords:
            requirements.append(
                AtomicRequirement(
                    id=f"R{len(requirements)+1}",
                    text="、".join(job.job_keywords),
                    requirement_type="core",
                    capability_category="general",
                    examples=job.job_keywords,
                    weight=20,
                )
            )
        return requirements

    def _candidate_skills_for_requirement(self, requirement: AtomicRequirement) -> list[str]:
        skills = [self._normalize_skill(skill) for skill in requirement.examples]
        skills.extend(CAPABILITY_SKILLS.get(requirement.capability_category, []))
        if requirement.capability_category == "web_cache_mq":
            skills.extend(CAPABILITY_SKILLS["web_backend"] + CAPABILITY_SKILLS["cache"] + CAPABILITY_SKILLS["message_queue"])
        return unique_keep_order(skills)

    @staticmethod
    def _category_terms(category: str) -> list[str]:
        terms = {
            "backend_language": ["后端", "语言", "服务端", "接口"],
            "data_storage": ["存储", "数据库", "缓存", "数据"],
            "web_cache_mq": ["Web", "缓存", "消息队列", "异步", "队列"],
            "analytics_reporting": ["统计", "指标", "报表", "分析", "可视化"],
            "ai_collaboration": ["AI", "大模型", "Agent", "RAG", "ChatGPT", "Claude", "Cursor"],
            "product_creativity": ["用户", "产品", "需求", "体验", "设计", "优化", "创新"],
            "cs_fundamentals": ["HTTP", "请求响应", "数据库读写", "前端渲染", "原理", "接口"],
            "crud_project": ["CRUD", "增删改查", "前后端", "项目", "课程项目", "side project"],
            "sql_crud": ["SQL", "增删改查", "联表", "表名", "字段名", "数据库"],
            "frontend_basic": ["HTML", "CSS", "JavaScript", "React", "Vue", "前端"],
            "git_workflow": ["Git", "branch", "commit", "PR", "版本管理"],
            "internship_availability": ["每周", "实习", "4天", "3个月"],
            "confirmation_required": ["到岗", "入职", "base", "地点", "现场", "远程", "薪资", "毕业", "转正"],
        }
        return terms.get(category, [])

    @staticmethod
    def _is_confirmation_requirement(requirement: AtomicRequirement) -> bool:
        return requirement.requirement_type == "constraint" or requirement.capability_category in {
            "internship_availability",
            "confirmation_required",
        }

    @staticmethod
    def _evidence_strength(text: str, source: str) -> float:
        if not text:
            return 0
        if source == "skill_section":
            return 55
        base = 78 if source.startswith("project") or source in {"project", "work", "internship"} else 62
        if any(marker in text for marker in ["%", "提升", "降低", "优化", "吞吐", "时延", "准确率"]):
            base += 12
        if any(marker in text for marker in RESPONSIBILITY_MARKERS):
            base += 6
        return min(base, 100)

    @staticmethod
    def _proficiency_score(requirement: AtomicRequirement, evidence: list[Evidence]) -> float:
        text = " ".join(item.text for item in evidence)
        if any(token in text for token in ["深入", "精通", "设计", "优化", "架构", "负责"]):
            candidate_level = 5
        elif any(token in text for token in ["熟练", "掌握"]):
            candidate_level = 4
        elif any(token in text for token in ["熟悉", "独立", "实现", "使用"]):
            candidate_level = 3
        elif any(token in text for token in ["了解", "学习"]):
            candidate_level = 1
        elif evidence:
            candidate_level = 2
        else:
            candidate_level = 0

        required_level = 3 if "熟悉" in requirement.proficiency else 2
        if candidate_level >= required_level + 1:
            return 100
        if candidate_level == required_level:
            return 85
        if candidate_level == required_level - 1:
            return 60
        if candidate_level > 0:
            return 35
        return 0

    @staticmethod
    def _project_depth(evidence: list[Evidence]) -> float:
        if not evidence:
            return 0
        text = " ".join(item.text for item in evidence)
        marker_count = sum(1 for marker in PROJECT_DEPTH_MARKERS if marker in text)
        if marker_count >= 5:
            return 92
        if marker_count >= 3:
            return 80
        if marker_count >= 1:
            return 68
        if any(item.source.startswith("project") for item in evidence):
            return 55
        return 35

    @staticmethod
    def _responsibility_score(evidence: list[Evidence]) -> float:
        if not evidence:
            return 0
        text = " ".join(item.text for item in evidence)
        if any(token in text for token in ["第一作者", "负责核心", "主导", "架构设计"]):
            return 92
        if any(token in text for token in RESPONSIBILITY_MARKERS):
            return 78
        return 45

    @staticmethod
    def _recency_score(evidence: list[Evidence]) -> float:
        text = " ".join(item.text for item in evidence)
        years = [int(year) for year in re.findall(r"(20\d{2})", text)]
        if not years:
            return 60
        latest = max(years)
        if latest >= 2025:
            return 100
        if latest >= 2024:
            return 90
        if latest >= 2023:
            return 75
        return 55

    @staticmethod
    def _requirement_confidence(semantic_score: float, evidence_strength: float, evidence: list[Evidence]) -> float:
        evidence_count_score = min(len(evidence) / 3, 1) * 100
        return semantic_score * 0.35 + evidence_strength * 0.35 + evidence_count_score * 0.30

    @staticmethod
    def _requirement_reason(
        requirement: AtomicRequirement,
        relation: str,
        matched_skills: list[str],
        evidence: list[Evidence],
        status: str,
    ) -> str:
        if status == "NOT_MATCHED":
            return f"未找到与“{requirement.text}”相关的有效证据"
        skill_text = "、".join(matched_skills) if matched_skills else "相关经历"
        evidence_text = evidence[0].text[:120] if evidence else "暂无证据"
        return f"{relation}：{skill_text}。证据：{evidence_text}"

    @staticmethod
    def _requirement_gaps(requirement: AtomicRequirement, matched_skills: list[str], status: str) -> list[str]:
        if status in {"FULLY_MATCHED", "MOSTLY_MATCHED"}:
            return []
        if requirement.examples:
            return [f"缺少或未充分体现 {requirement.text} 的直接项目证据，参考技能：{'、'.join(requirement.examples)}"]
        return [f"缺少或未充分体现 {requirement.text} 的直接项目证据"]

    @staticmethod
    def _dedupe_evidence(evidence: list[Evidence]) -> list[Evidence]:
        seen: set[str] = set()
        result: list[Evidence] = []
        for item in sorted(evidence, key=lambda value: value.strength, reverse=True):
            key = item.text[:180].casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _skills_from_evidence(evidence: list[Evidence]) -> list[str]:
        return unique_keep_order(skill for item in evidence for skill in item.skills)

    def _extract_known_skills(self, text: str) -> list[str]:
        skills = []
        normalized_text = text.casefold()
        for category_skills in CAPABILITY_SKILLS.values():
            for skill in category_skills:
                if contains_term(normalized_text, skill):
                    skills.append(self._normalize_skill(skill))
        for alias, normalized in TECH_ALIASES.items():
            if contains_term(normalized_text, alias):
                skills.append(normalized)
        return unique_keep_order(skills)

    @staticmethod
    def _evidence_term_hits(
        requirement: AtomicRequirement,
        evidence: list[Evidence],
        include_category: bool = True,
    ) -> list[str]:
        category_terms = ScoringService._category_terms(requirement.capability_category) if include_category else []
        terms = unique_keep_order(requirement.examples + category_terms)
        hits = []
        for item in evidence:
            hits.extend(term for term in terms if contains_term(item.text, term))
        return unique_keep_order(hits)

    @staticmethod
    def _normalize_skill(skill: str) -> str:
        key = skill.strip().casefold().replace("-", " ")
        return TECH_ALIASES.get(key, skill.strip())

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
    def _required_degree_rank(text: str) -> int:
        if any(token in text for token in ["大专", "专科"]):
            return 2
        if any(token in text for token in ["本科", "学士", "Bachelor"]):
            return 3
        if any(token in text for token in ["硕士", "研究生", "Master"]):
            return 4
        if any(token in text for token in ["博士", "PhD"]):
            return 5
        return 0

    @staticmethod
    def _requires_computer_related_major(text: str) -> bool:
        return any(token in text for token in ["计算机相关专业", "计算机相关", "计算机专业"])

    @staticmethod
    def _has_computer_related_major(text: str) -> bool:
        computer_major_terms = [
            "计算机",
            "软件工程",
            "网络工程",
            "信息安全",
            "网络与信息安全",
            "数据科学",
            "人工智能",
            "物联网",
            "电子信息",
            "通信工程",
        ]
        return any(term in text for term in computer_major_terms)

    @staticmethod
    def _education_missing_evidence(
        required_rank: int,
        degree_matched: bool,
        major_required: bool,
        major_matched: bool,
    ) -> list[str]:
        missing = []
        if required_rank and not degree_matched:
            missing.append("未发现满足岗位要求的学历层次")
        if major_required and not major_matched:
            missing.append("未发现计算机相关专业证据")
        if not missing and not degree_matched:
            missing.append("学历条件可能不满足或未识别")
        return missing
