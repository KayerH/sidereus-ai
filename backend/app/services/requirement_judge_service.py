from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models.schemas import AtomicRequirement
from app.services.llm_service import LLMService


@dataclass(slots=True)
class JudgeEvidence:
    source: str
    text: str
    strength: float = 0


@dataclass(slots=True)
class RequirementJudgeResult:
    status: str = "INSUFFICIENT_EVIDENCE"
    score: float = 0
    confidence: float = 0
    reason: str = ""
    direct_evidence: list[str] = field(default_factory=list)
    inferred_evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)


class LLMRequirementJudge:
    def __init__(self, llm: LLMService) -> None:
        self.llm = llm

    def judge(
        self,
        requirement: AtomicRequirement,
        evidence_pool: list[JudgeEvidence],
        rule_score: float,
    ) -> RequirementJudgeResult | None:
        if not self.llm.enabled or not evidence_pool:
            return None

        evidence_payload = [
            {
                "id": f"E{index + 1}",
                "source": item.source,
                "text": item.text[:700],
                "strength": item.strength,
            }
            for index, item in enumerate(evidence_pool[:8])
        ]
        evidence_by_id = {item["id"]: item for item in evidence_payload}
        system_prompt = (
            "你是受约束的招聘匹配裁判。只能依据给定证据判断单条 JD 要求。"
            "允许谨慎推断，但每个推断必须绑定 evidence_id 和原文 support。"
            "不要编造证据，不要给总分，只返回合法 JSON。"
        )
        user_prompt = {
            "requirement": requirement.model_dump(),
            "rule_score": round(rule_score, 1),
            "evidence_pool": evidence_payload,
            "output_schema": {
                "match_status": "FULLY_MATCHED|MOSTLY_MATCHED|PARTIALLY_MATCHED|INSUFFICIENT_EVIDENCE|NOT_MATCHED",
                "score": 0,
                "confidence": 0,
                "reason": "只解释本条要求",
                "direct_evidence": [{"evidence_id": "E1", "claim": "", "support": ""}],
                "inferred_evidence": [{"evidence_id": "E1", "claim": "", "support": "", "confidence": 0}],
                "missing_evidence": [""],
            },
            "rules": [
                "DIRECT_ONLY 的要求不能用 inferred_evidence 判通过。",
                "硬性条件如学历、实习时长、到岗时间必须有直接证据。",
                "如果只有宽泛技术栈，没有职责或行为支撑，最多 PARTIALLY_MATCHED。",
                "如果证据无法支撑 claim，把它放进 missing_evidence。",
            ],
        }
        payload = self.llm.chat_json(system_prompt, str(user_prompt))
        if not payload:
            return None
        return self._validate_payload(payload, evidence_by_id, requirement)

    def _validate_payload(
        self,
        payload: dict[str, Any],
        evidence_by_id: dict[str, dict[str, Any]],
        requirement: AtomicRequirement,
    ) -> RequirementJudgeResult:
        direct = self._valid_evidence_items(payload.get("direct_evidence", []), evidence_by_id)
        inferred = self._valid_evidence_items(payload.get("inferred_evidence", []), evidence_by_id)
        missing = [str(item).strip() for item in payload.get("missing_evidence", []) if str(item).strip()]

        status = str(payload.get("match_status", "INSUFFICIENT_EVIDENCE"))
        score = self._to_float(payload.get("score", 0))
        confidence = self._to_float(payload.get("confidence", 0))
        score = self._score_with_status_floor(status, score, bool(direct or inferred))

        if requirement.evidence_logic == "DIRECT_ONLY" and inferred:
            inferred = []
            score = min(score, 45)
            status = "INSUFFICIENT_EVIDENCE" if direct else "NOT_MATCHED"

        if not direct and not inferred:
            score = min(score, 25)
            status = "NOT_MATCHED"
        elif not direct and inferred:
            score = min(score, 72)
            if status == "FULLY_MATCHED":
                status = "MOSTLY_MATCHED"

        return RequirementJudgeResult(
            status=status if status in _VALID_STATUS else "INSUFFICIENT_EVIDENCE",
            score=max(0, min(score, 100)),
            confidence=max(0, min(confidence, 100)),
            reason=str(payload.get("reason", "")).strip(),
            direct_evidence=direct,
            inferred_evidence=inferred,
            missing_evidence=missing[:6],
        )

    @staticmethod
    def _valid_evidence_items(items: Any, evidence_by_id: dict[str, dict[str, Any]]) -> list[str]:
        if not isinstance(items, list):
            return []
        result: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get("evidence_id", "")).strip()
            claim = str(item.get("claim", "")).strip()
            support = str(item.get("support", "")).strip()
            evidence = evidence_by_id.get(evidence_id)
            if not evidence or not claim or not support:
                continue
            if not LLMRequirementJudge._support_in_text(support, evidence["text"]):
                continue
            result.append(f"{claim}：{support}")
        return result[:6]

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            number = float(value)
            return number * 100 if 0 < number <= 1 else number
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _support_in_text(support: str, text: str) -> bool:
        if support in text:
            return True
        compact_support = re.sub(r"\s+", "", support)
        compact_text = re.sub(r"\s+", "", text)
        if not compact_support:
            return False
        if compact_support in compact_text:
            return True
        if len(compact_support) <= 16:
            return compact_support in compact_text
        return compact_support[:12] in compact_text

    @staticmethod
    def _score_with_status_floor(status: str, score: float, has_evidence: bool) -> float:
        if not has_evidence:
            return min(score, 25)
        floors = {
            "FULLY_MATCHED": 88,
            "MOSTLY_MATCHED": 76,
            "PARTIALLY_MATCHED": 50,
        }
        ceilings = {
            "INSUFFICIENT_EVIDENCE": 58,
            "NOT_MATCHED": 25,
        }
        if status in floors:
            return max(score, floors[status])
        if status in ceilings:
            return min(score, ceilings[status])
        return score


_VALID_STATUS = {
    "FULLY_MATCHED",
    "MOSTLY_MATCHED",
    "PARTIALLY_MATCHED",
    "INSUFFICIENT_EVIDENCE",
    "NOT_MATCHED",
}
