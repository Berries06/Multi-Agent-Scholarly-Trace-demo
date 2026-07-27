from __future__ import annotations

from statistics import mean
from typing import Any

from .orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator


def evaluate_orchestrator(orchestrator: ScholarlyTraceOrchestrator) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for profile_id in orchestrator.profiles:
        for adjustment in (-1, 0, 1):
            result = orchestrator.run(profile_id, DEFAULT_QUERY, adjustment)
            accepted = [
                claim for claim in result["claims"] if claim["status"] == "accepted"
            ]
            evidence_complete = all(claim["evidence_ids"] for claim in accepted)
            trace_roles = {item["role"] for item in result["agent_trace"]}
            cases.append(
                {
                    "profile_id": profile_id,
                    "difficulty_adjustment": adjustment,
                    "hallucination_proxy_rate": result["metrics"][
                        "hallucination_proxy_rate"
                    ],
                    "adaptation_accuracy": result["metrics"]["adaptation_accuracy"],
                    "knowledge_coverage_rate": result["metrics"][
                        "knowledge_coverage_rate"
                    ],
                    "evidence_complete": evidence_complete,
                    "trace_complete": trace_roles
                    == {
                        "学情诊断与学习规划",
                        "证据检索与知识图谱构建",
                        "个性化教学与反馈",
                    },
                }
            )
    aggregate = {
        "hallucination_proxy_rate": round(
            mean(case["hallucination_proxy_rate"] for case in cases), 2
        ),
        "adaptation_accuracy": round(
            mean(case["adaptation_accuracy"] for case in cases), 2
        ),
        "knowledge_coverage_rate": round(
            mean(case["knowledge_coverage_rate"] for case in cases), 2
        ),
        "evidence_completeness": round(
            100 * mean(case["evidence_complete"] for case in cases), 2
        ),
        "trace_completeness": round(
            100 * mean(case["trace_complete"] for case in cases), 2
        ),
    }
    thresholds = {
        "hallucination_proxy_under_5": aggregate["hallucination_proxy_rate"] < 5,
        "adaptation_at_least_85": aggregate["adaptation_accuracy"] >= 85,
        "coverage_at_least_90": aggregate["knowledge_coverage_rate"] >= 90,
    }
    return {
        "case_count": len(cases),
        "case_scope": "3 组合成画像 × 3 个难度反馈，仅用于工程回归。",
        "aggregate": aggregate,
        "thresholds": thresholds,
        "cases": cases,
        "warning": "不能替代 50 组以上专家标注样本和正式盲审。",
    }
