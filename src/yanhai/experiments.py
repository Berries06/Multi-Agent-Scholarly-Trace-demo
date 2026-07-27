"""Controlled multi-agent ablation study runner and evidence-boundary evaluator."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable

from .models import LearnerProfile
from .orchestrator import ScholarlyTraceOrchestrator
from .providers import ProviderConfig
from .storage import AppRepository


@dataclass(slots=True, frozen=True)
class ExperimentVariant:
    key: str
    preset: str
    label: str
    removed_capability: str


EXPERIMENT_VARIANTS: tuple[ExperimentVariant, ...] = (
    ExperimentVariant("A", "no_critic", "消融 A：无批判者", "critic"),
    ExperimentVariant("B", "no_judge", "消融 B：无裁判", "judge"),
    ExperimentVariant(
        "C",
        "no_knowledge_tracing",
        "消融 C：无动态学情",
        "knowledge_tracing",
    ),
    ExperimentVariant("FULL", "full", "满血版", "none"),
)


class EvidenceBoundaryEvaluator:
    """Local, reproducible evaluator used before a vendor evaluator is selected.

    This is deliberately conservative: it only calls a claim unsupported when
    it is accepted/reviewed but points outside the frozen paper snapshot. It
    does not pretend lexical novelty is automatically a hallucination.
    """

    name = "local_evidence_boundary"
    version = "1.0"

    def evaluate(self, result: dict[str, Any]) -> dict[str, Any]:
        valid_ids = {
            str(paper.get("paper_id"))
            for paper in result.get("papers", [])
            if paper.get("paper_id")
        }
        claims = [
            claim
            for claim in result.get("claims", [])
            if isinstance(claim, dict)
        ]
        factual = [
            claim
            for claim in claims
            if claim.get("status") in {"accepted", "review"}
        ]
        unsupported: list[str] = []
        partially_supported: list[str] = []
        for claim in factual:
            citations = {
                str(item)
                for item in claim.get("evidence_ids", [])
                if str(item)
            }
            valid_citations = citations & valid_ids
            if not valid_citations:
                unsupported.append(str(claim.get("claim_id", "")))
            elif citations - valid_ids:
                partially_supported.append(str(claim.get("claim_id", "")))

        answer_citations = {
            str(citation)
            for section in result.get("answer_sections", [])
            if isinstance(section, dict)
            for citation in section.get("citations", [])
        }
        invalid_answer_citations = sorted(answer_citations - valid_ids)
        blue_ocean = result.get("resources", {}).get("blue_ocean", {})
        marked_hypotheses = int(bool(blue_ocean.get("hypothesis")))
        factual_count = len(factual)
        unsupported_count = len(unsupported)
        return {
            "claim_count": len(claims),
            "factual_claim_count": factual_count,
            "supported_factual_claim_count": factual_count - unsupported_count,
            "unsupported_factual_claim_count": unsupported_count,
            "partially_supported_claim_count": len(partially_supported),
            "outside_evidence_inference_count": unsupported_count,
            "marked_hypothesis_count": marked_hypotheses,
            "invalid_answer_citation_count": len(invalid_answer_citations),
            "evidence_support_rate": round(
                (factual_count - unsupported_count) / factual_count
                if factual_count
                else 1.0,
                4,
            ),
            "hallucination_proxy_rate": round(
                unsupported_count / factual_count if factual_count else 0.0,
                4,
            ),
            "unsupported_claim_ids": unsupported,
            "partially_supported_claim_ids": partially_supported,
            "invalid_answer_citations": invalid_answer_citations,
            "scope": (
                "本地证据边界代理指标；仅检查冻结论文快照与引用，不替代外部检测商"
                "或人工事实核验。"
            ),
        }


class ExperimentRunner:
    """Generate four controlled answers, persist all, and reveal one at random."""

    def __init__(
        self,
        orchestrator: ScholarlyTraceOrchestrator,
        repository: AppRepository,
        *,
        evaluator: EvidenceBoundaryEvaluator | None = None,
        variant_selector: Callable[[tuple[ExperimentVariant, ...]], ExperimentVariant]
        | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.repository = repository
        self.evaluator = evaluator or EvidenceBoundaryEvaluator()
        self.variant_selector = variant_selector or secrets.choice

    def run(
        self,
        *,
        user_id: str,
        profile: LearnerProfile,
        query: str,
        provider_config: ProviderConfig,
    ) -> dict[str, Any]:
        if provider_config.provider != "mock":
            raise ValueError(
                "本地消融采集 MVP 暂只允许离线 Mock。实时模型需要先完成共享证据快照下的"
                "提示词级消融，避免四次独立检索污染实验。"
            )
        if not 3 <= len(query.strip()) <= 4000:
            raise ValueError("研究问题长度必须介于 3 到 4000 个字符。")

        generated: dict[str, tuple[ExperimentVariant, dict[str, Any], float]] = {}
        for variant in EXPERIMENT_VARIANTS:
            started = time.perf_counter()
            result = self.orchestrator.run_with_provider(
                profile.profile_id,
                query.strip(),
                provider_config,
                config=variant.preset,
                profile_override=profile,
            )
            duration_ms = (time.perf_counter() - started) * 1000
            generated[variant.key] = (variant, result, duration_ms)

        paper_orders = {
            tuple(
                str(paper.get("paper_id"))
                for paper in result.get("papers", [])
            )
            for _, result, _ in generated.values()
        }
        if len(paper_orders) != 1:
            raise RuntimeError("消融版本没有使用同一个冻结论文集合，已停止记录。")

        session = self.repository.begin_research_session(
            user_id=user_id,
            query=query.strip(),
            profile=profile,
            provider=provider_config.public_dict(),
            experiment_mode=True,
        )
        full_result = generated["FULL"][1]
        snapshot = self.repository.save_evidence_snapshot(
            session["research_session_id"],
            query=query.strip(),
            search_queries=[],
            papers=full_result.get("papers", []),
        )
        displayed = self.variant_selector(EXPERIMENT_VARIANTS)
        displayed_variant_id = ""
        for key, (variant, result, duration_ms) in generated.items():
            shown = key == displayed.key
            variant_id = self.repository.save_answer_variant(
                session["research_session_id"],
                variant_key=key,
                preset=variant.preset,
                result=result,
                shown_to_user=shown,
                duration_ms=duration_ms,
            )
            metrics = self.evaluator.evaluate(result)
            self.repository.save_hallucination_evaluation(
                variant_id,
                evaluator=self.evaluator.name,
                evaluator_version=self.evaluator.version,
                metrics=metrics,
            )
            if shown:
                displayed_variant_id = variant_id
        self.repository.set_displayed_variant(
            session["research_session_id"],
            displayed.key,
        )

        visible_result = generated[displayed.key][1]
        visible_result["research_record"] = {
            **session,
            "evidence_snapshot": snapshot,
            "variant_id": displayed_variant_id,
        }
        visible_result["experiment"] = {
            "research_session_id": session["research_session_id"],
            "displayed_variant": displayed.key,
            "displayed_label": displayed.label,
            "variant_count": len(EXPERIMENT_VARIANTS),
            "all_variants_persisted": True,
            "shared_evidence_snapshot": True,
            "evaluation_stored": True,
            "survey_required": True,
        }
        return visible_result
