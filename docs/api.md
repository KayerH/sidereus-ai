# API 文档

后端默认地址：

```text
http://localhost:8000
```

所有业务接口统一挂载在 `/api` 前缀下。

## 通用说明

### 响应格式

后端主要返回 JSON。上传文件相关接口使用 `multipart/form-data`。

### 错误响应

常见错误响应：

```json
{
  "detail": "错误原因"
}
```

### 缓存说明

系统使用 Redis 缓存：

- 简历解析缓存：按文件 hash 缓存。
- 匹配结果缓存：按文件 hash、JD hash、权重 hash 缓存。
- Redis 不可用时，自动降级为内存缓存。

## 健康检查

```http
GET /api/health
```

响应示例：

```json
{
  "status": "ok",
  "cache": "redis",
  "llm": "enabled"
}
```

字段说明：

- `status`：后端服务状态。
- `cache`：当前缓存后端，可能为 `redis` 或 `memory-fallback`。
- `llm`：大模型是否可用。

## 默认评分权重

```http
GET /api/scoring/default-weights
```

响应示例：

```json
{
  "skill_match": 40,
  "experience_relevance": 25,
  "project_relevance": 20,
  "education_fit": 10,
  "keyword_coverage": 5
}
```

字段说明：

- `skill_match`：技能和能力类要求匹配权重。
- `experience_relevance`：经历、职责、实习和需确认条件权重。
- `project_relevance`：项目经验、项目深度和推断能力权重。
- `education_fit`：学历、专业和学校背景权重。
- `keyword_coverage`：要求覆盖度权重。

前端要求权重总和必须为 100 才能开始分析；后端仍会对传入权重做归一化保护。

## 上传并解析简历

```http
POST /api/resumes/upload
Content-Type: multipart/form-data
```

表单字段：

- `file`：PDF 简历文件。

响应示例：

```json
{
  "basic_info": {
    "name": "张三",
    "phone": "13800138000",
    "email": "zhangsan@example.com",
    "age": "23",
    "address": "北京"
  },
  "job_intention": {
    "position": "后端开发实习生",
    "expected_salary": ""
  },
  "background": {
    "years_of_experience": "",
    "education": [
      {
        "school": "某某大学",
        "degree": "本科",
        "major": "计算机科学与技术",
        "period": "2022.09-2026.06"
      }
    ],
    "projects": [
      {
        "name": "课程管理系统",
        "role": "后端开发",
        "description": "负责 REST API、数据库表设计和增删改查接口开发。",
        "technologies": ["Python", "FastAPI", "MySQL"],
        "highlights": ["实现用户、课程、选课等 CRUD 功能"]
      }
    ],
    "skills": ["Python", "FastAPI", "MySQL", "React", "Git"],
    "work_experience": [],
    "research_experience": [],
    "honors": [],
    "certificates": [],
    "self_evaluation": ""
  },
  "summary": "计算机相关专业，有 Web 项目经验。",
  "sections": {
    "education": {
      "name": "education",
      "title": "教育背景",
      "text": "某某大学 计算机科学与技术 本科 2022.09-2026.06",
      "start_line": 3,
      "end_line": 5
    }
  },
  "field_details": {
    "basic_info.phone": {
      "raw_value": "13800138000",
      "normalized_value": "13800138000",
      "source": "phone_regex",
      "confidence": 0.95,
      "status": "EXTRACTED",
      "page_number": null,
      "bbox": null,
      "evidence": "手机：13800138000",
      "normalized": true,
      "candidates": ["13800138000"]
    }
  },
  "extraction_warnings": []
}
```

说明：

- `basic_info.age` 只提取简历中明确出现的年龄或出生日期，不根据教育时间推断。
- `sections` 用于保留分章节文本，便于排查信息提取来源。
- `field_details` 用于保留字段证据、来源、置信度和候选值。

## 分析岗位 JD

```http
POST /api/jobs/analyze
Content-Type: multipart/form-data
```

表单字段：

- `job_description`：岗位描述文本。

JD 输入支持：

- 每行一条要求。
- `-`、`*`、`•` 等列表符号。
- `1.`、`1、`、`（1）` 等序号。
- 没有显式符号的自然段。

响应示例：

```json
{
  "required_skills": ["Python", "SQL", "React", "Git"],
  "preferred_skills": ["AI 工具"],
  "experience_requirements": "有完整课程项目或 side project",
  "education_requirements": "计算机相关专业在读，本科或研究生",
  "job_keywords": ["HTTP", "数据库读写", "REST API", "SQL", "React", "Git"],
  "responsibilities": [],
  "raw_description": "- 计算机相关专业在读\n- 熟悉后端语言，能写 REST API",
  "atomic_requirements": [
    {
      "id": "req_1",
      "text": "计算机相关专业在读，本科或研究生",
      "requirement_type": "core",
      "capability_category": "education",
      "capability_name": "计算机相关专业在读",
      "examples": [],
      "required_concepts": ["计算机相关专业", "本科或研究生", "在读"],
      "acceptable_evidence": ["教育背景中出现计算机相关专业", "学历为本科或研究生"],
      "evidence_logic": "DIRECT_ONLY",
      "logic": "AND",
      "min_count": 1,
      "proficiency": "熟悉",
      "is_hard": true,
      "is_open_ended": false,
      "weight": 10
    },
    {
      "id": "req_2",
      "text": "熟悉前端基础，了解 React 或 Vue 其中之一",
      "requirement_type": "core",
      "capability_category": "frontend_basic",
      "capability_name": "前端基础与框架",
      "examples": ["HTML", "CSS", "JavaScript", "React", "Vue"],
      "required_concepts": ["前端基础", "React 或 Vue"],
      "acceptable_evidence": ["技能栏出现 HTML/CSS/JavaScript/React/Vue", "项目中承担前端页面开发或前端渲染相关工作"],
      "evidence_logic": "INFER_ALLOWED",
      "logic": "OR",
      "min_count": 1,
      "proficiency": "了解",
      "is_hard": false,
      "is_open_ended": true,
      "weight": 10
    }
  ]
}
```

字段说明：

- `atomic_requirements`：拆分后的 JD 原子要求列表。
- `required_concepts`：该要求必须覆盖的核心概念。
- `acceptable_evidence`：可接受的简历证据类型。
- `evidence_logic`：
  - `DIRECT_ONLY`：只接受明确直接证据，不做能力推断。
  - `INFER_ALLOWED`：允许从项目、技术栈、职责中推断。
  - `PARTIAL_OK`：允许部分满足。
- `is_hard`：是否为硬性条件。
- `is_open_ended`：是否为开放式能力要求。

## 完整分析

```http
POST /api/analyze-full
Content-Type: multipart/form-data
```

表单字段：

- `file`：PDF 简历文件。
- `job_description`：岗位描述文本。
- `scoring_weights`：JSON 字符串，可选。

`scoring_weights` 示例：

```json
{
  "skill_match": 40,
  "experience_relevance": 25,
  "project_relevance": 20,
  "education_fit": 10,
  "keyword_coverage": 5
}
```

响应结构：

```json
{
  "resume_id": "90c7a4ab-0000-0000-0000-000000000000",
  "file_hash": "file_sha256",
  "parsed_from_cache": false,
  "matched_from_cache": false,
  "raw_text_preview": "简历前 800 字文本预览",
  "resume": {},
  "job_requirement": {},
  "match": {
    "score": 86,
    "level": "较匹配",
    "eligibility": "PASS",
    "confidence_score": 78,
    "breakdown": {
      "skill_match": 88,
      "experience_relevance": 80,
      "project_relevance": 86,
      "education_fit": 100,
      "keyword_coverage": 82
    },
    "weights": {
      "skill_match": 40,
      "experience_relevance": 25,
      "project_relevance": 20,
      "education_fit": 10,
      "keyword_coverage": 5
    },
    "matched_keywords": ["Python", "SQL", "React", "Git"],
    "missing_keywords": ["每周实习 4 天"],
    "requirement_results": [
      {
        "requirement_id": "req_2",
        "requirement": "熟悉前端基础，了解 React 或 Vue 其中之一",
        "category": "frontend_basic",
        "weight": 10,
        "status": "INFERRED",
        "score": 76,
        "semantic_score": 78,
        "evidence_strength": 70,
        "proficiency_score": 75,
        "project_depth": 72,
        "responsibility_score": 68,
        "recency_score": 80,
        "relation": "项目中存在前端相关实现，可作为推断证据",
        "matched_skills": ["React", "JavaScript"],
        "evidence": ["项目描述包含 Web 前端页面开发"],
        "direct_evidence": ["技能：React"],
        "inferred_evidence": ["项目为完整 Web 系统，可推断具备基础前端开发能力"],
        "missing_evidence": [],
        "rule_score": 70,
        "llm_score": 78,
        "judge_confidence": 82,
        "reason": "技能栏和项目描述共同支撑该要求。",
        "gaps": [],
        "confidence": 80
      }
    ],
    "strengths": ["后端语言、SQL、Git 有直接证据"],
    "gaps": ["实习时长需要进一步确认"],
    "risks": [],
    "reason": "整体满足岗位核心能力要求。",
    "suggestions": ["补充可实习天数和持续时间说明"],
    "ai_review": ""
  },
  "metadata": {
    "page_count": 1,
    "cache_backend": "redis",
    "llm_enabled": true,
    "security": {},
    "parse": {}
  }
}
```

顶层字段说明：

- `parsed_from_cache`：简历解析结果是否来自缓存。
- `matched_from_cache`：岗位匹配结果是否来自缓存。
- `raw_text_preview`：解析后的简历文本预览。
- `metadata.security`：文件安全检查结果。
- `metadata.parse`：PDF 页面解析路径、页面质量、OCR 情况。

`requirement_results` 说明：

- `status`：单条要求匹配状态，常见值为 `MATCHED`、`PARTIALLY_MATCHED`、`INFERRED`、`INSUFFICIENT_EVIDENCE`、`NOT_MATCHED`。
- `direct_evidence`：直接证据。
- `inferred_evidence`：推断证据。
- `missing_evidence`：缺失证据或需确认项。
- `rule_score`：规则评分。
- `llm_score`：单条要求大模型判断分。
- `judge_confidence`：大模型判断置信度。

## 调用示例

PowerShell 示例：

```powershell
$weights = @{
  skill_match = 40
  experience_relevance = 25
  project_relevance = 20
  education_fit = 10
  keyword_coverage = 5
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/analyze-full" `
  -Method Post `
  -Form @{
    file = Get-Item "D:\code\sidereus-ai\简历__2_.pdf"
    job_description = "- 熟悉 Python 和 SQL`n- 有完整 Web 项目经验"
    scoring_weights = $weights
  }
```
