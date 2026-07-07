from __future__ import annotations

import re
import json
from dataclasses import dataclass
from typing import Any

from app.models.schemas import (
    BackgroundInfo,
    BasicInfo,
    EducationItem,
    ExtractedField,
    JobIntention,
    ProjectItem,
    ResumeExtraction,
    ResumeSection,
)
from app.services.llm_service import LLMService
from app.utils.text import clean_text, truncate_text, unique_keep_order


PHONE_RE = re.compile(r"(?:\+?86[- ]?)?1[3-9](?:[ -]?\d){9}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\s*\.\s*[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s，。；;]+|(?:github|gitee)\.com/[A-Za-z0-9_.-]+", re.I)
PERIOD_RE = re.compile(
    r"((?:19|20)\d{2}[./-](?:1[0-2]|0?[1-9])?)\s*(?:-|—|–|至|~|到)\s*((?:19|20)\d{2}[./-](?:1[0-2]|0?[1-9])?|至今|今|present)",
    re.I,
)
SINGLE_DATE_RE = re.compile(r"(?:19|20)\d{2}[./-](?:1[0-2]|0?[1-9])(?!\d)")

COMMON_SKILLS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Vue",
    "Vue.js",
    "FastAPI",
    "Flask",
    "Django",
    "Spring Boot",
    "Spring Cloud",
    "MyBatis",
    "MyBatis-Plus",
    "MySQL",
    "PostgreSQL",
    "Redis",
    "MongoDB",
    "Elasticsearch",
    "Docker",
    "Kubernetes",
    "Linux",
    "Git",
    "Nginx",
    "Serverless",
    "LLM",
    "大模型",
    "RAG",
    "机器学习",
    "深度学习",
    "PyTorch",
    "TensorFlow",
    "HTML",
    "CSS",
    "jQuery",
    "WXML",
    "WXSS",
]

SKILL_ALIASES = {
    "SpringBoot": "Spring Boot",
    "spring boot": "Spring Boot",
    "Mybatis Plus": "MyBatis-Plus",
    "MyBatis Plus": "MyBatis-Plus",
    "Mybatis": "MyBatis",
    "Jquery": "jQuery",
    "Html": "HTML",
    "Css": "CSS",
    "Elastic Search": "Elasticsearch",
    "Redis缓存": "Redis",
    "Vue3": "Vue.js 3",
    "wxml": "WXML",
    "wxss": "WXSS",
}

SECTION_ALIASES = {
    "basic_info": ["基本信息", "个人信息", "个人简历", "联系方式", "CONTACT", "PROFILE"],
    "job_intention": ["求职意向", "职业目标", "应聘岗位", "目标岗位", "JOB INTENTION"],
    "education": ["教育背景", "教育经历", "学习经历", "EDUCATIONAL BACKGROUND", "EDUCATION"],
    "work": ["工作经历", "工作经验", "任职经历", "WORK EXPERIENCE", "EMPLOYMENT"],
    "internship": ["实习经历", "实习经验", "INTERNSHIP"],
    "project": ["项目经历", "项目经验", "PROJECT EXPERIENCE", "PROJECT"],
    "research": ["科研经历", "研究经历", "RESEARCH"],
    "skills": ["专业技能", "个人技能", "技能清单", "技能特长", "SKILLS"],
    "honors": ["获奖经历", "个人荣誉", "荣誉奖项", "HONOR", "AWARD"],
    "certificates": ["证书", "资格证书", "CERTIFICATE"],
    "campus": ["校园经历", "社会实践", "社团经历", "SOCIAL PRACTICE", "CAMPUS"],
    "self_evaluation": ["自我评价", "个人评价", "SELF EVALUATION", "SUMMARY"],
    "papers": ["论文", "成果", "PUBLICATION"],
    "portfolio": ["个人作品", "开源项目", "作品集", "PORTFOLIO"],
}

SCHOOL_HINTS = ["大学", "学院", "学校", "研究院", "University", "College"]
DEGREE_TERMS = ["博士", "硕士", "研究生", "本科", "学士", "大专", "专科"]
COMPANY_HINTS = ["公司", "科技", "集团", "有限", "工作室", "实验室", "研究院"]


@dataclass(slots=True)
class FieldCandidate:
    value: str
    source: str
    confidence: float
    evidence: str
    normalized: bool = False


@dataclass(slots=True)
class SelectedField:
    source_key: str
    field: ExtractedField


class ResumeExtractionService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def extract(self, resume_text: str) -> ResumeExtraction:
        cleaned_text = clean_text(resume_text)
        sections = self._identify_sections(cleaned_text)
        rule_result = self._extract_by_rules(cleaned_text, sections)
        ai_result = self._ai_extract_by_sections(sections)
        merged = self._merge_ai_result(rule_result, ai_result)
        return merged

    def _identify_sections(self, text: str) -> dict[str, ResumeSection]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        sections: dict[str, ResumeSection] = {}
        current_name = "basic_info"
        current_title = "基本信息"
        current_start = 0
        current_lines: list[str] = []

        def flush(end_line: int) -> None:
            nonlocal current_lines
            content = clean_text("\n".join(current_lines))
            if not content:
                current_lines = []
                return
            existing = sections.get(current_name)
            if existing:
                existing.text = clean_text(f"{existing.text}\n{content}")
                existing.end_line = end_line
            else:
                sections[current_name] = ResumeSection(
                    name=current_name,
                    title=current_title,
                    text=content,
                    start_line=current_start,
                    end_line=end_line,
                )
            current_lines = []

        for index, line in enumerate(lines):
            matched_name = self._match_section_title(line)
            if matched_name == "basic_info" and index > 5:
                matched_name = ""
            if matched_name and index > 0:
                flush(index - 1)
                current_name = matched_name
                current_title = line
                current_start = index
                current_lines = []
                continue
            current_lines.append(line)
        flush(len(lines) - 1)

        if "full_text" not in sections:
            sections["full_text"] = ResumeSection(
                name="full_text",
                title="全文",
                text=text,
                start_line=0,
                end_line=max(len(lines) - 1, 0),
            )
        return sections

    def _extract_by_rules(self, text: str, sections: dict[str, ResumeSection]) -> ResumeExtraction:
        field_details: dict[str, ExtractedField] = {}
        warnings: list[str] = []

        name = self._select_field(
            "basic_info.name",
            self._name_candidates(text, sections),
            required=True,
            warnings=warnings,
        )
        phone = self._select_field(
            "basic_info.phone",
            self._phone_candidates(text, sections),
            required=True,
            warnings=warnings,
        )
        email = self._select_field(
            "basic_info.email",
            self._email_candidates(text, sections),
            required=True,
            warnings=warnings,
        )
        address = self._select_field(
            "basic_info.address",
            self._address_candidates(text, sections),
            required=True,
            warnings=warnings,
        )

        for detail in [name, phone, email, address]:
            field_details[detail.source_key] = detail.field  # type: ignore[attr-defined]

        education = self._extract_education(sections)
        projects = self._extract_projects(sections)
        skills = self._extract_skills(text)
        honors = self._section_lines(sections, "honors")[:12]
        certificates = self._section_lines(sections, "certificates")[:12]
        work_experience = self._section_lines(sections, "work") + self._section_lines(sections, "internship")
        research_experience = self._section_lines(sections, "research")
        self_evaluation = sections.get("self_evaluation", ResumeSection(name="self_evaluation")).text

        job_intention = self._extract_job_intention(sections)
        years = self._extract_years_of_experience(text)

        field_details["background.skills"] = self._field_from_value(
            ", ".join(skills),
            "dictionary",
            0.86 if skills else 0,
            "、".join(skills[:12]),
            normalized=True,
        )
        field_details["background.education"] = self._field_from_value(
            json.dumps(education[0].model_dump(), ensure_ascii=False) if education else "",
            "section_rule",
            0.78 if education else 0,
            sections.get("education", ResumeSection(name="education")).text[:160],
        )
        field_details["background.projects"] = self._field_from_value(
            f"{len(projects)} 个项目" if projects else "",
            "section_rule",
            0.72 if projects else 0,
            sections.get("project", ResumeSection(name="project")).text[:160],
        )

        return ResumeExtraction(
            basic_info=BasicInfo(
                name=name.field.normalized_value,
                phone=phone.field.normalized_value,
                email=email.field.normalized_value,
                address=address.field.normalized_value,
            ),
            job_intention=job_intention,
            background=BackgroundInfo(
                years_of_experience=years,
                education=education,
                projects=projects,
                skills=skills,
                work_experience=work_experience[:10],
                research_experience=research_experience[:10],
                honors=honors,
                certificates=certificates,
                self_evaluation=self_evaluation,
            ),
            summary=self._build_summary(text, sections),
            sections=sections,
            field_details=field_details,
            extraction_warnings=warnings,
        )

    def _ai_extract_by_sections(self, sections: dict[str, ResumeSection]) -> dict[str, Any]:
        if not self.llm.enabled:
            return {}

        section_payload = {
            name: truncate_text(section.text, 2200)
            for name, section in sections.items()
            if name
            in {
                "basic_info",
                "job_intention",
                "education",
                "work",
                "internship",
                "project",
                "research",
                "skills",
                "honors",
                "certificates",
                "self_evaluation",
            }
            and section.text
        }
        if not section_payload:
            return {}

        system_prompt = (
            "你是招聘系统中的简历信息抽取助手。"
            "输入已经按章节切分，请优先在对应章节内抽取，不要编造。"
            "只返回合法 JSON，不要输出 Markdown。"
        )
        user_prompt = f"""
请基于下面的分章节简历文本抽取结构化信息。手机号、邮箱、学历、技能等确定性字段若已明显存在，请保持原文；缺失字段返回空字符串或空数组。

返回 JSON 结构：
{{
  "basic_info": {{"name": "", "phone": "", "email": "", "address": ""}},
  "job_intention": {{"position": "", "expected_salary": ""}},
  "background": {{
    "years_of_experience": "",
    "education": [{{"school": "", "degree": "", "major": "", "period": ""}}],
    "projects": [{{"name": "", "role": "", "description": "", "technologies": [], "highlights": []}}],
    "skills": [],
    "work_experience": [],
    "research_experience": [],
    "honors": [],
    "certificates": [],
    "self_evaluation": ""
  }},
  "summary": ""
}}

分章节文本：
{section_payload}
"""
        return self.llm.chat_json(system_prompt, user_prompt)

    def _merge_ai_result(self, rule_result: ResumeExtraction, ai_result: dict[str, Any]) -> ResumeExtraction:
        if not ai_result:
            return rule_result

        merged = rule_result.model_dump()
        protected_fields = {
            "basic_info": {"phone", "email"},
            "background": {"skills"},
        }

        for section_name, section_value in ai_result.items():
            if section_name not in merged or not isinstance(section_value, dict):
                if section_name == "summary" and section_value:
                    merged["summary"] = section_value
                continue
            for key, value in section_value.items():
                if value in ("", None, [], {}):
                    continue
                if key in protected_fields.get(section_name, set()) and merged[section_name].get(key):
                    continue
                if isinstance(value, list) and isinstance(merged[section_name].get(key), list):
                    merged[section_name][key] = value or merged[section_name][key]
                else:
                    merged[section_name][key] = value

        details = merged.setdefault("field_details", {})
        for path in ["basic_info.name", "job_intention.position", "job_intention.expected_salary"]:
            current = self._get_nested(merged, path)
            if current and (path not in details or not details[path].get("normalized_value")):
                details[path] = self._field_from_value(str(current), "ai_section_model", 0.68, str(current)).model_dump()

        try:
            return ResumeExtraction.model_validate(merged)
        except Exception:
            return rule_result

    @staticmethod
    def _match_section_title(line: str) -> str:
        if re.search(r"https?://|www\.|github\.com|gitee\.com", line, re.I):
            return ""
        normalized = re.sub(r"[/\\|:_：\-\s]+", "", line).lower()
        if len(normalized) > 40:
            return ""
        for name, aliases in SECTION_ALIASES.items():
            for alias in aliases:
                alias_key = re.sub(r"[/\\|:_：\-\s]+", "", alias).lower()
                if alias_key and alias_key in normalized:
                    return name
        return ""

    def _name_candidates(self, text: str, sections: dict[str, ResumeSection]) -> list[FieldCandidate]:
        candidates: list[FieldCandidate] = []
        search_text = "\n".join(
            [
                sections.get("basic_info", ResumeSection(name="basic_info")).text,
                "\n".join(text.splitlines()[:12]),
            ]
        )
        label_match = re.search(
            r"(?:姓名|Name)[:： ]*([\u4e00-\u9fa5A-Za-z· ]{2,8})(?=\s*(?:籍贯|生日|邮箱|电话|手机|QQ|$))",
            search_text,
            re.I,
        )
        if label_match:
            candidates.append(FieldCandidate(label_match.group(1).strip(), "label_rule", 0.88, label_match.group(0)))

        for line in text.splitlines()[:10]:
            stripped = line.strip()
            if any(token in stripped for token in ["电话", "邮箱", "@", "简历", "求职", "籍贯"]):
                continue
            if 2 <= len(stripped) <= 8 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z· ]+", stripped):
                candidates.append(FieldCandidate(stripped, "top_line_rule", 0.62, stripped))
                break
        return candidates

    def _phone_candidates(self, text: str, sections: dict[str, ResumeSection]) -> list[FieldCandidate]:
        candidates: list[FieldCandidate] = []
        for source, source_text, confidence in self._candidate_sources(text, sections):
            for match in PHONE_RE.finditer(source_text):
                normalized = self._normalize_phone(match.group(0))
                if self._valid_phone(normalized):
                    candidates.append(FieldCandidate(normalized, source, confidence, match.group(0), normalized=True))
        return candidates

    def _email_candidates(self, text: str, sections: dict[str, ResumeSection]) -> list[FieldCandidate]:
        candidates: list[FieldCandidate] = []
        for source, source_text, confidence in self._candidate_sources(text, sections):
            for match in EMAIL_RE.finditer(source_text):
                normalized = re.sub(r"\s+", "", match.group(0))
                if self._valid_email(normalized):
                    candidates.append(FieldCandidate(normalized, source, confidence, match.group(0), normalized=True))
        return candidates

    def _address_candidates(self, text: str, sections: dict[str, ResumeSection]) -> list[FieldCandidate]:
        candidates = []
        search_text = "\n".join([sections.get("basic_info", ResumeSection(name="basic_info")).text, text[:600]])
        for match in re.finditer(r"(?:现居|地址|所在地|居住地|籍贯)[:： ]*([^\n]{2,40})", search_text):
            value = re.split(r"(?:生日|邮箱|电话|手机|QQ)", match.group(1))[0].strip()
            candidates.append(FieldCandidate(value, "label_rule", 0.78, match.group(0), normalized=True))
        return candidates

    @staticmethod
    def _candidate_sources(text: str, sections: dict[str, ResumeSection]) -> list[tuple[str, str, float]]:
        basic = sections.get("basic_info", ResumeSection(name="basic_info")).text
        top = "\n".join(text.splitlines()[:18])
        return [
            ("basic_info_section", basic, 0.9),
            ("first_page_top_text", top, 0.82),
            ("full_text_rule", text, 0.74),
        ]

    def _select_field(
        self,
        source_key: str,
        candidates: list[FieldCandidate],
        required: bool,
        warnings: list[str],
    ) -> Any:
        unique = self._unique_candidates(candidates)
        if not unique:
            if required:
                warnings.append(f"{source_key} 未提供或未识别")
            field = ExtractedField(status="MISSING")
        else:
            sorted_candidates = sorted(unique, key=lambda item: item.confidence, reverse=True)
            best = sorted_candidates[0]
            conflict = len({item.value for item in sorted_candidates}) > 1
            status = self._status(best.confidence, conflict)
            field = ExtractedField(
                raw_value=best.evidence,
                normalized_value=best.value,
                source=best.source,
                confidence=round(best.confidence if not conflict else best.confidence - 0.15, 2),
                status=status,
                evidence=best.evidence,
                normalized=best.normalized,
                candidates=[item.value for item in sorted_candidates],
            )
        return SelectedField(source_key=source_key, field=field)

    @staticmethod
    def _unique_candidates(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
        seen: dict[str, FieldCandidate] = {}
        for candidate in candidates:
            key = candidate.value.casefold()
            if not key:
                continue
            if key not in seen or candidate.confidence > seen[key].confidence:
                seen[key] = candidate
        return list(seen.values())

    @staticmethod
    def _status(confidence: float, conflict: bool = False) -> str:
        if conflict:
            return "CONFLICT"
        if confidence >= 0.9:
            return "CONFIRMED"
        if confidence >= 0.75:
            return "HIGH_CONFIDENCE"
        if confidence >= 0.55:
            return "MEDIUM_CONFIDENCE"
        if confidence > 0:
            return "LOW_CONFIDENCE"
        return "MISSING"

    @staticmethod
    def _field_from_value(
        value: str,
        source: str,
        confidence: float,
        evidence: str,
        normalized: bool = False,
    ) -> ExtractedField:
        return ExtractedField(
            raw_value=evidence,
            normalized_value=value,
            source=source if value else "",
            confidence=round(confidence, 2) if value else 0,
            status=ResumeExtractionService._status(confidence) if value else "MISSING",
            evidence=evidence,
            normalized=normalized,
            candidates=[value] if value else [],
        )

    def _extract_education(self, sections: dict[str, ResumeSection]) -> list[EducationItem]:
        text = sections.get("education", ResumeSection(name="education")).text
        if not text:
            return []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        period = self._period_match(text)
        compact_line = next((line for line in lines if any(hint in line for hint in SCHOOL_HINTS)), "")
        school, major, degree = self._parse_education_line(compact_line)
        school = school or self._first_line_with(lines, SCHOOL_HINTS)
        degree = degree or self._first_match(r"(博士|硕士|研究生|本科|学士|大专|专科)", text)
        major = major or self._guess_major(lines, school, degree)
        return [EducationItem(school=school, degree=degree, major=major, period=period)]

    def _extract_projects(self, sections: dict[str, ResumeSection]) -> list[ProjectItem]:
        text = sections.get("project", ResumeSection(name="project")).text
        if not text:
            return []
        lines = [line.strip(" ·•-") for line in text.splitlines() if line.strip()]
        projects: list[ProjectItem] = []
        current_name = ""
        current_lines: list[str] = []

        def flush() -> None:
            nonlocal current_name, current_lines
            if not current_name and not current_lines:
                return
            description = clean_text("\n".join(current_lines))
            techs = self._extract_skills(description)
            projects.append(
                ProjectItem(
                    name=current_name,
                    role=self._first_match(r"(?:角色|职责)[:： ]*([^\n]{2,30})", description),
                    description=description,
                    technologies=techs,
                    highlights=self._extract_highlights(description),
                )
            )
            current_name = ""
            current_lines = []

        index = 0
        while index < len(lines):
            line = lines[index]
            if SINGLE_DATE_RE.search(line):
                flush()
                name_part = self._project_title_from_line(line)
                if not name_part and index + 1 < len(lines):
                    index += 1
                    name_part = lines[index]
                current_name = name_part[:60]
            else:
                current_lines.append(line)
            index += 1
        flush()
        return projects[:8]

    def _extract_job_intention(self, sections: dict[str, ResumeSection]) -> JobIntention:
        text = sections.get("job_intention", ResumeSection(name="job_intention")).text
        if not text:
            return JobIntention()
        position = self._first_match(r"(?:求职意向|目标岗位|应聘岗位)[:： ]*([^\n]{2,40})", text)
        salary = self._first_match(r"(?:期望薪资|薪资)[:： ]*([^\n]{2,30})", text)
        return JobIntention(position=position, expected_salary=salary)

    def _extract_years_of_experience(self, text: str) -> str:
        return self._first_match(r"(\d+\s*年(?:以上)?(?:工作|开发|项目)?经验)", text)

    @staticmethod
    def _extract_skills(text: str) -> list[str]:
        matched = [skill for skill in COMMON_SKILLS if re.search(re.escape(skill), text, re.I)]
        for raw_value, normalized_value in SKILL_ALIASES.items():
            if re.search(re.escape(raw_value), text, re.I):
                matched.append(normalized_value)
        return unique_keep_order(matched)

    @staticmethod
    def _extract_highlights(text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return [line for line in lines if any(token in line for token in ["提升", "降低", "优化", "负责", "实现", "%", "万"])][:5]

    @staticmethod
    def _project_title_from_line(line: str) -> str:
        title = PERIOD_RE.sub("", line)
        title = SINGLE_DATE_RE.sub("", title)
        return title.strip(" -:：·•")

    @staticmethod
    def _section_lines(sections: dict[str, ResumeSection], name: str) -> list[str]:
        text = sections.get(name, ResumeSection(name=name)).text
        return [line.strip() for line in text.splitlines() if line.strip()]

    @staticmethod
    def _first_match(pattern: str | re.Pattern[str], text: str) -> str:
        match = re.search(pattern, text, re.I) if isinstance(pattern, str) else pattern.search(text)
        if not match:
            return ""
        return match.group(1).strip() if match.lastindex else match.group(0).strip()

    @staticmethod
    def _period_match(text: str) -> str:
        match = PERIOD_RE.search(text)
        return match.group(0).strip() if match else ""

    @staticmethod
    def _first_line_with(lines: list[str], hints: list[str]) -> str:
        for line in lines:
            if any(hint.lower() in line.lower() for hint in hints):
                return line
        return ""

    @staticmethod
    def _guess_major(lines: list[str], school: str, degree: str) -> str:
        for line in lines:
            if line == school or line == degree:
                continue
            if any(token in line for token in ["专业", "科学", "工程", "技术", "管理", "设计"]):
                return line
        return ""

    @staticmethod
    def _parse_education_line(line: str) -> tuple[str, str, str]:
        line = PERIOD_RE.sub("", line).strip(" -")
        match = re.search(
            r"(?P<school>.*?(?:大学|学院|学校|研究院|University|College))(?P<middle>.*?)(?P<degree>博士|硕士|研究生|本科|学士|大专|专科)",
            line,
            re.I,
        )
        if not match:
            return "", "", ""
        school = match.group("school").strip()
        degree = match.group("degree").strip()
        major = re.sub(r"全日制|非全日制|统招|普通", "", match.group("middle")).strip()
        return school, major, degree

    @staticmethod
    def _normalize_phone(value: str) -> str:
        normalized = re.sub(r"[ -]", "", value)
        if normalized.startswith("+86"):
            normalized = normalized[3:]
        if normalized.startswith("86") and len(normalized) == 13:
            normalized = normalized[2:]
        return normalized

    @staticmethod
    def _valid_phone(value: str) -> bool:
        return bool(re.fullmatch(r"1[3-9]\d{9}", value))

    @staticmethod
    def _valid_email(value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value))

    @staticmethod
    def _build_summary(text: str, sections: dict[str, ResumeSection]) -> str:
        preferred = []
        for name in ["education", "work", "internship", "project", "skills", "self_evaluation"]:
            section = sections.get(name)
            if section and section.text:
                preferred.append(section.text)
        return truncate_text(clean_text("\n".join(preferred) or text), 500)

    @staticmethod
    def _get_nested(payload: dict[str, Any], path: str) -> Any:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
