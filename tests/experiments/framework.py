from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from yanhai import ScholarlyTraceOrchestrator  # noqa: E402


DATA_PATH = Path(__file__).resolve().parent / "data" / "mock_benchmark.jsonl"


def load_cases(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        item = json.loads(line)
        missing = {"case_id", "profile_id", "query", "expected_terms"} - item.keys()
        if missing:
            raise ValueError(
                f"{path}:{line_number} missing fields: {sorted(missing)}"
            )
        cases.append(item)
    return cases


def _term_coverage(result: dict[str, Any], expected_terms: list[str]) -> float:
    if not expected_terms:
        return 100.0
    corpus = " ".join(
        f"{claim['source']} {claim['relation']} {claim['target']}"
        for claim in result["claims"]
        if claim["status"] in {"accepted", "review"}
    ).lower()
    return round(
        100 * sum(term.lower() in corpus for term in expected_terms) / len(expected_terms),
        2,
    )


def _pressure_blocked(result: dict[str, Any]) -> bool:
    pressure = next(
        (
            claim
            for claim in result["claims"]
            if claim["relation"] == "guarantees"
        ),
        None,
    )
    return bool(pressure and pressure["status"] in {"rejected", "abstained"})


def result_row(
    experiment: str,
    preset: str,
    case: dict[str, Any],
    result: dict[str, Any],
    repetition: int,
    data_multiplier: int,
    feedback: str,
) -> dict[str, Any]:
    claims = result["claims"]
    with_criticisms = sum(bool(claim["criticisms"]) for claim in claims)
    knowledge_concepts = result["innovations"]["knowledge_state"].get(
        "concepts", []
    )
    mastery_delta = (
        mean(
            concept["posterior_mastery"] - concept["prior_mastery"]
            for concept in knowledge_concepts
        )
        if knowledge_concepts
        else 0.0
    )
    return {
        "experiment": experiment,
        "preset": preset,
        "case_id": case["case_id"],
        "profile_id": case["profile_id"],
        "feedback": feedback or "none",
        "repetition": repetition,
        "data_multiplier": data_multiplier,
        "knowledge_base_rows": result["performance"]["counters"][
            "papers_in_knowledge_base"
        ],
        "total_ms": result["performance"]["total_ms"],
        "accepted_claims": result["metrics"]["accepted_claims"],
        "review_claims": result["metrics"]["review_claims"],
        "rejected_claims": result["metrics"]["rejected_claims"],
        "abstained_claims": result["metrics"]["abstained_claims"],
        "pressure_claim_blocked": _pressure_blocked(result),
        "expected_term_coverage": _term_coverage(
            result, list(case["expected_terms"])
        ),
        "evidence_id_coverage": result["metrics"]["evidence_id_coverage"],
        "sentence_provenance_coverage": result["metrics"][
            "sentence_provenance_coverage"
        ],
        "hallucination_proxy_rate": result["metrics"][
            "hallucination_proxy_rate"
        ],
        "adaptation_accuracy": result["metrics"]["adaptation_accuracy"],
        "knowledge_coverage_rate": result["metrics"]["knowledge_coverage_rate"],
        "criticism_coverage": round(
            100 * with_criticisms / len(claims) if claims else 0.0, 2
        ),
        "falsification_rounds": result["innovations"]["falsification"]["rounds"],
        "falsification_failed": result["innovations"]["falsification"]["failed"],
        "debate_view_count": result["innovations"]["debate_view_count"],
        "hypothesis_count": len(result["innovations"]["hypotheses"]),
        "research_gap_count": len(
            result["innovations"]["discovery"].get("research_gaps", [])
        ),
        "knowledge_concept_count": len(knowledge_concepts),
        "mean_mastery_delta": round(mastery_delta, 4),
        "target_difficulty": result["diagnosis"]["target_difficulty"],
    }


def aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (row["preset"], row["data_multiplier"], row["feedback"])
        ].append(row)
    aggregates = []
    numeric_metrics = [
        "total_ms",
        "accepted_claims",
        "rejected_claims",
        "abstained_claims",
        "expected_term_coverage",
        "evidence_id_coverage",
        "sentence_provenance_coverage",
        "hallucination_proxy_rate",
        "adaptation_accuracy",
        "knowledge_coverage_rate",
        "criticism_coverage",
        "falsification_rounds",
        "debate_view_count",
        "hypothesis_count",
        "research_gap_count",
        "knowledge_concept_count",
        "mean_mastery_delta",
        "target_difficulty",
    ]
    for (preset, multiplier, feedback), group in sorted(grouped.items()):
        aggregate: dict[str, Any] = {
            "preset": preset,
            "data_multiplier": multiplier,
            "feedback": feedback,
            "case_runs": len(group),
            "pressure_block_rate": round(
                100 * mean(row["pressure_claim_blocked"] for row in group), 2
            ),
        }
        for metric in numeric_metrics:
            aggregate[f"mean_{metric}"] = round(
                mean(float(row[metric]) for row in group), 3
            )
        timings = sorted(float(row["total_ms"]) for row in group)
        percentile_index = min(
            len(timings) - 1, max(0, round(0.95 * len(timings) + 0.5) - 1)
        )
        aggregate["p95_total_ms"] = round(timings[percentile_index], 3)
        aggregate["std_total_ms"] = round(pstdev(timings), 3)
        aggregate["mean_runs_per_second"] = round(
            1000 / aggregate["mean_total_ms"]
            if aggregate["mean_total_ms"] > 0
            else 0.0,
            2,
        )
        aggregates.append(aggregate)
    return aggregates


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _report_markdown(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {config['title']}",
        "",
        f"- 目的：{config['purpose']}",
        f"- 样本运行数：{len(rows)}",
        f"- 数据性质：合成 mock，只证明实验管线可运行，不代表真实科研效果。",
        f"- 主指标：{', '.join(config['primary_metrics'])}",
        "",
        "## 汇总结果",
        "",
        "| 方案 | 数据倍率 | 反馈 | 运行数 | 压力命题拦截率 | 幻觉代理率 | 预期概念覆盖 | 句级溯源 | 平均 / P95 耗时(ms) |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in aggregates:
        lines.append(
            "| {preset} | {data_multiplier} | {feedback} | {case_runs} | "
            "{pressure_block_rate:.1f}% | {mean_hallucination_proxy_rate:.1f}% | "
            "{mean_expected_term_coverage:.1f}% | "
            "{mean_sentence_provenance_coverage:.1f}% | "
            "{mean_total_ms:.3f} / {p95_total_ms:.3f} |".format(
                **item
            )
        )
    lines.extend(
        [
            "",
            "## 自动评估",
            "",
            "- 该报告只陈述脚本直接计算的结果，不将 mock 指标写成论文结论。",
            "- 消融解释应比较同一批 case、同一环境下的方案差异。",
            "- 若耗时低于 1 ms，应增加重复次数后再报告，避免计时噪声。",
            "- 替换真实数据后，必须补充人工金标准、盲审一致性和显著性检验。",
            "",
            "## 文件说明",
            "",
            "- `raw_results.json`：每次运行的完整逐行结果。",
            "- `cases.csv`：可用 Excel 打开的逐行指标。",
            "- `summary.json`：按方案与数据倍率汇总。",
            "- `run_config.json`：本次运行的固定配置。",
        ]
    )
    return "\n".join(lines) + "\n"


def execute_experiment(
    config_path: Path,
    *,
    output_root: Path | None = None,
    repetitions_override: int | None = None,
) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cases = load_cases()
    selected_ids = set(config.get("case_ids", []))
    if selected_ids:
        cases = [case for case in cases if case["case_id"] in selected_ids]
    if not cases:
        raise ValueError("No benchmark cases selected.")

    repetitions = repetitions_override or int(config.get("repetitions", 1))
    multipliers = [int(value) for value in config.get("data_multipliers", [1])]
    feedbacks = list(config.get("feedbacks", [""]))
    orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
    original_papers = list(orchestrator.kb.papers)
    rows: list[dict[str, Any]] = []

    try:
        for multiplier in multipliers:
            orchestrator.kb.papers = original_papers * multiplier
            for preset in config["presets"]:
                for case in cases:
                    for feedback in feedbacks:
                        for repetition in range(1, repetitions + 1):
                            if feedback:
                                result = orchestrator.run_with_feedback(
                                    case["profile_id"],
                                    feedback,
                                    case["query"],
                                    config=preset,
                                )
                            else:
                                result = orchestrator.run(
                                    case["profile_id"],
                                    case["query"],
                                    config=preset,
                                )
                            rows.append(
                                result_row(
                                    config["slug"],
                                    preset,
                                    case,
                                    result,
                                    repetition,
                                    multiplier,
                                    feedback,
                                )
                            )
    finally:
        orchestrator.kb.papers = original_papers

    aggregates = aggregate_rows(rows)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    base = output_root or PROJECT_ROOT / "outputs" / "experiments"
    output_dir = base / config["slug"] / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "raw_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "summary.json").write_text(
        json.dumps(aggregates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(output_dir / "cases.csv", rows)
    (output_dir / "REPORT.md").write_text(
        _report_markdown(config, rows, aggregates), encoding="utf-8"
    )
    return output_dir


def cli(config_path: Path) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    output_dir = execute_experiment(
        config_path,
        output_root=args.output_root,
        repetitions_override=args.repetitions,
    )
    print(output_dir)
