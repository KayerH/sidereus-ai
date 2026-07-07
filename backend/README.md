# Backend

FastAPI 后端服务，提供 PDF 简历解析、AI 信息抽取、岗位 JD 分析、匹配评分和缓存能力。

## 启动

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

API 文档：

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
