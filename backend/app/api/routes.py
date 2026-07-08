from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.cache.redis_cache import CacheManager
from app.models.schemas import (
    AnalyzeFullResponse,
    ErrorResponse,
    JobRequirement,
    ResumeExtraction,
    ScoringWeights,
)
from app.models.pdf_document import DocumentAnalysis
from app.services.extraction_service import ResumeExtractionService
from app.services.job_service import JobRequirementService
from app.services.llm_service import LLMService
from app.services.pdf_parser import PDFParser
from app.services.scoring_service import ScoringService
from app.utils.hash import sha256_text

router = APIRouter()

cache = CacheManager()
llm = LLMService()
pdf_parser = PDFParser()
resume_extractor = ResumeExtractionService(llm)
job_analyzer = JobRequirementService(llm)
scorer = ScoringService(llm)


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "cache": cache.backend_name,
        "llm": "enabled" if llm.enabled else "disabled",
    }


@router.get("/scoring/default-weights", response_model=ScoringWeights)
def default_weights() -> ScoringWeights:
    return ScoringWeights()


@router.post(
    "/resumes/upload",
    response_model=ResumeExtraction,
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def upload_resume(file: UploadFile = File(...)) -> ResumeExtraction:
    content, security_report = await pdf_parser.read_pdf_with_report(file)
    file_hash = security_report.file_hash
    cache_key = f"resume:parse:{file_hash}"

    cached = cache.get_json(cache_key)
    if cached:
        return ResumeExtraction.model_validate(cached["resume"])

    analysis = pdf_parser.analyze_document(content)
    resume_text = analysis.selected_text
    resume = resume_extractor.extract(resume_text)
    cache.set_json(
        cache_key,
        {
            "resume": resume.model_dump(),
            "raw_text": resume_text,
            "page_count": analysis.page_count,
            "security_report": security_report.model_dump(),
            "parse_metadata": _pdf_analysis_metadata(analysis),
        },
    )
    return resume


@router.post("/jobs/analyze", response_model=JobRequirement)
async def analyze_job(job_description: str = Form(...)) -> JobRequirement:
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="岗位 JD 不能为空")
    return job_analyzer.analyze(job_description)


@router.post(
    "/analyze-full",
    response_model=AnalyzeFullResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def analyze_full(
    file: UploadFile = File(...),
    job_description: str = Form(...),
    scoring_weights: str = Form(""),
) -> AnalyzeFullResponse:
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="岗位 JD 不能为空")

    try:
        weights = _parse_weights(scoring_weights)
        content, security_report = await _run_stage(
            "文件接收与安全检查",
            pdf_parser.read_pdf_with_report(file),
        )
        file_hash = security_report.file_hash
        jd_hash = sha256_text(job_description)
        parse_cache_key = f"resume:parse:{file_hash}"
        match_cache_key = f"resume:match:{file_hash}:{jd_hash}:{sha256_text(weights.model_dump_json())}"

        cached_parse = cache.get_json(parse_cache_key)
        parsed_from_cache = bool(cached_parse)
        if cached_parse:
            resume_text = cached_parse["raw_text"]
            resume = ResumeExtraction.model_validate(cached_parse["resume"])
            page_count = cached_parse.get("page_count", 0)
            parse_metadata = cached_parse.get("parse_metadata", {})
            security_metadata = cached_parse.get("security_report", security_report.model_dump())
        else:
            analysis = _run_stage_sync("PDF 解析", lambda: pdf_parser.analyze_document(content))
            resume_text = analysis.selected_text
            page_count = analysis.page_count
            parse_metadata = _pdf_analysis_metadata(analysis)
            security_metadata = security_report.model_dump()
            resume = _run_stage_sync("简历信息提取", lambda: resume_extractor.extract(resume_text))
            cache.set_json(
                parse_cache_key,
                {
                    "resume": resume.model_dump(),
                    "raw_text": resume_text,
                    "page_count": page_count,
                    "security_report": security_metadata,
                    "parse_metadata": parse_metadata,
                },
            )

        cached_match = cache.get_json(match_cache_key)
        matched_from_cache = bool(cached_match)
        if cached_match:
            job = JobRequirement.model_validate(cached_match["job_requirement"])
            match = cached_match["match"]
        else:
            job = _run_stage_sync("JD 结构化分析", lambda: job_analyzer.analyze(job_description))
            match_result = _run_stage_sync("匹配评分", lambda: scorer.score(resume, job, weights))
            match = match_result.model_dump()
            cache.set_json(
                match_cache_key,
                {
                    "job_requirement": job.model_dump(),
                    "match": match,
                },
            )

        return AnalyzeFullResponse.model_validate(
            {
                "resume_id": str(uuid.uuid5(uuid.NAMESPACE_URL, file_hash)),
                "file_hash": file_hash,
                "parsed_from_cache": parsed_from_cache,
                "matched_from_cache": matched_from_cache,
                "raw_text_preview": resume_text[:800],
                "resume": resume.model_dump(),
                "job_requirement": job.model_dump(),
                "match": match,
                "metadata": {
                    "page_count": page_count,
                    "cache_backend": cache.backend_name,
                    "llm_enabled": llm.enabled,
                    "security": security_metadata,
                    "parse": parse_metadata,
                },
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"完整分析失败：{type(exc).__name__}: {exc}") from exc


def _parse_weights(raw_weights: str) -> ScoringWeights:
    if not raw_weights.strip():
        return ScoringWeights()
    try:
        payload = json.loads(raw_weights)
        return ScoringWeights.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="评分权重必须是合法 JSON") from exc


async def _run_stage(stage: str, awaitable):
    try:
        return await awaitable
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{stage}失败：{type(exc).__name__}: {exc}") from exc


def _run_stage_sync(stage: str, action):
    try:
        return action()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{stage}失败：{type(exc).__name__}: {exc}") from exc


def _pdf_analysis_metadata(analysis: DocumentAnalysis) -> dict[str, object]:
    return {
        "document_type": analysis.document_type,
        "page_count": analysis.page_count,
        "pages": [
            {
                "page_number": page.page_number,
                "route": page.route.value,
                "selected_source": page.selected_source,
                "native_quality_score": page.native_quality.overall_score,
                "ocr_quality_score": page.ocr_quality.overall_score if page.ocr_quality else None,
                "image_coverage_ratio": page.native_quality.image_coverage_ratio,
                "char_count": page.native_quality.non_space_chars,
                "ocr_average_confidence": page.ocr_quality.ocr_average_confidence if page.ocr_quality else 0,
            }
            for page in analysis.pages
        ],
    }
