from __future__ import annotations

from statistics import mean
from typing import Any

from .knowledge import KnowledgeBase
from .models import Claim, LearnerProfile


class QualityGate:
    """Non-Agent quality scoring and admission service."""

    name = "质量评估与准入模块"

    def assess_and_admit(
        self,
        claims: list[Claim],
        kb: KnowledgeBase,
        *,
        acceptance_threshold: float,
        review_threshold: float,
        calibrated: bool,
        abstention: bool,
        enforce: bool = True,
    ) -> dict[str, Any]:
        for claim in claims:
            valid_evidence = [
                paper_id
                for paper_id in claim.evidence_ids
                if paper_id in kb.paper_by_id
            ]
            evidence_bonus = min(0.08, 0.04 * len(valid_evidence))
            independence_bonus = 0.04 if len(valid_evidence) >= 2 else 0.0
            penalty = 0.0
            if not valid_evidence:
                penalty += 0.45
            if claim.relation in {"guarantees", "proves"}:
                penalty += 0.20
            if claim.base_confidence < 0.7:
                penalty += 0.08
            if calibrated:
                evidence_bonus += min(0.04, 0.02 * len(claim.evidence_spans))
                if len({view["perspective"] for view in claim.debate_views}) >= 3:
                    evidence_bonus += 0.02
                penalty += min(0.24, 0.12 * len(claim.counter_evidence_ids))
                penalty += 0.07 * sum(
                    step["outcome"] in {"failed", "unresolved"}
                    for step in claim.falsification_steps
                )
            claim.judge_score = max(
                0.0,
                min(
                    0.99,
                    claim.base_confidence
                    + evidence_bonus
                    + independence_bonus
                    - penalty,
                ),
            )
            if not enforce:
                claim.status = "accepted"
            elif claim.judge_score >= acceptance_threshold and valid_evidence:
                claim.status = "accepted"
            elif claim.judge_score >= review_threshold and valid_evidence:
                claim.status = "review"
            elif abstention and (
                not valid_evidence
                or any(
                    step["outcome"] == "unresolved"
                    for step in claim.falsification_steps
                )
            ):
                claim.status = "abstained"
            else:
                claim.status = "rejected"

        valid_citations = sum(
            bool(claim.evidence_ids)
            and all(paper_id in kb.paper_by_id for paper_id in claim.evidence_ids)
            for claim in claims
        )
        admitted = sum(claim.status == "accepted" for claim in claims)
        blocked = sum(
            claim.status in {"rejected", "abstained"} for claim in claims
        )
        return {
            "module": self.name,
            "kind": "non_agent_quality_gate",
            "enforced": enforce,
            "status": "completed",
            "thresholds": {
                "acceptance": acceptance_threshold,
                "review": review_threshold,
            },
            "counts": {
                "assessed": len(claims),
                "accepted": admitted,
                "review": sum(claim.status == "review" for claim in claims),
                "rejected": sum(claim.status == "rejected" for claim in claims),
                "abstained": sum(claim.status == "abstained" for claim in claims),
                "blocked": blocked,
            },
            "scores": {
                "citation_validity": (
                    round(100 * valid_citations / len(claims), 1)
                    if claims
                    else 100.0
                ),
                "admission_rate": (
                    round(100 * admitted / len(claims), 1)
                    if claims
                    else 0.0
                ),
            },
            "criteria": [
                "来源 ID 有效",
                "证据数量与独立性",
                "结论强度不过度外推",
                "反证与可证伪检查",
                "低证据命题拒答或拦截",
            ],
        }

    def evaluate_result(
        self,
        report: dict[str, Any],
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        claims: list[Claim],
        resources: dict[str, Any],
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        accepted = [claim for claim in claims if claim.status == "accepted"]
        grounded = [
            claim
            for claim in accepted
            if claim.evidence_ids and claim.evidence_spans
        ]
        evidence_score = (
            100 * len(grounded) / len(accepted) if accepted else 0.0
        )
        profile_fit = float(diagnosis["resource_match_score"])
        covered_text = " ".join(resources.get("covered_concepts", [])).lower()
        coverage = (
            100
            * sum(
                concept.lower() in covered_text
                for concept in profile.required_concepts
            )
            / len(profile.required_concepts)
            if profile.required_concepts
            else 100.0
        )
        ratings = [
            float(value)
            for value in (questionnaire or {}).values()
            if isinstance(value, (int, float)) and 1 <= float(value) <= 5
        ]
        user_score = round(20 * mean(ratings), 1) if ratings else None
        if user_score is None:
            overall = (
                0.5 * evidence_score
                + 0.3 * profile_fit
                + 0.2 * coverage
            )
        else:
            overall = (
                0.35 * evidence_score
                + 0.25 * profile_fit
                + 0.20 * coverage
                + 0.20 * user_score
            )
        report["scores"].update(
            {
                "evidence_grounding": round(evidence_score, 1),
                "profile_fit": round(profile_fit, 1),
                "knowledge_coverage": round(coverage, 1),
                "user_feedback": user_score,
                "overall_quality": round(overall, 1),
            }
        )
        report["questionnaire"] = {
            "received": bool(ratings),
            "response_count": len(ratings),
            "scope": "demo_in_memory",
        }
        return report
