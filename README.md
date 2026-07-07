# AI Resume Analyzer

AI 赋能的智能简历分析系统。项目面向招聘场景，支持上传 PDF 简历，完成文件安全检查、PDF 解析、OCR 兜底、章节识别、关键信息抽取、岗位 JD 分析、简历匹配评分和结果展示。

运行环境目标为 **阿里云 Serverless（函数计算 FC）**。后端采用 FastAPI ASGI 应用，前端采用 React + Vite，可部署到 GitHub Pages。

## 功能概览

- PDF 简历上传与安全检查
  - 校验扩展名、MIME、PDF 文件头、文件大小、页数、加密状态、PDF 可打开性、内部对象数和超大图片。
- PDF 文本解析
  - 使用 PyMuPDF 提取文本块、坐标、图片块、页面质量信息。
  - 支持原生文本、整页 OCR、局部 OCR、原生文本与 OCR 双通道比较。
- 简历信息抽取
  - 先进行章节识别，再按章节抽取字段。
  - 采用规则、词典和 AI 模型混合抽取。
  - 输出字段值、来源、置信度、证据和候选值。
- 岗位 JD 分析
  - 提取必备技能、加分技能、岗位关键词、经验要求和学历要求。
- 简历匹配评分
  - 按技能匹配、经验相关、项目相关、学历背景、关键词覆盖五个维度评分。
  - 前端可调整评分权重，后端自动归一化。
- 缓存机制
  - Redis 缓存简历解析结果和匹配结果。
  - Redis 不可用时自动降级为内存缓存。
- 前端页面
  - 支持上传 PDF、输入岗位 JD、调整评分权重、查看结构化结果和匹配分数。

## 技术选型

后端：

- Python 3.10+
- FastAPI：RESTful API 和 ASGI 服务
- Uvicorn：本地开发和 Serverless 自定义运行时启动
- PyMuPDF：PDF 原生文本、文本块、图片块和页面结构提取
- RapidOCR ONNXRuntime：扫描件、伪文本 PDF 和局部区域 OCR
- Pydantic：请求、响应和结构化数据模型
- OpenAI Python SDK：调用阿里云百炼 OpenAI 兼容接口
- Redis：解析结果和评分结果缓存

前端：

- React
- Vite
- lucide-react
- 原生 CSS

AI 模型：

- 默认使用阿里云百炼平台 OpenAI 兼容接口
- 默认模型：`qwen-plus`
- 可通过环境变量切换模型和 Base URL

部署：

- 后端：阿里云函数计算 FC（Serverless）
- 前端：GitHub Pages 或其他静态站点服务
- 缓存：阿里云 Redis / 本地 Redis / 内存降级

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
  |-- 文本清洗与标准化
  |-- 简历章节识别
  |-- 规则/词典/AI 信息抽取
  |-- 岗位 JD 分析
  |-- 动态权重匹配评分
  |-- Redis 缓存
  v
JSON 结构化结果
```

## 项目结构

```text
backend/
  app/
    api/
      routes.py                  API 路由
    cache/
      redis_cache.py             Redis 缓存与内存降级
    models/
      schemas.py                 业务响应模型
      pdf_document.py            PDF 页面解析模型
      file_security.py           文件安全检查模型
    services/
      file_validation_service.py 文件接收与安全检查
      pdf_parser.py              PDF 解析、OCR、页面质量评估
      extraction_service.py      章节识别与信息抽取
      job_service.py             岗位 JD 分析
      scoring_service.py         匹配评分
      llm_service.py             AI 模型调用封装
    utils/
      text.py                    文本清洗和标准化
      hash.py                    Hash 工具
    config.py                    环境变量配置
    main.py                      FastAPI 入口
  requirements.txt
  .env.example

frontend/
  src/
    main.jsx                     前端页面逻辑
    styles.css                   页面样式
  index.html
  package.json
  .env.example

docs/
  api.md                         API 说明
  deploy.md                      部署说明
```

## 后端处理流程

1. 文件上传
   - 接收单个 PDF 文件。
   - 执行扩展名、MIME、文件头、大小、页数、加密、损坏和资源风险检查。

2. PDF 解析
   - 对每页提取原生文本、文本块、坐标、图片块、页面尺寸和链接信息。
   - 计算页面质量分数。
   - 路由为 `TEXT`、`OCR`、`COMPARE` 或 `REGION_OCR`。

3. OCR 与文本融合
   - 对扫描页或伪文本页执行 OCR。
   - 原生文本和 OCR 结果按页面质量进行择优。
   - 对联系方式区域可进行局部 OCR 补偿。

4. 文本清洗
   - 清理控制字符、异常空白、异常换行、OCR 噪声。
   - 标准化手机号、邮箱、日期区间和技术关键词。

5. 信息提取
   - 先识别章节，如教育背景、项目经历、专业技能、获奖情况、自我评价。
   - 规则抽取手机号、邮箱、地址、学历、日期、技能。
   - 词典抽取技术栈、学历、学校和证书等。
   - AI 模型按章节补充项目描述、职责、求职意向等复杂字段。

6. 岗位匹配评分
   - 分析岗位 JD。
   - 计算技能匹配、经验相关、项目相关、学历匹配、关键词覆盖。
   - 使用前端传入权重计算总分。

## 本地运行

### 1. 后端

```powershell
cd D:\code\sidereus-ai\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

如果项目根目录存在 `API_KEY.txt`，且 `LLM_API_KEY` 为空，后端会自动读取该文件作为阿里云百炼 API Key。真实密钥不要提交到 Git。

健康检查：

```text
http://127.0.0.1:8000/api/health
```

Swagger 文档：

```text
http://127.0.0.1:8000/docs
```

### 2. Redis

Redis 可选。未配置或连接失败时，系统会降级为内存缓存。

本地已有 Redis 时：

```powershell
cd D:\software\Redis
.\redis-server.exe .\redis.windows.conf
```

测试：

```powershell
.\redis-cli.exe ping
```

返回 `PONG` 表示 Redis 正常。

后端 `.env` 配置：

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

### 3. 前端

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

### 上传并解析简历

```http
POST /api/resumes/upload
Content-Type: multipart/form-data
```

字段：

- `file`: PDF 简历文件

### 岗位 JD 分析

```http
POST /api/jobs/analyze
Content-Type: multipart/form-data
```

字段：

- `job_description`: 岗位描述文本

### 完整分析

```http
POST /api/analyze-full
Content-Type: multipart/form-data
```

字段：

- `file`: PDF 简历文件
- `job_description`: 岗位 JD
- `scoring_weights`: JSON 字符串，可选

评分权重示例：

```json
{
  "skill_match": 40,
  "experience_relevance": 25,
  "project_relevance": 20,
  "education_fit": 10,
  "keyword_coverage": 5
}
```

## 返回结果说明

`/api/analyze-full` 返回内容包括：

- `resume`: 简历结构化信息
- `resume.sections`: 分章节文本
- `resume.field_details`: 字段证据、来源、置信度和候选值
- `job_requirement`: 岗位结构化要求
- `match`: 匹配评分、评分拆解、命中关键词、缺失关键词和建议
- `metadata.security`: 文件安全检查报告
- `metadata.parse`: PDF 页面解析路径、质量分数和 OCR 情况

## 评分逻辑

当前最终分数由规则评分计算，AI 只生成简短评价，不直接修改分数。

评分维度：

- 技能匹配：岗位技能在简历中的命中率
- 经验相关：工作年限和经历完整度
- 项目相关：项目经历对岗位关键词的覆盖程度
- 学历背景：简历学历是否满足岗位要求
- 关键词覆盖：岗位关键词在简历中的总体覆盖率

最终分数：

```text
总分 =
技能匹配分 * 技能权重
+ 经验相关分 * 经验权重
+ 项目相关分 * 项目权重
+ 学历背景分 * 学历权重
+ 关键词覆盖分 * 关键词权重
```

前端传入的权重不要求总和为 100，后端会自动归一化。

评分等级：

```text
90-100：高度匹配
75-89：较匹配
60-74：基本匹配
60 以下：匹配度较低
```

## 阿里云 Serverless 部署

后端运行环境要求为 **阿里云 Serverless（函数计算 FC）**。

推荐方式：函数计算自定义运行时或容器运行时。

后端入口：

```text
app.main:app
```

启动命令：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

部署步骤：

1. 在阿里云函数计算 FC 创建 Python 自定义运行时或容器函数。
2. 上传 `backend` 目录代码。
3. 安装 `backend/requirements.txt` 中依赖。
4. 配置 HTTP 触发器。
5. 配置环境变量：

```env
ENVIRONMENT=production
CORS_ORIGINS=https://your-github-pages-domain.github.io
LLM_PROVIDER=aliyun-bailian
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
REDIS_URL=redis://your-redis-host:6379/0
```

6. 将函数计算公网访问地址配置到前端：

```env
VITE_API_BASE_URL=https://your-fc-http-trigger-domain
```

7. 重新构建并发布前端。

注意：

- OCR 依赖包含 ONNXRuntime 和 OpenCV，函数计算环境需要确保依赖可安装。
- 若部署包过大，建议使用容器运行时。
- Redis 推荐使用阿里云 Redis 或兼容 Redis 服务。
- `LLM_API_KEY` 应通过函数计算环境变量或密钥管理配置，不要写入代码。

## 前端部署到 GitHub Pages

```powershell
cd frontend
npm install
npm run build
```

将 `frontend/dist` 发布到 GitHub Pages。

如果项目不是部署在域名根路径，可在 Vite 配置中设置 `base`，或使用 GitHub Actions 发布静态文件。

## 常见问题

### Redis 显示 `memory-fallback`

说明后端没有连接到 Redis。检查：

- Redis 是否启动
- `REDIS_URL` 是否配置
- 后端是否重启

### 修改代码后上传同一个 PDF 还是旧结果

可能命中了 Redis 缓存。可以删除对应 key：

```powershell
cd D:\software\Redis
.\redis-cli.exe keys "resume:*"
.\redis-cli.exe del <key>
```

### PDF 看起来正常但提取不完整

部分 PDF 的文本层可能损坏或顺序错误。系统会根据页面质量选择 OCR 或原生文本与 OCR 比较。

### 阿里云百炼接口不可用

检查：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- 百炼平台模型权限

## 验证命令

```powershell
cd D:\code\sidereus-ai
python -m compileall backend\app

cd frontend
npm run build
```

## 说明

本项目重点体现：

- Serverless 后端工程化
- PDF 安全检查
- PDF 页面级解析与 OCR 兜底
- 简历章节识别和可追溯字段抽取
- AI 模型辅助结构化
- 可配置权重的岗位匹配评分
- Redis 缓存和降级策略
