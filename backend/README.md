# Backend

FastAPI 后端服务，负责 PDF 简历安全检查、页面级解析、OCR 兜底、简历信息提取、岗位 JD 结构化、单条要求判断、融合评分和缓存。

## 技术栈

- FastAPI
- Uvicorn
- PyMuPDF
- RapidOCR ONNXRuntime
- Pydantic
- OpenAI Python SDK
- Redis

## 目录结构

```text
app/
  api/
    routes.py                    API 路由
  cache/
    redis_cache.py               Redis 缓存与内存降级
  models/
    schemas.py                   简历、岗位、评分响应模型
    pdf_document.py              PDF 页面解析模型
    file_security.py             文件安全检查模型
  services/
    file_validation_service.py   文件安全检查
    pdf_parser.py                PDF 解析、OCR、页面质量评估
    extraction_service.py        简历章节识别与信息提取
    job_service.py               JD 拆分与开放式结构化
    requirement_judge_service.py 单条 JD 要求大模型判断
    scoring_service.py           证据池构建、规则评分、融合评分
    llm_service.py               AI 模型调用封装
  utils/
    text.py                      文本清洗
    hash.py                      Hash 工具
    skill_match.py               技能词边界匹配
  config.py                      环境变量配置
  main.py                        FastAPI 入口
```

## 本地启动

```powershell
cd D:\code\sidereus-ai\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```text
http://127.0.0.1:8000/api/health
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

## 环境变量

复制 `.env.example` 为 `.env` 后按需修改：

```env
APP_NAME=AI Resume Analyzer
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

LLM_PROVIDER=aliyun-bailian
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

REDIS_URL=redis://127.0.0.1:6379/0
```

说明：

- 本地开发时，如果 `LLM_API_KEY` 为空，后端会尝试读取项目根目录 `API_KEY.txt`。
- 生产环境不要使用 `API_KEY.txt`，应使用环境变量或密钥管理。
- Redis 不可用时会自动降级为 `memory-fallback`。
- 如果前端使用 `127.0.0.1:5173` 启动，`CORS_ORIGINS` 必须包含该地址。

## 核心接口

```http
GET /api/health
GET /api/scoring/default-weights
POST /api/resumes/upload
POST /api/jobs/analyze
POST /api/analyze-full
```

完整接口说明见根目录 `docs/api.md`。

## 验证命令

```powershell
cd D:\code\sidereus-ai
python -m compileall backend\app
```
