"""Archived pre-P0 experiment prototypes.

These classes and feature presets belonged to the former six-agent/feature-flag
experiment branch.  They are retained only so historical reports remain
auditable.  The supported runtime is :class:`yanhai.ScholarlyTraceOrchestrator`,
whose decision trace contains exactly three roles: proposer, critic, and judge.

Nothing in ``src/yanhai`` imports this module.  Do not use it for new results.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from time import perf_counter_ns
from typing import Any, Iterator

from ..knowledge import KnowledgeBase
from ..models import Claim, LearnerProfile, Paper


ARCHIVE_STATUS = "unsupported_historical_reference"


@dataclass(slots=True, frozen=True)
class FeatureFlags:
    critic: bool = True
    judge: bool = True
    calibrated_judge: bool = True
    sentence_provenance: bool = False
    diverse_debate: bool = False
    sequential_falsification: bool = False
    hypothesis_tournament: bool = False
    knowledge_tracing: bool = False
    temporal_analysis: bool = False
    information_gain_retrieval: bool = False
    abstention: bool = False
    performance_probes: bool = True

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class SystemConfig:
    name: str
    label: str
    description: str
    flags: FeatureFlags
    retrieval_limit: int = 8
    acceptance_threshold: float = 0.78
    review_threshold: float = 0.58
    max_falsification_rounds: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "flags": self.flags.to_dict(),
            "retrieval_limit": self.retrieval_limit,
            "acceptance_threshold": self.acceptance_threshold,
            "review_threshold": self.review_threshold,
            "max_falsification_rounds": self.max_falsification_rounds,
        }


LEGACY = SystemConfig(
    name="legacy",
    label="归档：基础六智能体",
    description="P0 前的诊断、检索、提出、批判、裁判与资源生成实验闭环。",
    flags=FeatureFlags(),
)

FULL = SystemConfig(
    name="full",
    label="归档：扩展创新链路",
    description="P0 前的句级溯源、辩论、反证、动态学情和假设锦标赛。",
    flags=FeatureFlags(
        sentence_provenance=True,
        diverse_debate=True,
        sequential_falsification=True,
        hypothesis_tournament=True,
        knowledge_tracing=True,
        temporal_analysis=True,
        information_gain_retrieval=True,
        abstention=True,
    ),
    retrieval_limit=6,
)


def _ablation(name: str, label: str, flag: str) -> SystemConfig:
    return replace(
        FULL,
        name=name,
        label=label,
        description=f"归档单因素开关：关闭 {flag}。",
        flags=replace(FULL.flags, **{flag: False}),
    )


ARCHIVED_PRESETS: dict[str, SystemConfig] = {
    "legacy": LEGACY,
    "full": FULL,
    "no_critic": _ablation("no_critic", "归档：无批判者", "critic"),
    "no_judge": _ablation("no_judge", "归档：无裁判", "judge"),
    "no_provenance": _ablation(
        "no_provenance", "归档：无句级溯源", "sentence_provenance"
    ),
    "no_debate": _ablation("no_debate", "归档：无多视角辩论", "diverse_debate"),
    "no_falsification": _ablation(
        "no_falsification", "归档：无序贯反证", "sequential_falsification"
    ),
    "no_tournament": _ablation(
        "no_tournament", "归档：无假设锦标赛", "hypothesis_tournament"
    ),
    "no_knowledge_tracing": _ablation(
        "no_knowledge_tracing", "归档：无动态学情", "knowledge_tracing"
    ),
}


class DiverseDebateAgent:
    name = "归档：多视角辩论 Agent"

    def debate(self, claims: list[Claim], kb: KnowledgeBase) -> list[Claim]:
        for claim in claims:
            valid = [
                paper_id
                for paper_id in claim.evidence_ids
                if paper_id in kb.paper_by_id
            ]
            views = [
                {
                    "perspective": "证据审计员",
                    "stance": "support" if valid else "challenge",
                    "finding": f"定位到 {len(valid)} 个有效来源。",
                },
                {
                    "perspective": "方法论怀疑者",
                    "stance": "challenge" if len(valid) < 2 else "support",
                    "finding": (
                        "单来源不足以排除方法偏差。"
                        if len(valid) < 2
                        else "已具备交叉来源，但仍需真实任务复验。"
                    ),
                },
                {
                    "perspective": "外部有效性审查员",
                    "stance": "challenge",
                    "finding": "论文切片只能支持条件性结论，不能外推为普遍保证。",
                },
            ]
            claim.debate_views.extend(views)
            if len(valid) < 2 and "多视角复核：交叉来源不足。" not in claim.criticisms:
                claim.criticisms.append("多视角复核：交叉来源不足。")
        return claims


class SequentialFalsificationAgent:
    name = "归档：序贯反证 Agent"

    def falsify(
        self,
        claims: list[Claim],
        kb: KnowledgeBase,
        max_rounds: int = 2,
    ) -> list[Claim]:
        for claim in claims:
            valid = [
                paper_id
                for paper_id in claim.evidence_ids
                if paper_id in kb.paper_by_id
            ]
            tests = [
                {
                    "round": 1,
                    "test": "若命题成立，应能定位至少一个支持句及其论文。",
                    "support_ids": valid,
                    "counter_ids": list(claim.counter_evidence_ids),
                    "outcome": "passed" if claim.evidence_spans and valid else "unresolved",
                },
                {
                    "round": 2,
                    "test": "若结论可推广，不应依赖绝对化措辞或未处理反证。",
                    "support_ids": valid,
                    "counter_ids": list(claim.counter_evidence_ids),
                    "outcome": (
                        "failed"
                        if claim.relation in {"guarantees", "proves"}
                        or claim.counter_evidence_ids
                        else "passed"
                    ),
                },
            ]
            claim.falsification_steps.extend(tests[: max(1, max_rounds)])
            if any(step["outcome"] == "failed" for step in claim.falsification_steps):
                claim.criticisms.append("序贯反证发现未通过的可证伪检查。")
        return claims


class KnowledgeTracingAgent:
    name = "归档：动态学情追踪 Agent"

    def trace(
        self,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        feedback: str | None = None,
    ) -> dict[str, Any]:
        delta = {"too_hard": -0.04, "suitable": 0.03, "too_easy": 0.05}.get(
            feedback, 0.0
        )
        concepts = []
        for topic, score in sorted(profile.knowledge_scores.items()):
            prior = score / 100
            posterior = max(0.01, min(0.99, prior + delta))
            concepts.append(
                {
                    "concept": topic,
                    "prior_mastery": round(prior, 3),
                    "posterior_mastery": round(posterior, 3),
                    "uncertainty": round(1 - abs(posterior - 0.5) * 2, 3),
                    "evidence": feedback or "profile_prior",
                }
            )
        weakest = min(concepts, key=lambda item: item["posterior_mastery"])
        return {
            "model": "archived deterministic Bayesian-style mock tracer",
            "concepts": concepts,
            "next_focus": weakest["concept"],
            "target_difficulty": diagnosis["target_difficulty"],
            "warning": "归档算法，不属于当前三智能体验收协议。",
        }


class TemporalDiscoveryAgent:
    name = "归档：时序争议发现 Agent"

    def analyse(
        self,
        papers: list[Paper],
        claims: list[Claim],
    ) -> dict[str, Any]:
        timeline = [
            {
                "year": paper.year,
                "paper_id": paper.paper_id,
                "milestone": paper.summary,
            }
            for paper in sorted(papers, key=lambda item: (item.year, item.paper_id))
        ]
        target_counts = Counter(claim.target for claim in claims if claim.evidence_ids)
        controversies = [
            {
                "topic": claim.target,
                "reason": (
                    "存在反向证据，需人工复核。"
                    if claim.counter_evidence_ids
                    else "仅有单一来源，跨场景有效性仍不确定。"
                ),
                "claim_id": claim.claim_id,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in claims
            if claim.counter_evidence_ids or len(claim.evidence_ids) == 1
        ]
        gaps = [
            {
                "topic": claim.target,
                "gap_type": (
                    "low_corroboration"
                    if len(claim.evidence_ids) == 1
                    else "cross_domain_validation"
                ),
                "priority": round(
                    min(0.99, 0.45 + 0.15 / max(1, target_counts[claim.target])), 3
                ),
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in claims
            if claim.status in {"accepted", "review"}
        ]
        gaps.sort(key=lambda item: item["priority"], reverse=True)
        return {
            "timeline": timeline,
            "controversies": controversies,
            "research_gaps": gaps[:5],
            "method": "归档拓扑启发式分析。",
        }


class HypothesisTournamentAgent:
    name = "归档：蓝海假设锦标赛 Agent"

    def rank(
        self,
        discovery: dict[str, Any],
        claims: list[Claim],
    ) -> list[dict[str, Any]]:
        accepted = [claim for claim in claims if claim.status == "accepted"]
        evidence_ids = sorted(
            {paper_id for claim in accepted for paper_id in claim.evidence_ids}
        )
        gap_topic = (
            discovery.get("research_gaps", [{}])[0].get("topic", "科研发现质量")
            if discovery.get("research_gaps")
            else "科研发现质量"
        )
        candidates = [
            {
                "hypothesis": f"将序贯反证失败率编码为动态图谱边权，可能改善“{gap_topic}”候选的排序。",
                "novelty": 0.86,
                "evidence_strength": min(0.92, 0.52 + 0.05 * len(evidence_ids)),
                "testability": 0.93,
                "uncertainty_value": 0.81,
            },
            {
                "hypothesis": "按学习者概念不确定度调节检索信息增益，可能提高跨学科证据覆盖。",
                "novelty": 0.79,
                "evidence_strength": min(0.88, 0.48 + 0.04 * len(evidence_ids)),
                "testability": 0.88,
                "uncertainty_value": 0.76,
            },
            {
                "hypothesis": "由角色多样性而非智能体数量决定辩论收益，可能降低无效讨论成本。",
                "novelty": 0.75,
                "evidence_strength": min(0.86, 0.5 + 0.04 * len(evidence_ids)),
                "testability": 0.91,
                "uncertainty_value": 0.73,
            },
        ]
        for index, candidate in enumerate(candidates, start=1):
            score = (
                0.30 * candidate["novelty"]
                + 0.25 * candidate["evidence_strength"]
                + 0.30 * candidate["testability"]
                + 0.15 * candidate["uncertainty_value"]
            )
            candidate["candidate_id"] = f"H{index:02d}"
            candidate["score"] = round(score, 3)
            candidate["evidence_ids"] = evidence_ids[:3]
            candidate["status"] = "hypothesis_not_fact"
        candidates.sort(key=lambda item: item["score"], reverse=True)
        for rank, candidate in enumerate(candidates, start=1):
            candidate["rank"] = rank
            candidate["pairwise_wins"] = len(candidates) - rank
        return candidates


class PerformanceProbe:
    """Archived probe used by the former preset-driven pipeline."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._started_ns = perf_counter_ns()
        self._stage_ms: dict[str, float] = defaultdict(float)
        self._stage_calls: dict[str, int] = defaultdict(int)
        self._counters: dict[str, int | float] = {}
        self._notes: list[str] = []

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        started_ns = perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter_ns() - started_ns) / 1_000_000
            self._stage_ms[stage] += elapsed_ms
            self._stage_calls[stage] += 1

    def set_counter(self, name: str, value: int | float) -> None:
        if self.enabled:
            self._counters[name] = value

    def increment(self, name: str, amount: int | float = 1) -> None:
        if self.enabled:
            self._counters[name] = self._counters.get(name, 0) + amount

    def note(self, message: str) -> None:
        if self.enabled and message not in self._notes:
            self._notes.append(message)

    def duration(self, stage: str) -> float:
        return round(self._stage_ms.get(stage, 0.0), 3)

    def snapshot(self) -> dict[str, Any]:
        total_ms = (perf_counter_ns() - self._started_ns) / 1_000_000
        measured_ms = sum(self._stage_ms.values())
        return {
            "clock": "time.perf_counter_ns",
            "total_ms": round(total_ms, 3) if self.enabled else None,
            "measured_stage_ms": round(measured_ms, 3) if self.enabled else None,
            "stages": [
                {
                    "name": name,
                    "duration_ms": round(duration, 3),
                    "calls": self._stage_calls[name],
                }
                for name, duration in self._stage_ms.items()
            ],
            "counters": dict(self._counters),
            "notes": list(self._notes),
            "scope": "归档探针；不属于当前三智能体运行时。",
        }
