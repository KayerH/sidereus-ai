# AI Resume Analyzer

面向实习招聘场景的 AI 简历分析与岗位匹配系统。系统支持上传 PDF 简历、输入岗位 JD、解析简历结构化信息、拆分岗位原子要求、构建证据池，并结合规则与大模型判断输出匹配分数、直接证据、推断证据和缺失证据。

运行环境目标：后端部署到阿里云 Serverless，前端部署到 GitHub Pages。

## 功能概览

- PDF 简历上传与安全检查：校验扩展名、MIME、PDF 文件头、文件大小、页数、加密状态、可打开性、对象数量和超大图片。
- PDF 解析与 OCR 兜底：基于 PyMuPDF 提取原生文本、文本块、图片块和页面质量；对扫描件、伪文本 PDF 或局部缺失区域使用 OCR 补偿。
- 文本清洗与章节识别：清理异常空白、控制字符和 OCR 噪声，识别基本信息、教育背景、项目经历、专业技能、荣誉证书等章节。
- 简历信息提取：提取姓名、电话、邮箱、年龄、地址、求职意向、学历、项目、技能、证书、荣誉等信息，并保留字段来源、置信度和候选值。
- JD 原子要求拆分：支持用户输入序号、`-`、`*`、自然段等格式，将岗位描述拆成独立要求。
- 开放式要求结构化：大模型为每条 JD 要求生成 `required_concepts`、`acceptable_evidence`、`evidence_logic` 等结构化信息，不依赖固定枚举类别。
- 简历能力证据池：构建技能证据、项目证据、教育证据和弱证据，用于后续匹配判断。
- 单条要求判断：`LLMRequirementJudge` 只判断单条 JD 要求与证据是否匹配，不直接计算总分。
- 融合评分：系统融合规则分、模型判断分和证据强度，输出最终分数、评分拆解、直接证据、推断证据和缺失证据。
- 可配置权重：前端支持调整评分权重，权重总和必须为 100 才能开始分析。
- Redis 缓存：缓存简历解析结果和匹配结果；Redis 不可用时自动降级到内存缓存。
- 前端体验：支持 JD 输入提示、上传分析、等待进度提示、结构化结果展示、年龄展示和证据展示。

## 技术选型

### 后端

- Python 3.10+
- FastAPI：REST API 与 ASGI 应用入口
- Uvicorn：本地开发与 Serverless 自定义运行时启动
- PyMuPDF：PDF 原生文本、文本块、页面结构、图片信息提取
- RapidOCR ONNXRuntime：扫描件和局部区域 OCR
- Pydantic：请求、响应和业务结构模型
- OpenAI Python SDK：调用阿里云百炼 OpenAI 兼容接口
- Redis：解析缓存、匹配缓存与降级缓存封装

### 前端

- React 19
- Vite 6
- lucide-react
- 原生 CSS

### AI 模型

- 默认使用阿里云百炼 OpenAI 兼容接口
- 默认模型：`qwen-plus`
- 可通过环境变量切换 `LLM_BASE_URL`、`LLM_MODEL` 和 `LLM_API_KEY`
- 若根目录存在 `API_KEY.txt`，且环境变量未提供 API Key，后端会尝试读取该文件作为本地开发密钥

### 部署

- 后端：阿里云函数计算 FC / Serverless
- 前端：GitHub Pages
- 缓存：阿里云 Redis、本地 Redis，或内存降级缓存

## 系统架构

```text
React + Vite 前端
  |
  | multipart/form-data
  v
FastAPI 后端 API
  |
  |-- 文件接收与安全检查
  |-- PDF 页面级解析
  |-- OCR 兜底与页面级择优
  |-- 文本清洗与章节识别
  |-- 规则/词典/AI 混合信息提取
  |-- JD 原子要求拆分
  |-- 大模型开放式要求结构化
  |-- 简历能力证据池构建
  |-- 单条要求 LLM 判断
  |-- 规则分与模型分融合
  |-- Redis 缓存
  v
JSON 结构化结果
```

## 项目结构

```text
backend/
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
      file_validation_service.py   文件接收与安全检查
      pdf_parser.py                PDF 解析、OCR、页面质量评估
      extraction_service.py        章节识别与简历信息提取
      job_service.py               JD 拆分与开放式结构化
      requirement_judge_service.py 单条 JD 要求大模型判断
      scoring_service.py           证据池构建、规则评分、融合评分
      llm_service.py               AI 模型调用封装
    utils/
      text.py                      文本清洗与标准化
      hash.py                      Hash 工具
      skill_match.py               技能词边界匹配工具
    config.py                      环境变量配置
    main.py                        FastAPI 入口
  requirements.txt
  .env.example

frontend/
  src/
    main.jsx                       页面逻辑与 API 调用
    styles.css                     页面样式
  index.html
  package.json
  .env.example

docs/
  api.md                           API 说明
  deploy.md                        部署说明
```

## 后端处理流程

1. 文件接收
   - 接收单个 PDF 简历文件。
   - 执行扩展名、MIME、文件头、大小、页数、加密状态、损坏情况和资源风险检查。

2. PDF 解析
   - 按页提取原生文本、文本块、图片块、坐标、页面尺寸和链接信息。
   - 计算页面质量分数。
   - 按页面质量选择 `TEXT`、`OCR`、`COMPARE` 或 `REGION_OCR` 路由。

3. OCR 与文本融合
   - 对扫描页、伪文本页或疑似缺失区域执行 OCR。
   - 原生文本和 OCR 结果按质量择优。
   - 对联系方式等关键区域可进行局部 OCR 补偿。

4. 文本清洗
   - 清理控制字符、异常空白、异常换行和 OCR 噪声。
   - 标准化手机号、邮箱、日期区间和常见技术词。

5. 简历信息提取
   - 先识别章节，再按章节提取字段。
   - 规则提取姓名、手机号、邮箱、年龄、地址、学历、日期和技能。
   - AI 模型补充项目描述、职责、求职意向等复杂字段。
   - 输出字段值、来源、置信度、证据和候选值。

6. JD 分析
   - 规则优先拆分岗位 JD 为原子要求。
   - 大模型对每条要求进行开放式结构化，生成要求概念、可接受证据和证据逻辑。
   - 对实习时长、到岗、地点、薪资等确定性条件，不强行推理，展示为需确认或缺失证据。

7. 匹配评分
   - 构建技能、项目、教育、弱证据池。
   - 确定性要求优先走规则判断。
   - 模糊、可推断要求才调用大模型判断。
   - 最终由系统融合规则分、模型分和证据强度生成分数。

## 评分说明

当前评分不是单纯关键词匹配。系统会先把 JD 拆成原子要求，再为每条要求计算匹配状态和证据。

匹配状态包括：

- `MATCHED`：有明确直接证据。
- `PARTIALLY_MATCHED`：部分满足，或有较弱但相关的证据。
- `INFERRED`：没有直接文本命中，但可从项目、技术栈或职责中合理推断。
- `INSUFFICIENT_EVIDENCE`：证据不足，需要确认。
- `NOT_MATCHED`：明确不满足。

结果证据分为：

- 直接证据：简历中明确出现的技能、学历、项目描述或经历。
- 推断证据：由项目背景、技术栈、职责描述推断出的能力。
- 缺失证据：岗位要求中没有找到有效支撑的信息。

评分拆解字段：

- `skill_match`：技能和能力类要求的融合匹配情况。
- `experience_relevance`：经历、实习、职责、直接证据和需确认条件的匹配情况。
- `project_relevance`：项目经验、项目深度、可推断能力和软能力的匹配情况。
- `education_fit`：学历、专业、学校背景等硬性条件匹配情况。
- `keyword_coverage`：要求覆盖度，不再是简单关键词覆盖。

默认权重：

```json
{
  "skill_match": 40,
  "experience_relevance": 25,
  "project_relevance": 20,
  "education_fit": 10,
  "keyword_coverage": 5
}
```

前端要求权重总和必须为 100；后端仍会对传入权重做归一化保护。

## 本地运行

### 1. 启动后端

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

Swagger 文档：

```text
http://127.0.0.1:8000/docs
```

### 2. 启动 Redis

Redis 是推荐项，不是强制项。Redis 不可用时，后端会自动降级为 `memory-fallback`。

本地 Redis 示例：

```powershell
cd D:\software\Redis
.\redis-server.exe .\redis.windows.conf
```

测试 Redis：

```powershell
.\redis-cli.exe ping
```

返回 `PONG` 表示 Redis 正常。

后端 `.env` 示例：

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

### 3. 启动前端

```powershell
cd D:\code\sidereus-ai\frontend
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 5173
```

访问：

```text
http://127.0.0.1:5173/
```

如果后端地址不同，修改 `frontend/.env`：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 环境变量

后端 `backend/.env`：

```env
APP_NAME=AI Resume Analyzer
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

MAX_UPLOAD_MB=20
MAX_PDF_PAGES=20
RECOMMENDED_RESUME_PAGES=5
MAX_PDF_IMAGE_PIXELS=25000000
MAX_PDF_OBJECTS=5000

LLM_PROVIDER=aliyun-bailian
LLM_API_KEY=
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_TIMEOUT_SECONDS=40

REDIS_URL=redis://127.0.0.1:6379/0
CACHE_TTL_SECONDS=86400
```

前端 `frontend/.env`：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 核心接口

### 健康检查

```http
GET /api/health
```

返回缓存后端和 LLM 状态。

### 默认评分权重

```http
GET /api/scoring/default-weights
```

### 上传并解析简历

```http
POST /api/resumes/upload
Content-Type: multipart/form-data
```

字段：

- `file`：PDF 简历文件

### 分析岗位 JD

```http
POST /api/jobs/analyze
Content-Type: multipart/form-data
```

字段：

- `job_description`：岗位描述文本

### 完整分析

```http
POST /api/analyze-full
Content-Type: multipart/form-data
```

字段：

- `file`：PDF 简历文件
- `job_description`：岗位 JD
- `scoring_weights`：JSON 字符串，可选

返回内容包括：

- `resume`：简历结构化信息
- `resume.sections`：章节文本
- `resume.field_details`：字段证据、来源、置信度和候选值
- `job_requirement`：JD 结构化要求
- `match`：总分、评分拆解、单条要求结果、证据、风险和建议
- `metadata.security`：文件安全检查结果
- `metadata.parse`：PDF 页面解析路径、质量分数和 OCR 情况

## 前端使用说明

1. 打开前端页面。
2. 上传 PDF 简历。
3. 在岗位 JD 输入框中填写岗位要求。
4. 推荐一行一条要求，可以使用 `-`、`*`、序号或自然段。
5. 调整评分权重，确保总和为 100。
6. 点击“开始分析”。
7. 等待解析、提取、推理、分析等步骤完成，线上环境通常需要 3-5 分钟。
8. 查看基本信息、岗位要求匹配、评分拆解、直接证据、推断证据和缺失证据。

JD 输入示例：

```text
- 计算机相关专业在读，本科或研究生
- 熟悉至少一种后端语言，能写基础 REST API
- 熟悉基础 SQL，能完成增删改查和简单联表
- 了解 React 或 Vue，有完整课程项目或 side project
- 每周可实习 4 天，能持续 3 个月以上
- 能使用 Cursor / Claude Code / ChatGPT 提升效率，并能判断生成代码对错
```

## 阿里云 Serverless 部署

后端目标运行环境为阿里云函数计算 FC。推荐使用自定义运行时或容器运行时，尤其是包含 OCR、ONNXRuntime、OpenCV 等依赖时，容器运行时更稳定。

后端 ASGI 入口：

```text
app.main:app
```

启动命令示例：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

部署步骤：

1. 在阿里云函数计算 FC 创建 Python 自定义运行时或容器函数。
2. 上传 `backend` 目录代码，或构建后端容器镜像。
3. 安装 `backend/requirements.txt` 中的依赖。
4. 配置 HTTP 触发器。
5. 配置生产环境变量：

```env
ENVIRONMENT=production
CORS_ORIGINS=https://your-github-pages-domain.github.io
LLM_PROVIDER=aliyun-bailian
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
REDIS_URL=redis://your-redis-host:6379/0
```

6. 将函数计算公网访问地址配置到前端环境变量：

```env
VITE_API_BASE_URL=https://your-fc-http-trigger-domain
```

注意事项：

- `LLM_API_KEY` 应通过函数计算环境变量或密钥管理配置，不要写入代码仓库。
- 如果后端包体过大，优先使用容器运行时。
- Redis 推荐使用阿里云 Redis 或兼容 Redis 服务。
- 生产环境需要把 GitHub Pages 域名加入 `CORS_ORIGINS`。

## GitHub Pages 部署

构建前端：

```powershell
cd D:\code\sidereus-ai\frontend
npm install
npm run build
```

发布 `frontend/dist` 到 GitHub Pages。

如果不是部署在域名根路径，需要在 Vite 配置中设置 `base`，或通过 GitHub Actions 按目标路径发布静态文件。

## 常见问题

### `/api/health` 显示 `memory-fallback`

说明后端没有连接到 Redis。检查：

- Redis 服务是否启动。
- `REDIS_URL` 是否正确。
- 后端是否在 Redis 启动后重启。
- 当前后端进程读取的 `.env` 是否正确。

### 上传同一个 PDF 后还是旧结果

系统会按文件 hash 缓存解析结果，按文件 hash、JD hash 和权重 hash 缓存匹配结果。修改解析或评分逻辑后，如果想重新测试同一个文件，需要删除旧缓存。

本地 Redis 示例：

```powershell
cd D:\software\Redis
.\redis-cli.exe keys "resume:*"
.\redis-cli.exe del <key>
```

### 年龄显示为未识别

系统只提取简历中明确出现的年龄或出生日期，不会根据入学年份、毕业年份推断年龄，因为这种推断容易产生错误。

### PDF 看起来正常但提取不完整

部分 PDF 的文本层可能损坏、顺序异常或包含伪文本。系统会根据页面质量选择 OCR、原生文本或二者比较，但极端版式仍可能影响提取效果。

### 阿里云百炼接口不可用

检查：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- 百炼平台模型权限
- 函数计算环境是否允许访问外网

## 验证命令

后端语法检查：

```powershell
cd D:\code\sidereus-ai
python -m compileall backend\app
```

前端构建：

```powershell
cd D:\code\sidereus-ai\frontend
npm run build
```
