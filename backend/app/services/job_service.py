from __future__ import annotations

import re
from typing import Any

from app.models.schemas import AtomicRequirement, JobRequirement
from app.services.extraction_service import COMMON_SKILLS
from app.services.llm_service import LLMService
from app.utils.skill_match import contains_any, contains_term, matched_terms
from app.utils.text import truncate_text, unique_keep_order


class JobRequirementService:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def analyze(self, job_description: str) -> JobRequirement:
        fallback = self._rule_based_analyze(job_description)
        ai_result = self._ai_analyze(job_description)
        if not ai_result:
            return self._structure_atomic_requirements(job_description, fallback)

        merged = self._merge(fallback.model_dump(), ai_result)
        try:
            return self._structure_atomic_requirements(job_description, JobRequirement.model_validate(merged))
        except Exception:
            return self._structure_atomic_requirements(job_description, fallback)

    def _structure_atomic_requirements(self, job_description: str, job: JobRequirement) -> JobRequirement:
        if not job.atomic_requirements:
            return job
        structured = self._ai_structure_requirements(job_description, job.atomic_requirements)
        requirements = structured or [_fallback_structure_requirement(item) for item in job.atomic_requirements]
        total_weight = sum(max(item.weight, 0) for item in requirements) or 1
        for item in requirements:
            item.weight = round(max(item.weight, 0) / total_weight * 100, 2)
        job.atomic_requirements = requirements
        return job

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
  "responsibilities": [],
  "atomic_requirements": [
    {{
      "id": "R1",
      "text": "",
      "requirement_type": "core",
      "capability_category": "开放能力类别，使用英文 snake_case，不受固定枚举限制",
      "capability_name": "",
      "examples": [],
      "required_concepts": [],
      "acceptable_evidence": [],
      "evidence_logic": "DIRECT_ONLY|PARTIAL_OK|INFER_ALLOWED",
      "logic": "OR",
      "min_count": 1,
      "proficiency": "熟悉",
      "is_hard": false,
      "is_open_ended": true,
      "weight": 10
    }}
  ]
}}

岗位描述：
{truncate_text(job_description, 6000)}
"""
        return self.llm.chat_json(system_prompt, user_prompt)

    def _ai_structure_requirements(
        self,
        job_description: str,
        requirements: list[AtomicRequirement],
    ) -> list[AtomicRequirement]:
        if not self.llm.enabled:
            return []

        system_prompt = (
            "你是招聘 JD 结构化助手。用户输入已经被规则拆成原子要求。"
            "你只负责把每条要求转成开放式能力结构，不要合并、删除或改写 id。"
            "不要使用固定枚举限制 capability_category，可按语义生成英文 snake_case。"
            "只返回合法 JSON。"
        )
        user_prompt = f"""
请结构化下面的岗位原子要求。重点输出 required_concepts 和 acceptable_evidence。

规则：
1. required_concepts 写岗位真正要求候选人具备的概念/能力点。
2. acceptable_evidence 写简历中可证明该能力的证据类型，可以包含可间接推断的项目行为。
3. evidence_logic 可选：
   - DIRECT_ONLY：学历、证书、到岗时间、实习时长等确定性条件，只允许直接证据。
   - PARTIAL_OK：部分证据可部分匹配。
   - INFER_ALLOWED：允许从项目技术栈、职责、产出中谨慎推断。
4. is_hard 只用于学历、证书、地域/到岗等真正会一票否决的硬性条件；实习时长若简历未写，应视为待确认，不要默认不满足。
5. 不要编造原 JD 没有的要求。

返回 JSON：
{{
  "atomic_requirements": [
    {{
      "id": "R1",
      "text": "保持原文",
      "requirement_type": "hard|core|business|soft",
      "capability_category": "open_snake_case",
      "capability_name": "中文能力名",
      "examples": [],
      "required_concepts": [],
      "acceptable_evidence": [],
      "evidence_logic": "DIRECT_ONLY|PARTIAL_OK|INFER_ALLOWED",
      "logic": "OR|AND",
      "min_count": 1,
      "proficiency": "了解|熟悉|熟练|精通",
      "is_hard": false,
      "is_open_ended": true,
      "weight": 10
    }}
  ]
}}

完整 JD：
{truncate_text(job_description, 4000)}

规则拆分结果：
{[item.model_dump() for item in requirements]}
"""
        payload = self.llm.chat_json(system_prompt, user_prompt)
        raw_items = payload.get("atomic_requirements", [])
        if not isinstance(raw_items, list) or len(raw_items) < max(1, len(requirements) // 2):
            return []

        fallback_by_id = {item.id: item for item in requirements}
        structured: list[AtomicRequirement] = []
        seen: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            req_id = str(raw.get("id", ""))
            fallback = fallback_by_id.get(req_id)
            if not fallback or req_id in seen:
                continue
            merged = fallback.model_dump()
            for key, value in raw.items():
                if value not in ("", None, [], {}):
                    merged[key] = value
            try:
                structured.append(_normalize_structured_requirement(AtomicRequirement.model_validate(merged)))
                seen.add(req_id)
            except Exception:
                structured.append(_fallback_structure_requirement(fallback))
                seen.add(req_id)

        for item in requirements:
            if item.id not in seen:
                structured.append(_fallback_structure_requirement(item))
        return structured

    @staticmethod
    def _rule_based_analyze(job_description: str) -> JobRequirement:
        atomic_requirements = _build_atomic_requirements(job_description)
        required_skills = unique_keep_order(
            skill for skill in COMMON_SKILLS if contains_term(job_description, skill)
        )
        keywords = unique_keep_order(required_skills + _extract_chinese_keywords(job_description))
        return JobRequirement(
            required_skills=required_skills,
            preferred_skills=[],
            experience_requirements=_first_requirement(job_description, "经验"),
            education_requirements=_first_requirement(job_description, "本科|硕士|博士|大专|学历"),
            job_keywords=keywords[:20],
            responsibilities=_split_sentences(job_description)[:6],
            raw_description=job_description,
            atomic_requirements=atomic_requirements,
        )

    @staticmethod
    def _merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        for key, value in incoming.items():
            if value not in ("", None, [], {}):
                if key == "atomic_requirements":
                    continue
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


def _build_atomic_requirements(text: str) -> list[AtomicRequirement]:
    clauses = _split_requirement_items(text)
    requirements = [_classify_requirement(index + 1, clause) for index, clause in enumerate(clauses)]
    total_weight = sum(item.weight for item in requirements) or 1
    for item in requirements:
        item.weight = round(item.weight / total_weight * 100, 2)
    return requirements


def _fallback_structure_requirement(requirement: AtomicRequirement) -> AtomicRequirement:
    concepts = unique_keep_order(requirement.required_concepts or requirement.examples or _extract_chinese_keywords(requirement.text))
    evidence_map = {
        "education": ["教育经历中出现对应学历、专业或在读状态"],
        "internship_availability": ["简历或补充信息中明确每周可实习天数、可持续月份、到岗时间"],
        "confirmation_required": ["简历或补充信息中明确地点、到岗、薪资、时间安排等约束条件"],
        "backend_language": ["技能栏出现后端语言", "项目技术栈或职责中使用后端语言开发接口、服务或业务模块"],
        "data_storage": ["项目中出现数据库、缓存、表结构、字段、落库、查询、索引等证据"],
        "cs_fundamentals": ["项目中出现接口开发、请求处理、数据库落库、前后端交互、WebSocket 等可推断基础原理的证据"],
        "crud_project": ["项目中出现完整业务功能、增删改查、登录鉴权、发布评论、前后端协作等证据"],
        "sql_crud": ["项目中出现 SQL 数据库、表名字段、查询、落库、增删改查、联表或 ORM 使用证据"],
        "frontend_basic": ["项目或技能中出现 HTML、CSS、JavaScript、React、Vue、页面渲染或前端交互证据"],
        "git_workflow": ["技能或项目中明确 Git、branch、commit、PR、版本管理流程证据"],
        "ai_collaboration": ["简历中出现 Cursor、Claude Code、ChatGPT 等 AI 工具使用，或对 AI 生成代码进行审查的证据"],
    }
    direct_only = requirement.is_hard or requirement.capability_category in {"education", "internship_availability", "confirmation_required"}
    requirement.required_concepts = concepts
    requirement.acceptable_evidence = unique_keep_order(
        requirement.acceptable_evidence
        or evidence_map.get(requirement.capability_category, [f"简历中体现 {requirement.text} 的直接或项目证据"])
    )
    requirement.evidence_logic = "DIRECT_ONLY" if direct_only else ("INFER_ALLOWED" if requirement.capability_category in {"cs_fundamentals", "crud_project", "sql_crud", "frontend_basic"} else "PARTIAL_OK")
    requirement.capability_name = requirement.capability_name or requirement.text[:24]
    return _normalize_structured_requirement(requirement)


def _normalize_structured_requirement(requirement: AtomicRequirement) -> AtomicRequirement:
    text = requirement.text
    if requirement.capability_category == "education" or any(token in text for token in ["本科", "硕士", "博士", "学历", "研究生"]):
        requirement.capability_category = "education"
        requirement.requirement_type = "hard"
        requirement.is_hard = True
        requirement.evidence_logic = "DIRECT_ONLY"

    if _is_confirmation_requirement(text, requirement.capability_category):
        if requirement.capability_category != "internship_availability":
            requirement.capability_category = "confirmation_required"
        requirement.requirement_type = "constraint"
        requirement.is_hard = False
        requirement.evidence_logic = "DIRECT_ONLY"

    if not requirement.is_hard and requirement.capability_category in {"cs_fundamentals", "crud_project", "sql_crud", "frontend_basic"}:
        requirement.evidence_logic = "INFER_ALLOWED"
    return requirement


def _split_requirement_items(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    line_items: list[str] = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^(?:[-*•·]\s*|\d+[、.．)]\s*|[一二三四五六七八九十]+[、.．)]\s*)", "", stripped)
        stripped = stripped.strip(" \n\t;；。")
        if stripped:
            line_items.append(stripped)
    if len(line_items) > 1:
        return line_items

    parts = re.split(r"(?:^|[\n;；。]\s*|\s+)(?:\d+[、.．)]|[一二三四五六七八九十]+[、.．])\s*", normalized)
    items = [part.strip(" \n\t;；。") for part in parts if part.strip(" \n\t;；。")]
    if len(items) > 1:
        return items

    sentence_parts = re.split(r"[。；;]\s*|\n+", normalized)
    sentence_items = [part.strip(" \n\t-•*;；。") for part in sentence_parts if 6 <= len(part.strip()) <= 160]
    return sentence_items or _split_sentences(text)


def _valid_atomic_requirements(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    valid_categories = {
        "education",
        "backend_language",
        "data_storage",
        "analytics_reporting",
        "web_cache_mq",
        "ai_collaboration",
        "product_creativity",
        "cs_fundamentals",
        "crud_project",
        "sql_crud",
        "frontend_basic",
        "git_workflow",
        "internship_availability",
        "confirmation_required",
        "general",
    }
    structured_count = 0
    for item in value:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        if item.get("capability_category") in valid_categories:
            structured_count += 1
    return structured_count >= max(1, len(value) // 2)


def _classify_requirement(index: int, text: str) -> AtomicRequirement:
    requirement = AtomicRequirement(id=f"R{index}", text=text)

    if any(token in text for token in ["本科", "硕士", "博士", "学历", "研究生", "专业在读", "计算机相关专业"]):
        requirement.requirement_type = "hard"
        requirement.capability_category = "education"
        requirement.examples = [token for token in ["本科", "硕士", "博士", "研究生", "计算机相关专业", "计算机"] if token in text]
        requirement.is_hard = True
        requirement.is_open_ended = False
        requirement.weight = 12
        return requirement

    if contains_any(text, ["HTTP", "请求响应", "数据库读写", "前端渲染", "计算机基础", "基本原理"]):
        requirement.requirement_type = "core"
        requirement.capability_category = "cs_fundamentals"
        requirement.examples = _examples_from_text(text, ["HTTP", "请求响应", "数据库读写", "前端渲染", "计算机基础", "基本原理"])
        requirement.logic = "AND" if "、" in text else "OR"
        requirement.min_count = 2 if "、" in text else 1
        requirement.weight = 12
        return requirement

    if contains_any(text, ["CRUD", "side project", "课程项目", "项目可以展示"]) or ("前后端" in text and "项目" in text):
        requirement.requirement_type = "core"
        requirement.capability_category = "crud_project"
        requirement.examples = _examples_from_text(text, ["CRUD", "side project", "课程项目", "前后端"])
        requirement.logic = "AND" if "CRUD" in text and "项目" in text else "OR"
        requirement.min_count = 2 if requirement.logic == "AND" else 1
        requirement.weight = 12
        return requirement

    if contains_any(text, ["Node.js", "Nodejs", "Go", "Python"]) and any(token in text for token in ["后端", "语言", "REST", "API", "至少"]):
        requirement.requirement_type = "core"
        requirement.capability_category = "backend_language"
        requirement.examples = _examples_from_text(text, ["Node.js", "Nodejs", "Go", "Python", "REST API", "RESTAPI"])
        requirement.logic = "OR"
        requirement.min_count = 1
        requirement.is_open_ended = "等" in text or "至少" in text or "均可" in text
        requirement.weight = 18
        return requirement

    if contains_any(text, ["SQL", "增删改查", "联表"]):
        requirement.requirement_type = "core"
        requirement.capability_category = "sql_crud"
        requirement.examples = _examples_from_text(text, ["SQL", "MySQL", "PostgreSQL", "增删改查", "CRUD", "联表"])
        requirement.logic = "AND" if "联表" in text or "增删改查" in text else "OR"
        requirement.min_count = 2 if requirement.logic == "AND" else 1
        requirement.weight = 12
        return requirement

    if contains_any(text, ["HTML", "CSS", "JavaScript", "React", "Vue"]) or "前端基础" in text:
        requirement.requirement_type = "core"
        requirement.capability_category = "frontend_basic"
        requirement.examples = _examples_from_text(text, ["HTML", "CSS", "JavaScript", "React", "Vue"])
        requirement.logic = "AND" if all(token in text for token in ["HTML", "CSS", "JavaScript"]) else "OR"
        requirement.min_count = 3 if requirement.logic == "AND" else 1
        requirement.weight = 12
        return requirement

    if contains_any(text, ["Git", "branch", "commit", "PR"]) or "版本管理" in text:
        requirement.requirement_type = "core"
        requirement.capability_category = "git_workflow"
        requirement.examples = _examples_from_text(text, ["Git", "branch", "commit", "PR", "版本管理"])
        requirement.logic = "AND" if contains_any(text, ["branch", "commit", "PR"]) else "OR"
        requirement.min_count = 2 if requirement.logic == "AND" else 1
        requirement.weight = 8
        return requirement

    if any(token in text for token in ["每周", "个月", "到岗", "天实习", "可实习", "持续"]):
        requirement.requirement_type = "constraint"
        requirement.capability_category = "internship_availability"
        requirement.examples = _examples_from_text(text, ["每周", "4天", "3个月", "实习"])
        requirement.is_hard = False
        requirement.is_open_ended = False
        requirement.evidence_logic = "DIRECT_ONLY"
        requirement.weight = 6
        return requirement

    if _is_confirmation_requirement(text):
        requirement.requirement_type = "constraint"
        requirement.capability_category = "confirmation_required"
        requirement.examples = _examples_from_text(text, ["到岗", "入职", "现场", "远程", "base", "地点", "薪资", "毕业", "全职", "转正"])
        requirement.is_hard = False
        requirement.is_open_ended = False
        requirement.evidence_logic = "DIRECT_ONLY"
        requirement.weight = 6
        return requirement

    if contains_any(text, ["MySQL", "Redis", "MongoDB", "PostgreSQL", "Elasticsearch"]) or any(token in text for token in ["存储", "数据库"]):
        requirement.requirement_type = "core"
        requirement.capability_category = "data_storage"
        requirement.examples = _examples_from_text(text, ["MySQL", "Redis", "MongoDB", "PostgreSQL", "Elasticsearch"])
        requirement.logic = "OR" if any(token in text for token in ["等", "或", "至少"]) else "AND"
        requirement.min_count = 1
        requirement.weight = 14
        return requirement

    if any(token in text for token in ["统计分析", "指标体系", "数据报表", "报表", "指标"]):
        requirement.requirement_type = "business"
        requirement.capability_category = "analytics_reporting"
        requirement.examples = _examples_from_text(text, ["统计分析", "指标体系", "数据报表"])
        requirement.weight = 15
        return requirement

    if any(token in text for token in ["Web", "缓存", "消息队列", "基础组件"]):
        requirement.requirement_type = "core"
        requirement.capability_category = "web_cache_mq"
        requirement.examples = _examples_from_text(text, ["Web", "缓存", "消息队列", "Redis", "Kafka", "RabbitMQ", "RocketMQ"])
        requirement.logic = "OR" if "等" in text else "AND"
        requirement.min_count = 2 if "、" in text and "等" not in text else 1
        requirement.weight = 20
        return requirement

    if contains_any(text, ["Cursor", "Claude", "Claude Code", "ChatGPT"]) or "AI" in text:
        requirement.requirement_type = "core"
        requirement.capability_category = "ai_collaboration"
        requirement.examples = _examples_from_text(text, ["Cursor", "Claude Code", "Claude", "ChatGPT", "AI 工具", "AI协同开发", "判断AI生成代码"])
        requirement.weight = 15
        return requirement

    if any(token in text for token in ["产品意识", "创造力", "创新"]):
        requirement.requirement_type = "soft"
        requirement.capability_category = "product_creativity"
        requirement.examples = _examples_from_text(text, ["产品意识", "创造力"])
        requirement.weight = 10
        return requirement

    requirement.requirement_type = "core"
    requirement.capability_category = "general"
    requirement.examples = _extract_chinese_keywords(text)
    requirement.weight = 10
    return requirement


def _examples_from_text(text: str, candidates: list[str]) -> list[str]:
    return unique_keep_order(matched_terms(text, candidates))


def _is_confirmation_requirement(text: str, category: str = "") -> bool:
    if category in {"internship_availability", "confirmation_required"}:
        return True
    confirmation_terms = [
        "每周",
        "天实习",
        "个月以上",
        "持续",
        "到岗",
        "入职",
        "base",
        "工作地点",
        "现场",
        "远程",
        "薪资",
        "转正",
        "毕业时间",
        "全职",
        "可实习",
    ]
    return any(term in text for term in confirmation_terms)


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
    return [keyword for keyword in candidates if contains_term(text, keyword)]


def _first_requirement(text: str, keyword_pattern: str) -> str:
    for sentence in _split_sentences(text):
        if any(token in sentence for token in keyword_pattern.split("|")):
            return sentence
    return ""
