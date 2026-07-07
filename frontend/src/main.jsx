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
  keyword_coverage: "关键词覆盖",
};

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
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "分析失败，请稍后重试。");
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
              placeholder="粘贴招聘岗位描述，例如 Python 后端实习生，熟悉 FastAPI、Redis、LLM API..."
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
            <div className="weight-total">总权重 {weightTotal}</div>
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

          <button className="primary-button" type="submit" disabled={loading}>
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
        <p>正在解析 PDF、抽取信息并计算匹配度...</p>
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
          <span>{result.metadata.cache_backend}</span>
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
    address: "地址",
  };
  return map[key] || key;
}

createRoot(document.getElementById("root")).render(<App />);
