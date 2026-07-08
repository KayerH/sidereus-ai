import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertCircle,
  BriefcaseBusiness,
  CheckCircle2,
  FileText,
  Loader2,
  RotateCcw,
  SlidersHorizontal,
  Upload,
} from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const DEFAULT_WEIGHTS = {
  skill_match: 40,
  experience_relevance: 25,
  project_relevance: 20,
  education_fit: 10,
  keyword_coverage: 5,
};

const WEIGHT_LABELS = {
  skill_match: "技能匹配",
  experience_relevance: "经验相关",
  project_relevance: "项目相关",
  education_fit: "学历背景",
  keyword_coverage: "要求覆盖",
};

const STATUS_LABELS = {
  FULLY_MATCHED: "完全匹配",
  MOSTLY_MATCHED: "高度匹配",
  PARTIALLY_MATCHED: "部分匹配",
  INSUFFICIENT_EVIDENCE: "证据不足",
  NOT_MATCHED: "未匹配",
  CONFLICTED: "存在冲突",
};

const JD_PLACEHOLDER = `建议按一行一条输入，支持 -、*、序号或自然段，例如：
- 计算机相关专业在读，本科或研究生
- 熟悉至少一种后端语言，能写基础 REST API
- 熟悉基础 SQL，能完成增删改查和简单联表
- 了解 React 或 Vue，有完整课程项目或 side project
- 每周可实习 4 天，能持续 3 个月以上
- 能使用 Cursor / Claude Code / ChatGPT 提升效率，并能判断生成代码对错`;

const LOADING_STEPS = [
  "安全检查",
  "PDF 解析",
  "信息提取",
  "JD 拆分",
  "证据检索",
  "模型推理",
  "综合评分",
];

function App() {
  const [file, setFile] = useState(null);
  const [jobDescription, setJobDescription] = useState("");
  const [weights, setWeights] = useState(DEFAULT_WEIGHTS);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const weightTotal = useMemo(
    () => Object.values(weights).reduce((sum, value) => sum + Number(value || 0), 0),
    [weights],
  );
  const weightTotalValid = weightTotal === 100;

  async function handleAnalyze(event) {
    event.preventDefault();
    setError("");
    setResult(null);

    if (!file) {
      setError("请先上传 PDF 简历。");
      return;
    }
    if (!jobDescription.trim()) {
      setError("请输入岗位 JD。");
      return;
    }
    if (!weightTotalValid) {
      setError("评分权重总和必须等于 100。");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("job_description", jobDescription);
    formData.append("scoring_weights", JSON.stringify(weights));

    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/analyze-full`, {
        method: "POST",
        body: formData,
      });
      const payload = await parseResponsePayload(response);
      if (!response.ok) {
        throw new Error(formatRequestError(payload, response.status));
      }
      setResult(payload);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  function updateWeight(key, value) {
    setWeights((current) => ({
      ...current,
      [key]: Number(value),
    }));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Sidereus AI Internship Task</p>
          <h1>AI Resume Analyzer</h1>
        </div>
        <div className="api-pill">API: {API_BASE_URL}</div>
      </header>

      <section className="workspace">
        <form className="input-panel" onSubmit={handleAnalyze}>
          <div className="section-title">
            <Upload size={20} />
            <h2>简历与岗位</h2>
          </div>

          <label className="file-zone">
            <input
              type="file"
              accept="application/pdf"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
            <FileText size={28} />
            <span>{file ? file.name : "选择 PDF 简历"}</span>
          </label>

          <label className="field">
            <span>岗位 JD</span>
            <textarea
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              placeholder={JD_PLACEHOLDER}
            />
          </label>

          <div className="weights-area">
            <div className="section-title compact">
              <SlidersHorizontal size={18} />
              <h2>评分权重</h2>
              <button
                className="icon-button"
                type="button"
                title="恢复默认权重"
                onClick={() => setWeights(DEFAULT_WEIGHTS)}
              >
                <RotateCcw size={16} />
              </button>
            </div>
            <div className={`weight-total ${weightTotalValid ? "" : "invalid"}`}>
              总权重 {weightTotal} / 100
              {!weightTotalValid && <span>请调整到 100 后开始分析</span>}
            </div>
            {Object.entries(weights).map(([key, value]) => (
              <label className="weight-row" key={key}>
                <span>{WEIGHT_LABELS[key]}</span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={value}
                  onChange={(event) => updateWeight(key, event.target.value)}
                />
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={value}
                  onChange={(event) => updateWeight(key, event.target.value)}
                />
              </label>
            ))}
          </div>

          {error && (
            <div className="message error">
              <AlertCircle size={18} />
              <span>{error}</span>
            </div>
          )}

          <button className="primary-button" type="submit" disabled={loading || !weightTotalValid}>
            {loading ? <Loader2 className="spin" size={18} /> : <BriefcaseBusiness size={18} />}
            <span>{loading ? "分析中" : "开始分析"}</span>
          </button>
        </form>

        <ResultPanel result={result} loading={loading} />
      </section>
    </main>
  );
}

function ResultPanel({ result, loading }) {
  if (loading) {
    return (
      <section className="result-panel centered">
        <Loader2 className="spin" size={34} />
        <p>正在分析，通常需要 3-5 分钟，请保持页面打开。</p>
        <div className="progress-steps">
          {LOADING_STEPS.map((step, index) => (
            <span key={step} style={{ animationDelay: `${index * 0.35}s` }}>
              {step}
            </span>
          ))}
        </div>
      </section>
    );
  }

  if (!result) {
    return (
      <section className="result-panel empty">
        <FileText size={42} />
        <p>上传简历并输入岗位 JD 后，分析结果会显示在这里。</p>
      </section>
    );
  }

  const resume = result.resume;
  const match = result.match;
  const job = result.job_requirement;

  return (
    <section className="result-panel">
      <div className="score-band">
        <div>
          <p className="eyebrow">匹配度评分</p>
          <div className="score-line">
            <strong>{match.score}</strong>
            <span>{match.level}</span>
          </div>
        </div>
        <div className="cache-state">
          <CheckCircle2 size={16} />
          <span>{match.eligibility || "PASS"} · 置信度 {match.confidence_score || 0}% · {result.metadata.cache_backend}</span>
        </div>
      </div>

      <div className="grid two">
        <InfoBlock title="基本信息" items={resume.basic_info} />
        <InfoBlock
          title="求职信息"
          items={{
            求职意向: resume.job_intention.position || "未识别",
            期望薪资: resume.job_intention.expected_salary || "未识别",
            工作年限: resume.background.years_of_experience || "未识别",
          }}
        />
      </div>

      <div className="block">
        <h3>评分拆解</h3>
        <div className="breakdown">
          {Object.entries(match.breakdown).map(([key, value]) => (
            <div className="bar-row" key={key}>
              <span>{WEIGHT_LABELS[key]}</span>
              <div>
                <i style={{ width: `${value}%` }} />
              </div>
              <b>{Math.round(value)}</b>
            </div>
          ))}
        </div>
      </div>

      <RequirementBlock requirements={match.requirement_results || []} />

      <TagBlock title="已匹配关键词" tags={match.matched_keywords} />
      <TagBlock title="待补充关键词" tags={match.missing_keywords} muted />
      <TagBlock title="岗位关键词" tags={job.job_keywords} />
      <TagBlock title="简历技能" tags={resume.background.skills} />

      <div className="block">
        <h3>项目经历</h3>
        <div className="list-stack">
          {resume.background.projects.length ? (
            resume.background.projects.map((project, index) => (
              <article className="item-card" key={`${project.name}-${index}`}>
                <h4>{project.name || `项目 ${index + 1}`}</h4>
                <p>{project.description || "暂无项目描述"}</p>
                <small>{project.technologies.join(" / ")}</small>
              </article>
            ))
          ) : (
            <p className="muted-text">未识别到明确项目经历。</p>
          )}
        </div>
      </div>

      <div className="block">
        <h3>匹配说明</h3>
        <p>{match.ai_review || match.reason}</p>
        <ul className="suggestions">
          {match.suggestions.map((suggestion) => (
            <li key={suggestion}>{suggestion}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function RequirementBlock({ requirements }) {
  if (!requirements.length) {
    return null;
  }

  return (
    <div className="block">
      <h3>岗位要求逐条匹配</h3>
      <div className="requirement-list">
        {requirements.map((item) => (
          <article className="requirement-card" key={item.requirement_id || item.requirement}>
            <div className="requirement-head">
              <div>
                <strong>{item.requirement}</strong>
                <span>{item.relation}</span>
              </div>
              <div className={`status-pill status-${item.status}`}>
                {STATUS_LABELS[item.status] || item.status}
                <b>{Math.round(item.score)}</b>
              </div>
            </div>
            <p>{item.reason}</p>
            {!!item.matched_skills?.length && (
              <div className="mini-tags">
                {item.matched_skills.slice(0, 8).map((skill) => (
                  <span key={`${item.requirement_id}-${skill}`}>{skill}</span>
                ))}
              </div>
            )}
            {!!item.evidence?.length && (
              <ul className="evidence-list">
                {item.evidence.slice(0, 2).map((evidence) => (
                  <li key={evidence}>{evidence}</li>
                ))}
              </ul>
            )}
            <EvidenceGroup title="直接证据" items={item.direct_evidence} />
            <EvidenceGroup title="推断证据" items={item.inferred_evidence} inferred />
            <EvidenceGroup title="缺失证据" items={item.missing_evidence} missing />
            {!!item.gaps?.length && (
              <ul className="gap-list">
                {item.gaps.slice(0, 2).map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

function EvidenceGroup({ title, items = [], inferred = false, missing = false }) {
  if (!items.length) {
    return null;
  }
  const className = `evidence-group ${inferred ? "inferred" : ""} ${missing ? "missing" : ""}`;
  return (
    <div className={className}>
      <b>{title}</b>
      <ul>
        {items.slice(0, 3).map((item) => (
          <li key={`${title}-${item}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function InfoBlock({ title, items }) {
  return (
    <div className="block">
      <h3>{title}</h3>
      <dl className="info-list">
        {Object.entries(items).map(([key, value]) => (
          <React.Fragment key={key}>
            <dt>{formatKey(key)}</dt>
            <dd>{String(value || "未识别")}</dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
}

function TagBlock({ title, tags, muted = false }) {
  return (
    <div className="block">
      <h3>{title}</h3>
      <div className={`tags ${muted ? "muted" : ""}`}>
        {tags.length ? tags.map((tag) => <span key={tag}>{tag}</span>) : <em>暂无</em>}
      </div>
    </div>
  );
}

function formatKey(key) {
  const map = {
    name: "姓名",
    phone: "电话",
    email: "邮箱",
    age: "年龄",
    address: "地址",
  };
  return map[key] || key;
}

async function parseResponsePayload(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

function formatRequestError(payload, status) {
  if (payload.detail) {
    return Array.isArray(payload.detail) ? JSON.stringify(payload.detail) : String(payload.detail);
  }
  if (payload.Message || payload.Code) {
    const code = payload.Code ? `错误码：${payload.Code}` : `HTTP ${status}`;
    const message = payload.Message ? `，原因：${payload.Message}` : "";
    const requestId = payload.RequestId ? `，RequestId：${payload.RequestId}` : "";
    return `${code}${message}${requestId}`;
  }
  if (payload.message) {
    return String(payload.message);
  }
  return `分析失败，HTTP 状态码：${status}`;
}

createRoot(document.getElementById("root")).render(<App />);
