# API 文档

后端默认地址：`http://localhost:8000`

## 健康检查

```http
GET /api/health
```

响应：

```json
{
  "status": "ok",
  "cache": "redis",
  "llm": "enabled"
}
```

## 上传并解析简历

```http
POST /api/resumes/upload
Content-Type: multipart/form-data
```

表单字段：

- `file`: PDF 简历文件

响应为简历结构化信息。

## 分析岗位 JD

```http
POST /api/jobs/analyze
Content-Type: multipart/form-data
```

表单字段：

- `job_description`: 岗位描述文本

响应：

```json
{
  "required_skills": ["Python", "FastAPI"],
  "preferred_skills": ["Redis"],
  "experience_requirements": "1 年以上后端开发经验",
  "education_requirements": "本科及以上",
  "job_keywords": ["Python", "FastAPI", "后端"],
  "responsibilities": []
}
```

## 完整分析

```http
POST /api/analyze-full
Content-Type: multipart/form-data
```

表单字段：

- `file`: PDF 简历文件
- `job_description`: 岗位描述文本
- `scoring_weights`: JSON 字符串，可选

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

响应包含：

- `resume`: 简历结构化信息
- `job_requirement`: 岗位结构化要求
- `match`: 匹配分数、评分拆解、命中关键词、缺失关键词、建议
- `metadata`: 页数、缓存后端、AI 是否启用

## 默认评分权重

```http
GET /api/scoring/default-weights
```

响应：

```json
{
  "skill_match": 40,
  "experience_relevance": 25,
  "project_relevance": 20,
  "education_fit": 10,
  "keyword_coverage": 5
}
```
