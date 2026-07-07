# 部署说明

## 前端部署到 GitHub Pages

1. 在 `frontend/.env` 中设置后端公网地址：

```env
VITE_API_BASE_URL=https://your-serverless-api.example.com
```

2. 构建前端：

```bash
cd frontend
npm install
npm run build
```

3. 将 `frontend/dist` 发布到 GitHub Pages。可以使用 GitHub Actions，也可以在仓库 Settings 中配置 Pages 分支。

## 后端部署到阿里云函数计算 FC

后端是标准 ASGI 应用，入口为：

```text
app.main:app
```

推荐部署方式：

- 使用函数计算自定义运行时或容器运行时
- 安装 `backend/requirements.txt`
- 启动命令使用 `uvicorn app.main:app --host 0.0.0.0 --port 9000`
- 配置 HTTP 触发器

生产环境变量：

```env
APP_NAME=AI Resume Analyzer
ENVIRONMENT=production
CORS_ORIGINS=https://your-github-pages-domain.github.io
LLM_PROVIDER=aliyun-bailian
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
REDIS_URL=redis://your-redis-host:6379/0
CACHE_TTL_SECONDS=86400
```

百炼 OpenAI 兼容接口也可以替换为业务空间专属域名，只需要修改 `LLM_BASE_URL`。

## Redis

本地可用 Docker 启动 Redis：

```bash
docker run --name resume-redis -p 6379:6379 -d redis:7
```

如果 `REDIS_URL` 未配置或 Redis 不可用，后端会降级为内存缓存，便于本地开发和演示；生产环境建议配置 Redis。
