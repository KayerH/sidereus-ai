# 部署说明

项目目标部署方式：

- 后端：阿里云 Serverless / 函数计算 FC
- 前端：GitHub Pages
- 缓存：阿里云 Redis 或兼容 Redis 服务
- AI：阿里云百炼 OpenAI 兼容接口

## 部署前准备

### 后端环境变量

生产环境推荐通过阿里云函数计算环境变量或密钥管理配置，不要把真实密钥写入代码仓库。

```env
APP_NAME=AI Resume Analyzer
ENVIRONMENT=production
CORS_ORIGINS=https://your-github-pages-domain.github.io

MAX_UPLOAD_MB=20
MAX_PDF_PAGES=20
RECOMMENDED_RESUME_PAGES=5
MAX_PDF_IMAGE_PIXELS=25000000
MAX_PDF_OBJECTS=5000

LLM_PROVIDER=aliyun-bailian
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_TIMEOUT_SECONDS=40

REDIS_URL=redis://your-redis-host:6379/0
CACHE_TTL_SECONDS=86400
```

说明：

- `CORS_ORIGINS` 必须包含 GitHub Pages 域名。
- `LLM_API_KEY` 本地开发可以来自根目录 `API_KEY.txt`，生产环境必须使用环境变量或密钥管理。
- `REDIS_URL` 生产环境建议配置阿里云 Redis 或兼容 Redis 服务。
- 如果不配置 Redis，系统会降级为 `memory-fallback`，但不适合作为生产缓存方案。

### 前端环境变量

`frontend/.env`：

```env
VITE_API_BASE_URL=https://your-fc-http-trigger-domain
```

该地址应指向阿里云函数计算 HTTP 触发器公网地址，不需要额外拼接 `/api`，前端代码会调用后端的 `/api/...` 接口。

## 后端部署到阿里云函数计算 FC

后端是 FastAPI ASGI 应用，入口为：

```text
app.main:app
```

启动命令示例：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

### 推荐方式：容器运行时

项目依赖 RapidOCR、ONNXRuntime、PyMuPDF 等 PDF/OCR 相关库，部署包可能较大。生产环境优先推荐函数计算容器运行时，依赖更可控。

部署步骤：

1. 准备后端镜像，工作目录指向 `backend`。
2. 安装 `backend/requirements.txt` 中的依赖。
3. 设置启动命令：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

4. 在函数计算 FC 创建容器函数。
5. 配置 HTTP 触发器。
6. 配置生产环境变量。
7. 部署后访问：

```text
https://your-fc-http-trigger-domain/api/health
```

预期返回：

```json
{
  "status": "ok",
  "cache": "redis",
  "llm": "enabled"
}
```

### 可选方式：Python 3.10 自定义运行时

如果依赖包大小和系统库兼容性可控，也可以使用 Python 自定义运行时。由于 `rapidocr-onnxruntime` 依赖 `onnxruntime`，ZIP 部署时推荐选择 **Python 3.10**，不要选择 Python 3.12，否则可能出现 `No module named uvicorn`、`onnxruntime` 无可用 wheel 或二进制依赖不兼容问题。

部署步骤：

1. 在阿里云函数计算 FC 创建 Python 自定义运行时函数。
2. 上传 `backend` 目录代码。
3. 安装 `requirements.txt` 中的依赖。
4. 配置启动命令：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

5. 配置 HTTP 触发器和环境变量。
6. 使用 `/api/health` 验证服务状态。

注意事项：

- OCR 相关依赖可能需要额外系统库支持。
- 如果安装依赖失败或部署包过大，改用容器运行时。
- 函数超时时间应覆盖 PDF 解析、OCR 和 LLM 调用耗时。
- 建议为完整分析接口预留至少 5 分钟级别的超时时间。

## 前端部署到 GitHub Pages

### 1. 配置后端地址

修改 `frontend/.env`：

```env
VITE_API_BASE_URL=https://your-fc-http-trigger-domain
```

### 2. 构建前端

```powershell
cd D:\code\sidereus-ai\frontend
npm install
npm run build
```

构建产物位于：

```text
frontend/dist
```

### 3. 发布到 GitHub Pages

可以使用两种方式：

- 在仓库 Settings 中配置 Pages 分支或目录。
- 使用 GitHub Actions 将 `frontend/dist` 发布到 Pages。

如果站点不是部署在域名根路径，需要在 Vite 配置中设置 `base`，否则静态资源路径可能加载失败。

### 4. 配置 CORS

前端部署完成后，将 GitHub Pages 域名加入后端环境变量：

```env
CORS_ORIGINS=https://your-github-pages-domain.github.io
```

修改后需要重新部署或重启后端函数。

## Redis 部署

生产环境建议使用阿里云 Redis 或兼容 Redis 服务。

后端通过 `REDIS_URL` 连接：

```env
REDIS_URL=redis://your-redis-host:6379/0
```

Redis 用途：

- 缓存 PDF 解析结果，避免同一文件重复解析。
- 缓存 JD 匹配结果，避免同一文件、同一 JD、同一权重重复推理。
- 降低大模型调用次数和响应时间。

本地开发可使用已有 Redis，也可以使用 Docker：

```bash
docker run --name resume-redis -p 6379:6379 -d redis:7
```

如果 `/api/health` 返回：

```json
{
  "cache": "memory-fallback"
}
```

说明当前后端未连接到 Redis。检查：

- Redis 服务是否启动。
- `REDIS_URL` 是否正确。
- 函数计算网络是否能访问 Redis。
- 后端是否已重新部署或重启。

## AI 模型配置

默认使用阿里云百炼 OpenAI 兼容接口：

```env
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

如果使用业务空间专属域名或其他兼容接口，只需要修改 `LLM_BASE_URL` 和 `LLM_MODEL`。

注意：

- 生产环境不要使用 `API_KEY.txt`。
- 确认百炼平台已开通目标模型权限。
- 确认函数计算运行环境允许访问外网。
- LLM 不可用时，系统仍可运行规则兜底逻辑，但开放式结构化和模糊要求推理效果会下降。

## 部署验证

### 后端验证

```text
https://your-fc-http-trigger-domain/api/health
```

检查：

- `status` 是否为 `ok`。
- `cache` 是否为 `redis`。
- `llm` 是否为 `enabled`。

### 前端验证

1. 打开 GitHub Pages 地址。
2. 上传 PDF 简历。
3. 输入岗位 JD。
4. 确保评分权重总和为 100。
5. 点击开始分析。
6. 检查是否显示基本信息、评分拆解、直接证据、推断证据和缺失证据。

## 常见问题

### 前端请求后端失败

检查：

- `VITE_API_BASE_URL` 是否是函数计算公网地址。
- 后端 `CORS_ORIGINS` 是否包含 GitHub Pages 域名。
- 函数计算 HTTP 触发器是否允许公网访问。
- 浏览器控制台是否有 CORS 或网络错误。

### 后端启动失败

检查：

- Python 版本是否满足依赖要求。
- `requirements.txt` 是否安装完整。
- OCR / ONNXRuntime 相关依赖是否兼容当前运行时。
- 端口是否与函数计算运行时要求一致。

### 完整分析超时

完整分析包含 PDF 解析、OCR、简历抽取、JD 结构化、LLM 单条要求判断和综合评分，线上环境耗时可能达到 3-5 分钟。

处理建议：

- 提高函数计算超时时间。
- 启用 Redis 缓存。
- 优先使用文本层质量较好的 PDF。
- 对部署包和 OCR 依赖较重的场景使用容器运行时。
