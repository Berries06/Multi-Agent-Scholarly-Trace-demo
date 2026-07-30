from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .agents import CriticAgent, JudgeAgent
from .knowledge import KnowledgeBase
from .models import Claim


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


class DecisionAblation:
    """Track-A comparison over a frozen candidate pool.

    This is intentionally a deterministic demo benchmark. It validates that the
    comparison and trace pipeline work; it is not a substitute for an LLM or
    expert-annotated public benchmark.
    """

    def __init__(self, project_root: Path, knowledge_base: KnowledgeBase) -> None:
        self.project_root = project_root
        self.kb = knowledge_base
        benchmark_path = project_root / "data" / "evaluation" / "decision_benchmark.json"
        self.benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
        self.critic = CriticAgent()
        self.judge = JudgeAgent()

    def run(self) -> dict[str, Any]:
        variants: list[tuple[str, str, Callable[[list[Claim]], list[Claim]]]] = [
            (
                "rule_program",
                "普通规则程序",
                self._rule_program,
            ),
            (
                "single_pass",
                "单次判定",
                self._single_pass,
            ),
            (
                "homogeneous_vote",
                "同质三路投票",
                self._homogeneous_vote,
            ),
            (
                "evidence_triad",
                "提出—批判—裁判",
                self._evidence_triad,
            ),
        ]
        results = []
        for variant_id, label, runner in variants:
            claims = self._claims()
            predicted = runner(claims)
            results.append(
                {
                    "variant_id": variant_id,
                    "label": label,
                    "metrics": self._metrics(predicted),
                    "cases": [self._case_result(item) for item in predicted],
                }
            )
        triad = next(
            item for item in results if item["variant_id"] == "evidence_triad"
        )
        strongest_baseline = max(
            (
                item
                for item in results
                if item["variant_id"] != "evidence_triad"
            ),
            key=lambda item: (
                item["metrics"]["accepted_precision"],
                item["metrics"]["gold_recall"],
            ),
        )
        return {
            "benchmark_id": self.benchmark["benchmark_id"],
            "domain": self.benchmark["domain"],
            "frozen_on": self.benchmark["frozen_on"],
            "scope": self.benchmark["scope"],
            "case_count": len(self.benchmark["cases"]),
            "variants": results,
            "comparison": {
                "strongest_baseline": strongest_baseline["variant_id"],
                "accepted_precision_gain_pp": round(
                    100
                    * (
                        triad["metrics"]["accepted_precision"]
                        - strongest_baseline["metrics"]["accepted_precision"]
                    ),
                    1,
                ),
                "unsupported_acceptance_reduction_pp": round(
                    100
                    * (
                        strongest_baseline["metrics"]["unsupported_acceptance_rate"]
                        - triad["metrics"]["unsupported_acceptance_rate"]
                    ),
                    1,
                ),
                "gold_recall_change_pp": round(
                    100
                    * (
                        triad["metrics"]["gold_recall"]
                        - strongest_baseline["metrics"]["gold_recall"]
                    ),
                    1,
                ),
            },
            "warning": (
                "结果来自 12 条人工整理、规则可见的小样本演示集，只证明工程机制按预期工作；"
                "提交论文前必须在冻结人工金标准和真实模型输出上重跑。"
            ),
        }

    def _claims(self) -> list[Claim]:
        return [
            Claim(
                claim_id=item["claim_id"],
                source=item["source"],
                relation=item["relation"],
                target=item["target"],
                relation_type=item["relation_type"],
                base_confidence=float(item["base_confidence"]),
                source_type=self.kb.entity_type_for_name(item["source"]),
                target_type=self.kb.entity_type_for_name(item["target"]),
                evidence_ids=list(item["evidence_ids"]),
                proposal_reason="冻结候选池中的统一输入。",
                model_route="frozen-track-a-candidate",
            )
            for item in self.benchmark["cases"]
        ]

    @staticmethod
    def _rule_program(claims: list[Claim]) -> list[Claim]:
        for claim in claims:
            claim.status = (
                "accepted" if claim.base_confidence >= 0.78 else "rejected"
            )
            claim.judge_score = claim.base_confidence
            claim.judge_reason = "只按候选置信度阈值 0.78 决策。"
        return claims

    def _single_pass(self, claims: list[Claim]) -> list[Claim]:
        for claim in claims:
            evidence_ok = any(
                self.kb.evidence_is_valid(item) for item in claim.evidence_ids
            )
            claim.status = (
                "accepted"
                if evidence_ok and claim.base_confidence >= 0.72
                else "rejected"
            )
            claim.judge_score = claim.base_confidence if evidence_ok else 0.0
            claim.judge_reason = "单次策略只检查证据 ID 是否存在，不做独立反证。"
        return claims

    def _homogeneous_vote(self, claims: list[Claim]) -> list[Claim]:
        thresholds = (0.70, 0.72, 0.74)
        for claim in claims:
            evidence_ok = any(
                self.kb.evidence_is_valid(item) for item in claim.evidence_ids
            )
            votes = [
                evidence_ok and claim.base_confidence >= threshold
                for threshold in thresholds
            ]
            claim.status = "accepted" if sum(votes) >= 2 else "rejected"
            claim.judge_score = sum(votes) / len(votes)
            claim.judge_reason = (
                f"三个同质策略投票 {sum(votes)}:3；它们共享证据检查盲点。"
            )
            claim.score_breakdown = {
                "vote_1": float(votes[0]),
                "vote_2": float(votes[1]),
                "vote_3": float(votes[2]),
            }
        return claims

    def _evidence_triad(self, claims: list[Claim]) -> list[Claim]:
        return self.judge.adjudicate(
            self.critic.critique(claims, self.kb),
            self.kb,
        )

    def _metrics(self, claims: list[Claim]) -> dict[str, Any]:
        gold = {
            item["claim_id"]: bool(item["gold_supported"])
            for item in self.benchmark["cases"]
        }
        accepted = [item for item in claims if item.status == "accepted"]
        tp = sum(gold[item.claim_id] for item in accepted)
        fp = len(accepted) - tp
        supported = sum(gold.values())
        unsupported = len(gold) - supported
        fn = supported - tp
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        evidence_complete = sum(
            bool(item.evidence_ids)
            and all(self.kb.evidence_is_valid(ref) for ref in item.evidence_ids)
            for item in accepted
        )
        paper_count = len(
            {
                self.kb.paper_id_for_evidence(ref)
                for item in accepted
                if gold[item.claim_id]
                for ref in item.evidence_ids
            }
        )
        return {
            "accepted_precision": round(precision, 3),
            "gold_recall": round(recall, 3),
            "f1": round(f1, 3),
            "unsupported_acceptance_rate": round(
                _safe_divide(fp, unsupported),
                3,
            ),
            "evidence_coverage": round(
                _safe_divide(evidence_complete, len(accepted)),
                3,
            ),
            "verified_triple_yield": round(
                _safe_divide(tp, paper_count),
                3,
            ),
            "accepted_count": len(accepted),
            "true_positive_count": tp,
            "false_positive_count": fp,
        }

    def _case_result(self, claim: Claim) -> dict[str, Any]:
        gold_case = next(
            item
            for item in self.benchmark["cases"]
            if item["claim_id"] == claim.claim_id
        )
        return {
            **deepcopy(claim.to_dict()),
            "gold_supported": gold_case["gold_supported"],
            "error_type": gold_case["error_type"],
            "correct": (
                (claim.status == "accepted")
                == bool(gold_case["gold_supported"])
            ),
        }

