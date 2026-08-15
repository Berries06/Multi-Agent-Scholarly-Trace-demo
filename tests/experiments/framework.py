from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from time import perf_counter
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from yanhai import ScholarlyTraceOrchestrator  # noqa: E402


DATA_PATH = Path(__file__).resolve().parent / "data" / "mock_benchmark.jsonl"
DECISION_BENCHMARK_PATH = PROJECT_ROOT / "data" / "evaluation" / "decision_benchmark.json"
SUPPORTED_MODES = {"decision_ablation", "orchestrator"}
SUPPORTED_EVALUATION_TYPES = {
    "real_gt",
    "synthetic_proxy",
    "self_supervised_proxy",
    "simulation_only",
    "human_eval",
}
DECISION_VARIANTS = {
    "rule_program",
    "single_pass",
    "homogeneous_vote",
    "evidence_triad",
}
CURRENT_PIPELINE = "three_agent_pipeline"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_metadata() -> dict[str, Any]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return {"available": False, "head": None, "dirty": None}
    return {"available": True, "head": head, "dirty": dirty}


def _run_provenance(
    config_path: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_paths = [
        Path(__file__).resolve(),
        SRC_ROOT / "yanhai" / "ablation.py",
        SRC_ROOT / "yanhai" / "agents.py",
        SRC_ROOT / "yanhai" / "orchestrator.py",
    ]
    input_paths = [config_path.resolve()]
    if config["mode"] == "decision_ablation":
        input_paths.append(DECISION_BENCHMARK_PATH)
    else:
        input_paths.append(DATA_PATH)
    return {
        "git": _git_metadata(),
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "timing": {
            "clock": "time.perf_counter",
            "warmup_runs": 0,
            "scope": (
                "decision_ablation_batch"
                if config["mode"] == "decision_ablation"
                else "core_pipeline_excluding_decision_ablation"
            ),
        },
        "source_sha256": {
            str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"): _sha256(path)
            for path in source_paths
        },
        "input_sha256": {
            str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"): _sha256(path)
            for path in input_paths
        },
    }


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


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
        if item.get("synthetic") is not True:
            raise ValueError(
                f"{path}:{line_number} must explicitly set synthetic=true"
            )
        cases.append(item)
    return cases


def load_experiment_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    missing = {
        "slug",
        "title",
        "purpose",
        "mode",
        "primary_metrics",
        "evaluation_type",
        "claim_ceiling",
    } - config.keys()
    if missing:
        raise ValueError(f"{path} missing fields: {sorted(missing)}")
    mode = str(config["mode"])
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"{path} has unsupported mode: {mode}")
    evaluation_type = str(config["evaluation_type"])
    if evaluation_type not in SUPPORTED_EVALUATION_TYPES:
        raise ValueError(
            f"{path} has unsupported evaluation_type: {evaluation_type}"
        )
    if "presets" in config:
        raise ValueError(
            f"{path} still uses archived six-agent presets; use variants instead"
        )
    repetitions = int(config.get("repetitions", 1))
    if repetitions < 1:
        raise ValueError(f"{path} repetitions must be positive")
    variants = list(config.get("variants", []))
    if mode == "decision_ablation":
        unknown = set(variants) - DECISION_VARIANTS
        if not variants or unknown:
            raise ValueError(
                f"{path} must select current Track-A variants; unknown={sorted(unknown)}"
            )
    elif variants not in ([], [CURRENT_PIPELINE]):
        raise ValueError(
            f"{path} orchestrator mode only supports {CURRENT_PIPELINE}"
        )
    multipliers = [int(value) for value in config.get("data_multipliers", [1])]
    if not multipliers or any(value < 1 for value in multipliers):
        raise ValueError(f"{path} data_multipliers must be positive")
    return config


def _term_coverage(result: dict[str, Any], expected_terms: list[str]) -> float:
    if not expected_terms:
        return 100.0
    corpus = " ".join(
        f"{claim['source']} {claim['relation']} {claim['target']}"
        for claim in result["claims"]
        if claim["status"] in {"accepted", "needs_review"}
    ).casefold()
    return round(
        100
        * sum(term.casefold() in corpus for term in expected_terms)
        / len(expected_terms),
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
    return bool(pressure and pressure["status"] != "accepted")


def _percent_true(values: Iterable[bool]) -> float:
    materialized = list(values)
    return round(100 * mean(materialized), 2) if materialized else 100.0


def _decision_rows(
    orchestrator: ScholarlyTraceOrchestrator,
    config: dict[str, Any],
    repetitions: int,
) -> list[dict[str, Any]]:
    selected_variants = set(config["variants"])
    selected_case_ids = set(config.get("case_ids", []))
    selected_error_types = set(config.get("error_types", []))
    rows: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        started = perf_counter()
        result = orchestrator.ablation.run()
        run_ms = round((perf_counter() - started) * 1000, 3)
        for variant in result["variants"]:
            variant_id = variant["variant_id"]
            if variant_id not in selected_variants:
                continue
            for case in variant["cases"]:
                if selected_case_ids and case["claim_id"] not in selected_case_ids:
                    continue
                if selected_error_types and case["error_type"] not in selected_error_types:
                    continue
                accepted = case["status"] == "accepted"
                evidence_ids = list(case["evidence_ids"])
                rows.append(
                    {
                        "experiment": config["slug"],
                        "mode": config["mode"],
                        "variant": variant_id,
                        "variant_label": variant["label"],
                        "case_id": case["claim_id"],
                        "error_type": case["error_type"],
                        "gold_supported": bool(case["gold_supported"]),
                        "status": case["status"],
                        "accepted": accepted,
                        "correct": bool(case["correct"]),
                        "evidence_id_count": len(evidence_ids),
                        "evidence_ids_valid": bool(evidence_ids)
                        and all(
                            orchestrator.kb.evidence_is_valid(item)
                            for item in evidence_ids
                        ),
                        "repetition": repetition,
                        "batch_run_ms": run_ms,
                        "evaluation_type": config["evaluation_type"],
                        "data_kind": config["evaluation_type"],
                        "claim_ceiling": config["claim_ceiling"],
                    }
                )
    if not rows:
        raise ValueError(f"{config['slug']} selected no Track-A cases")
    return rows


def _orchestrator_row(
    orchestrator: ScholarlyTraceOrchestrator,
    config: dict[str, Any],
    case: dict[str, Any],
    repetition: int,
    multiplier: int,
    feedback: str,
) -> dict[str, Any]:
    started = perf_counter()
    if feedback:
        result = orchestrator.run_with_feedback(
            case["profile_id"],
            feedback,
            case["query"],
            include_ablation=False,
        )
    else:
        result = orchestrator.run(
            case["profile_id"],
            case["query"],
            include_ablation=False,
        )
    total_ms = round((perf_counter() - started) * 1000, 3)
    claims = list(result["claims"])
    accepted = [claim for claim in claims if claim["status"] == "accepted"]
    evidence_id_coverage = _percent_true(
        bool(claim["evidence_ids"])
        and all(
            orchestrator.kb.evidence_is_valid(item)
            for item in claim["evidence_ids"]
        )
        for claim in accepted
    )
    sentence_provenance_coverage = _percent_true(
        bool(claim.get("evidence_spans")) for claim in accepted
    )
    trace_roles = {item["role"] for item in result["agent_trace"]}
    return {
        "experiment": config["slug"],
        "mode": config["mode"],
        "variant": CURRENT_PIPELINE,
        "case_id": case["case_id"],
        "profile_id": case["profile_id"],
        "feedback": feedback or "none",
        "repetition": repetition,
        "data_multiplier": multiplier,
        "knowledge_base_rows": len(orchestrator.kb.papers),
        "total_ms": total_ms,
        "accepted_claims": len(accepted),
        "needs_review_claims": sum(
            claim["status"] == "needs_review" for claim in claims
        ),
        "rejected_claims": sum(claim["status"] == "rejected" for claim in claims),
        "pressure_claim_blocked": _pressure_blocked(result),
        "expected_term_coverage": _term_coverage(
            result, list(case["expected_terms"])
        ),
        "evidence_id_coverage": evidence_id_coverage,
        "sentence_provenance_coverage": sentence_provenance_coverage,
        "hallucination_proxy_rate": result["metrics"]["hallucination_proxy_rate"],
        "adaptation_accuracy": result["metrics"]["adaptation_accuracy"],
        "knowledge_coverage_rate": result["metrics"]["knowledge_coverage_rate"],
        "target_difficulty": result["diagnosis"]["target_difficulty"],
        "core_agent_count": result["core_method"]["agent_count"],
        "trace_complete": trace_roles
        == {"关联提出", "反证与约束", "置信裁决"},
        "research_idea_count": len(result["graph_insights"]["research_ideas"]),
        "timing_scope": "core_pipeline_excluding_decision_ablation",
        "evaluation_type": config["evaluation_type"],
        "data_kind": config["evaluation_type"],
        "claim_ceiling": config["claim_ceiling"],
    }


def _orchestrator_rows(
    orchestrator: ScholarlyTraceOrchestrator,
    config: dict[str, Any],
    cases: list[dict[str, Any]],
    repetitions: int,
) -> list[dict[str, Any]]:
    selected_ids = set(config.get("case_ids", []))
    if selected_ids:
        known_ids = {case["case_id"] for case in cases}
        unknown = selected_ids - known_ids
        if unknown:
            raise ValueError(f"Unknown mock case ids: {sorted(unknown)}")
        cases = [case for case in cases if case["case_id"] in selected_ids]
    if not cases:
        raise ValueError("No benchmark cases selected.")
    multipliers = [int(value) for value in config.get("data_multipliers", [1])]
    feedbacks = list(config.get("feedbacks", [""]))
    original_papers = list(orchestrator.kb.papers)
    rows: list[dict[str, Any]] = []
    try:
        for multiplier in multipliers:
            orchestrator.kb.papers = original_papers * multiplier
            for case in cases:
                for feedback in feedbacks:
                    for repetition in range(1, repetitions + 1):
                        rows.append(
                            _orchestrator_row(
                                orchestrator,
                                config,
                                case,
                                repetition,
                                multiplier,
                                feedback,
                            )
                        )
    finally:
        orchestrator.kb.papers = original_papers
    return rows


def _aggregate_decision(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["variant"]].append(row)
    aggregates = []
    for variant, group in sorted(grouped.items()):
        accepted = [row for row in group if row["accepted"]]
        tp = sum(row["gold_supported"] for row in accepted)
        fp = len(accepted) - tp
        supported = sum(row["gold_supported"] for row in group)
        unsupported = len(group) - supported
        fn = supported - tp
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        aggregates.append(
            {
                "variant": variant,
                "case_runs": len(group),
                "accepted_count": len(accepted),
                "true_positive_count": tp,
                "false_positive_count": fp,
                "false_negative_count": fn,
                "accepted_precision": round(precision, 3),
                "gold_recall": round(recall, 3),
                "unsupported_acceptance_rate": round(
                    _safe_divide(fp, unsupported), 3
                ),
                "evidence_coverage": round(
                    _safe_divide(
                        sum(row["evidence_ids_valid"] for row in accepted),
                        len(accepted),
                    ),
                    3,
                ),
                "decision_accuracy": round(mean(row["correct"] for row in group), 3),
                "mean_batch_run_ms": round(
                    mean(row["batch_run_ms"] for row in group), 3
                ),
                "evaluation_type": config["evaluation_type"],
                "data_kind": config["evaluation_type"],
                "claim_ceiling": config["claim_ceiling"],
            }
        )
    return aggregates


def _aggregate_orchestrator(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["variant"], row["data_multiplier"], row["feedback"])].append(
            row
        )
    numeric_metrics = [
        "total_ms",
        "knowledge_base_rows",
        "accepted_claims",
        "needs_review_claims",
        "rejected_claims",
        "expected_term_coverage",
        "evidence_id_coverage",
        "sentence_provenance_coverage",
        "hallucination_proxy_rate",
        "adaptation_accuracy",
        "knowledge_coverage_rate",
        "target_difficulty",
        "research_idea_count",
    ]
    aggregates = []
    for (variant, multiplier, feedback), group in sorted(grouped.items()):
        timings = sorted(float(row["total_ms"]) for row in group)
        percentile_index = min(
            len(timings) - 1, max(0, round(0.95 * len(timings) + 0.5) - 1)
        )
        aggregate: dict[str, Any] = {
            "variant": variant,
            "data_multiplier": multiplier,
            "feedback": feedback,
            "case_runs": len(group),
            "pressure_block_rate": _percent_true(
                row["pressure_claim_blocked"] for row in group
            ),
            "trace_complete_rate": _percent_true(
                row["trace_complete"] for row in group
            ),
            "p95_total_ms": round(timings[percentile_index], 3),
            "std_total_ms": round(pstdev(timings), 3),
            "evaluation_type": config["evaluation_type"],
            "data_kind": config["evaluation_type"],
            "claim_ceiling": config["claim_ceiling"],
        }
        for metric in numeric_metrics:
            aggregate[f"mean_{metric}"] = round(
                mean(float(row[metric]) for row in group), 3
            )
        aggregate["mean_runs_per_second"] = round(
            1000 / aggregate["mean_total_ms"]
            if aggregate["mean_total_ms"] > 0
            else 0.0,
            2,
        )
        aggregates.append(aggregate)
    return aggregates


def aggregate_rows(
    config: dict[str, Any], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if config["mode"] == "decision_ablation":
        return _aggregate_decision(config, rows)
    return _aggregate_orchestrator(config, rows)


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
        f"- 当前协议：{config['mode']}",
        f"- 样本运行数：{len(rows)}",
        f"- 评估类型：{config['evaluation_type']}",
        f"- 主张上限：{config['claim_ceiling']}",
        "- 重复语义：确定性重放，不作为独立样本或随机种子。",
        f"- 主指标：{', '.join(config['primary_metrics'])}",
        "",
        "## 汇总结果",
        "",
        "```json",
        json.dumps(aggregates, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 完整性边界",
        "",
        "- Track A 的标签来自版本化压力集，只用于比较同一候选池上的决策机制。",
        "- orchestrator 模式使用合成画像与 mock 查询，只证明三智能体链路可重复运行。",
        "- 不得将重复运行次数当作独立样本数。",
        "- 替换真实数据后，必须补充双人标注、盲审一致性、置信区间和错误分析。",
        "",
        "## 文件说明",
        "",
        "- `raw_results.json`：逐次、逐案例结果。",
        "- `cases.csv`：可用表格软件打开的逐行指标。",
        "- `summary.json`：按当前变体、倍率和反馈汇总。",
        "- `run_config.json`：本次冻结配置、代码/输入哈希、Git 状态、运行环境与计时范围。",
    ]
    return "\n".join(lines) + "\n"


def verify_experiment_artifacts(output_dir: Path) -> None:
    config = json.loads(
        (output_dir / "run_config.json").read_text(encoding="utf-8")
    )
    rows = json.loads(
        (output_dir / "raw_results.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )
    expected_summary = aggregate_rows(config, rows)
    if summary != expected_summary:
        raise ValueError(f"{output_dir} summary does not match raw results")

    with (output_dir / "cases.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        csv_rows = list(csv.DictReader(handle))
    expected_csv_rows = [
        {key: str(value) for key, value in row.items()}
        for row in rows
    ]
    if csv_rows != expected_csv_rows:
        raise ValueError(f"{output_dir} CSV does not match raw results")

    expected_report = _report_markdown(config, rows, summary)
    actual_report = (output_dir / "REPORT.md").read_text(encoding="utf-8")
    if actual_report != expected_report:
        raise ValueError(f"{output_dir} report does not match summary")

    receipt_path = output_dir / "verification.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("status") != "passed":
            raise ValueError(f"{output_dir} verification receipt is not passed")
        for name, expected_hash in receipt.get("verified_sha256", {}).items():
            if _sha256(output_dir / name) != expected_hash:
                raise ValueError(
                    f"{output_dir} verification hash mismatch: {name}"
                )


def execute_experiment(
    config_path: Path,
    *,
    output_root: Path | None = None,
    repetitions_override: int | None = None,
) -> Path:
    config = load_experiment_config(config_path)
    repetitions = repetitions_override or int(config.get("repetitions", 1))
    if repetitions < 1:
        raise ValueError("repetitions_override must be positive")
    orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
    if config["mode"] == "decision_ablation":
        rows = _decision_rows(orchestrator, config, repetitions)
    else:
        rows = _orchestrator_rows(
            orchestrator,
            config,
            load_cases(),
            repetitions,
        )
    aggregates = aggregate_rows(config, rows)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    base = output_root or PROJECT_ROOT / "outputs" / "experiments"
    output_dir = base / config["slug"] / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)
    frozen_config = {
        **config,
        "effective_repetitions": repetitions,
        "data_kind": config["evaluation_type"],
        "repetition_semantics": "deterministic_replay_not_independent_sample",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": _run_provenance(config_path, config),
        "artifact_verifier": "tests.experiments.framework.verify_experiment_artifacts",
    }
    (output_dir / "run_config.json").write_text(
        json.dumps(frozen_config, ensure_ascii=False, indent=2), encoding="utf-8"
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
    verify_experiment_artifacts(output_dir)
    verified_names = [
        "run_config.json",
        "raw_results.json",
        "summary.json",
        "cases.csv",
        "REPORT.md",
    ]
    (output_dir / "verification.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "verifier": (
                    "tests.experiments.framework.verify_experiment_artifacts"
                ),
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "verified_sha256": {
                    name: _sha256(output_dir / name)
                    for name in verified_names
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    verify_experiment_artifacts(output_dir)
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
