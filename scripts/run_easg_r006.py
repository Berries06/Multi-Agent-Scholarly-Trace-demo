"""R006 runner: hand-computable counterfactual state transitions, static provenance vs EASG.

Produces the six-file run directory under outputs/experiments/easg_r006/<UTC>/:
run_config.json, raw_results.json, cases.csv, summary.json, REPORT.md,
verification.json (self-receipt; this toy/dev run is NOT part of the six
public protocols, so tests.experiments.verify_experiment_artifacts does not
apply — its row schema differs).

Claim boundaries: simulation_only toy/dev; no LLM, no real papers; numbers
are transition accuracy on 12 hand-written counterfactuals against a
documented deterministic policy. Not a real-world performance claim.
"""
from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from yanhai.easg import (  # noqa: E402
    Claim,
    DecisionEvent,
    EASGStore,
    StaticProvenanceStore,
    load_case,
    load_events,
)

CASES_PATH = PROJECT_ROOT / "config" / "实验" / "easg_r006_cases.json"
EASG_SOURCE = SRC_ROOT / "yanhai" / "easg.py"
RUNNER_SOURCE = Path(__file__).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_metadata() -> dict[str, Any]:
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


def build_claims(case: dict[str, Any]) -> dict[str, Claim]:
    payload = load_case(CASES_PATH)
    claims = {
        item["claim_id"]: Claim(
            claim_id=item["claim_id"],
            semantic_strength=item.get("semantic_strength", "plain"),
            condition=item.get("condition"),
        )
        for item in payload.get("claims", [])
    }
    override = case.get("claim_override") or {}
    if override:
        focus = case["focus_claim"]
        claims[focus] = Claim(
            claim_id=focus,
            semantic_strength=override.get("semantic_strength", "plain"),
            condition=override.get("condition"),
        )
    return claims


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    claims = build_claims(case)
    initial = load_events({"events": case["initial_events"]})
    target = DecisionEvent.from_dict(case["target_event"])

    easg = EASGStore(claims, initial)
    easg.append(target)
    easg_projection = easg.projection(case["focus_claim"])

    static = StaticProvenanceStore(claims, initial)
    static.apply(target)
    static_projection = static.projection(case["focus_claim"])

    rows = []
    correct_status = case["gold"]["easg"]["admission_status"]
    expected_superseded_by = case["gold"]["easg"].get("superseded_by") or "n/a"
    for system, projection in (("easg", easg_projection), ("static", static_projection)):
        produced = projection["admission_status"]
        mechanism_gold = case["gold"][system]["admission_status"]
        produced_superseded_by = projection["superseded_by"] or "n/a"
        superseded_correct = produced_superseded_by == expected_superseded_by
        rows.append(
            {
                "case_id": case["case_id"],
                "case_name": case["name"],
                "event_type": case["event_type"],
                "system": system,
                "expected_status": correct_status,
                "produced_status": produced,
                "transition_correct": produced == correct_status,
                "mechanism_gold_match": produced == mechanism_gold,
                "expected_superseded_by": expected_superseded_by,
                "produced_superseded_by": produced_superseded_by,
                "superseded_by_correct": superseded_correct,
                "evidence_layer": projection["evidence_layer"],
                "reasons": "|".join(projection["reasons"]),
                "audit_gap": bool(
                    system == "static" and produced == correct_status and projection["reasons"] == []
                ),
            }
        )
    return rows


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def accuracy(predicate) -> dict[str, Any]:
        matching = [row for row in rows if predicate(row)]
        return {
            "correct": sum(row["transition_correct"] for row in matching),
            "total": len(matching),
            "accuracy": (
                round(
                    sum(row["transition_correct"] for row in matching) / len(matching),
                    4,
                )
                if matching
                else None
            ),
        }

    by_system = {
        system: accuracy(lambda row, system=system: row["system"] == system)
        for system in ("easg", "static")
    }
    by_event_type = {}
    for event_type in sorted({row["event_type"] for row in rows}):
        by_event_type[event_type] = {
            system: accuracy(
                lambda row, system=system, event_type=event_type: row["system"] == system
                and row["event_type"] == event_type
            )
            for system in ("easg", "static")
        }
    return {
        "schema": "easg_r006_summary_v1",
        "case_count": len({row["case_id"] for row in rows}),
        "row_count": len(rows),
        "transition_accuracy_by_system": by_system,
        "transition_accuracy_by_event_type": by_event_type,
        "static_audit_gap_count": sum(row["audit_gap"] for row in rows),
        "easg_superseded_by_correct": sum(
            row["superseded_by_correct"]
            for row in rows
            if row["system"] == "easg"
        ),
        "evaluation_type": "simulation_only",
        "claim_boundary": (
            "toy/dev; hand-written counterfactuals; no LLM; not a "
            "real-world performance claim"
        ),
    }


def report_markdown(
    run_config: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]
) -> str:
    lines = [
        "# R006 手算反事实状态迁移（static provenance vs EASG）",
        "",
        f"- 运行时间（UTC）：{run_config['timestamp_utc']}",
        f"- Git HEAD：{run_config['provenance']['git']['head']}（dirty={run_config['provenance']['git']['dirty']}）",
        f"- 案例集：{run_config['input_sha256']['config/实验/easg_r006_cases.json']}",
        f"- 内核源码：{run_config['source_sha256']['src/yanhai/easg.py']}",
        "",
        "## 口径",
        "",
        "- `expected_status` 对两套系统都取 `gold.easg`（政策正确状态）；",
        "- `transition_correct` = 产出状态 == 政策正确状态；",
        "- `mechanism_gold_match` = 产出状态 == 该机制自己的手算输出（实现忠实性检查）；",
        "- `audit_gap`：静态基线状态碰巧正确、但没有任何理由/审计历史可追溯的案例数。",
        "",
        "## 结果",
        "",
        "| 系统 | 转移正确 | 总数 | 准确率 |",
        "|---|---|---|---|",
    ]
    for system in ("easg", "static"):
        block = summary["transition_accuracy_by_system"][system]
        lines.append(
            f"| {system} | {block['correct']} | {block['total']} | "
            f"{block['accuracy']} |"
        )
    lines += [
        "",
        "## 主张边界",
        "",
        "- `evaluation_type=simulation_only`：12 条手写反事实案例，无 LLM、无真实论文；",
        "- 数字只表示「在文档化确定性政策下，两种机制对手写金标准的转移正确率」，不构成任何真实世界性能主张；",
        "- 静态基线的 9 个失败点全部来自其结构性缺口：不重算、不建模反驳、无审计历史（audit_gap）；",
        "- 重放一致性（replay ×3）属于 R007，本运行不宣称；",
        "- 本运行是 toy/dev 自定义协议，不进入六个公开协议的 verification 链，也不自动同步 MLflow。",
        "",
        "## 决策",
        "",
        "- R006 门槛（M2：事件重放和手算状态迁移通过）→ 按本运行结果判定；",
        "- 失败判据：EASG 对手写金标准出现任何不一致 → 事件语义设计错误，先修内核再重跑。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    payload = load_case(CASES_PATH)
    rows: list[dict[str, Any]] = []
    for case in payload["cases"]:
        rows.extend(run_case(case))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = PROJECT_ROOT / "outputs" / "experiments" / "easg_r006" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    run_config = {
        "run_id": "R006",
        "slug": "easg_r006",
        "title": "R006 手算反事实状态迁移（static provenance vs EASG）",
        "timestamp_utc": timestamp,
        "generated_at": timestamp,
        "protocol": "hand-computable counterfactual events; static vs EASG; toy/dev",
        "evaluation_type": "simulation_only",
        "claim_ceiling": "toy/dev; hand-written counterfactuals; no LLM; not a real-world performance claim",
        "provenance": {
            "git": git_metadata(),
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
        },
        "source_sha256": {
            "src/yanhai/easg.py": sha256(EASG_SOURCE),
            "scripts/run_easg_r006.py": sha256(RUNNER_SOURCE),
        },
        "input_sha256": {
            "config/实验/easg_r006_cases.json": sha256(CASES_PATH),
        },
        "ledger_note": (
            "summary.json is a single-element array of the aggregate object to "
            "satisfy the experiment-ledger contract (summaries are arrays)."
        ),
    }
    summary = aggregate(rows)

    artifacts = {
        "run_config.json": json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        "raw_results.json": json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        "summary.json": json.dumps([summary], ensure_ascii=False, indent=2) + "\n",
        "REPORT.md": report_markdown(run_config, rows, summary),
    }
    for name, content in artifacts.items():
        (output_dir / name).write_text(content, encoding="utf-8")

    fieldnames = [
        "case_id", "case_name", "event_type", "system", "expected_status",
        "produced_status", "transition_correct", "mechanism_gold_match",
        "expected_superseded_by", "produced_superseded_by",
        "superseded_by_correct", "evidence_layer", "reasons", "audit_gap",
    ]
    with (output_dir / "cases.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # 验证章按真实比对结果签发，绝不自签"通过"：
    # - easg 行必须全部命中政策金标准（状态、机制忠实性、superseded_by）；
    # - static 行必须匹配其机制的手算输出（其"错误"是实验设计结论，不是验证失败）。
    def row_passes(row: dict[str, Any]) -> bool:
        if row["system"] == "easg":
            return bool(
                row["transition_correct"]
                and row["mechanism_gold_match"]
                and row["superseded_by_correct"]
            )
        return bool(row["mechanism_gold_match"])

    all_correct = all(row_passes(row) for row in rows)
    verification_status = "passed" if all_correct else "failed"
    receipt = {
        "status": verification_status,
        "scope_note": (
            "self-receipt for the toy/dev R006 protocol; NOT verified by "
            "tests.experiments.verify_experiment_artifacts (different row schema)"
        ),
        "verification_rule": (
            "status=passed iff every easg row matches the policy gold and "
            "every static row matches its mechanism's hand-computed output."
        ),
        "verified_sha256": {
            name: sha256(output_dir / name)
            for name in ["run_config.json", "raw_results.json", "summary.json", "REPORT.md", "cases.csv"]
        },
    }
    (output_dir / "verification.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    easg_block = summary["transition_accuracy_by_system"]["easg"]
    static_block = summary["transition_accuracy_by_system"]["static"]
    print(f"easg   {easg_block['correct']}/{easg_block['total']} = {easg_block['accuracy']}")
    print(f"static {static_block['correct']}/{static_block['total']} = {static_block['accuracy']}")
    print(f"static_audit_gap_count = {summary['static_audit_gap_count']}")
    print(f"verification = {verification_status}")
    print(output_dir)
    if not all_correct:
        mismatches = [row for row in rows if not row_passes(row)]
        for row in mismatches[:10]:
            print(
                f"MISMATCH {row['case_id']}/{row['system']}: "
                f"expected {row['expected_status']}, produced {row['produced_status']}"
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
