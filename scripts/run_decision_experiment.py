"""对比实验：24 条冻结压力命题 × 决策机制组合（规则 / LLM 批判者 / LLM 裁判）。

用法：
  python scripts/run_decision_experiment.py --models "deepseek:deepseek-chat,zhipu:glm-4-flash"
  省略 --models 时只跑规则基线（离线自检用，不产生费用）。

组合矩阵：
  - baseline：规则批判者 + 规则裁判（对照）
  - 对每个模型 M：LLM 批判者(M) + LLM 裁判(M)（同模型三件套）
  - 模型数 ≤3 时：两两异质组合（批判者 A + 裁判 B）
缺 Key 的组合会被跳过并注明（实验里不允许静默回退，否则结果不可比）。

产物（outputs/experiments/decision-matrix-<时间戳>/）：
  - summary.json：各组合指标 + Wilson 95% 区间 + token/时延统计
  - cases.csv：逐组合逐案例结果
  - REPORT.md：可读报告
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.ablation import DecisionAblation  # noqa: E402
from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.llm_decision import LLMCritic, LLMJudge  # noqa: E402
from yanhai.models import Claim  # noqa: E402
from yanhai.providers import ProviderError, create_provider, load_config_from_env  # noqa: E402

Runner = Callable[[list[Claim]], tuple[list[Claim], dict[str, Any]]]

CASE_REQUIRED = {
    "claim_id",
    "source",
    "relation",
    "target",
    "relation_type",
    "base_confidence",
    "evidence_ids",
    "gold_supported",
}


def load_benchmark(cases_path: str) -> dict[str, Any]:
    """Load the default frozen pool or a custom case set, validating its shape."""
    if not cases_path:
        path = PROJECT_ROOT / "data" / "evaluation" / "decision_benchmark.json"
    else:
        path = Path(cases_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise SystemExit(f"案例集不存在：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit(f"案例集 {path} 缺少非空 cases 数组。")
    for index, item in enumerate(cases, 1):
        if not isinstance(item, dict):
            raise SystemExit(f"第 {index} 条案例必须是对象。")
        missing = sorted(CASE_REQUIRED - set(item.keys()))
        if missing:
            raise SystemExit(f"第 {index} 条案例缺少字段：{', '.join(missing)}")
        if not isinstance(item["evidence_ids"], list):
            raise SystemExit(f"第 {index} 条案例 evidence_ids 必须是数组。")
        if not isinstance(item["gold_supported"], bool):
            raise SystemExit(f"第 {index} 条案例 gold_supported 必须是 true/false。")
    if "benchmark_id" not in payload:
        payload["benchmark_id"] = path.stem
    return payload


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_models(spec: str) -> list[tuple[str, str]]:
    models: list[tuple[str, str]] = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise SystemExit(
                f"模型写法应为 provider:model，例如 deepseek:deepseek-chat；收到 {item!r}"
            )
        provider, model = item.split(":", 1)
        models.append((provider.strip(), model.strip()))
    return models


def make_llm_runner(
    kb: KnowledgeBase,
    critic_provider: str,
    critic_model: str,
    judge_provider: str,
    judge_model: str,
) -> Runner:
    def runner(claims: list[Claim]) -> tuple[list[Claim], dict[str, Any]]:
        critic_cfg = load_config_from_env(critic_provider, critic_model)
        judge_cfg = load_config_from_env(judge_provider, judge_model)
        critic = LLMCritic(
            create_provider(critic_cfg), fallback_to_rules=False
        )
        judge = LLMJudge(create_provider(judge_cfg), fallback_to_rules=False)
        claims = critic.critique(claims, kb)
        claims = judge.adjudicate(claims, kb)
        return claims, {
            "critic": critic.stats.snapshot(),
            "judge": judge.stats.snapshot(),
        }

    return runner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--models",
        default="",
        help="逗号分隔的 provider:model 列表；缺 Key 的组合会跳过。",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="最多跑多少条案例；0 表示全量（默认）。仅用于快速冒烟。",
    )
    parser.add_argument(
        "--cases",
        default="",
        help="可选：自定义案例集 JSON 路径（不传则用 24 条冻结压力命题）。字段与扩充方法见 docs/协作与运维/测试案例集扩充指南.md",
    )
    parser.add_argument(
        "--domain",
        default="",
        help="案例集所属领域 ID；留空=默认领域（与 --cases 对应的知识库一致）。",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    models = parse_models(args.models)

    kb = KnowledgeBase(
        PROJECT_ROOT / "data" / "knowledge",
        args.domain or None,
    )
    benchmark = load_benchmark(args.cases)
    abl = DecisionAblation(PROJECT_ROOT, kb, benchmark=benchmark)
    case_limit = (
        len(benchmark["cases"])
        if args.max_cases <= 0
        else min(args.max_cases, len(benchmark["cases"]))
    )

    price_path = PROJECT_ROOT / "config" / "experiment_models.json"
    prices = json.loads(price_path.read_text(encoding="utf-8")).get("prices", {})

    def baseline_runner(
        claims: list[Claim],
    ) -> tuple[list[Claim], dict[str, Any]]:
        return abl._evidence_triad(claims), {}

    combos: list[tuple[str, Runner, str, str]] = [
        ("baseline_rule", baseline_runner, "rule", "rule"),
    ]
    for provider, model in models:
        key = f"{provider}:{model}"
        combos.append(
            (
                f"llm_{provider}_{model}",
                make_llm_runner(kb, provider, model, provider, model),
                key,
                key,
            )
        )
    if 1 < len(models) <= 3:
        for i, (pa, ma) in enumerate(models):
            for j, (pb, mb) in enumerate(models):
                if i == j:
                    continue
                combos.append(
                    (
                        f"hetero_{pa}_{ma}__{pb}_{mb}",
                        make_llm_runner(kb, pa, ma, pb, mb),
                        f"{pa}:{ma}",
                        f"{pb}:{mb}",
                    )
                )

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for combo_id, runner, critic_name, judge_name in combos:
        claims = abl._claims()[:case_limit]
        try:
            predicted, stats = runner(claims)
        except ProviderError as exc:
            skipped.append({"combo_id": combo_id, "reason": str(exc)})
            continue
        metrics = abl._metrics(predicted)
        rows.append(
            {
                "combo_id": combo_id,
                "critic": critic_name,
                "judge": judge_name,
                "metrics": metrics,
                "stats": stats,
                "cases": [abl._case_result(item) for item in predicted],
            }
        )

    for row in rows:
        row["cost_cny_estimate"] = _estimate_cost(row, prices)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_root = PROJECT_ROOT / "outputs" / "experiments" / f"decision-matrix-{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "summary.json").write_text(
        json.dumps(
            {
                "benchmark_id": benchmark["benchmark_id"],
                "case_count": case_limit,
                "models_requested": [f"{p}:{m}" for p, m in models],
                "skipped": skipped,
                "results": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_csv(out_root / "cases.csv", rows)
    (out_root / "REPORT.md").write_text(
        _markdown(rows, skipped, benchmark, case_limit), encoding="utf-8"
    )
    print(f"results: {out_root}")
    print(_markdown(rows, skipped, benchmark, case_limit))


def _estimate_cost(row: dict[str, Any], prices: dict[str, Any]) -> float | None:
    parts: list[float] = []
    stats = row.get("stats") or {}
    for role in ("critic", "judge"):
        entry = stats.get(role)
        if not entry:
            continue
        price = prices.get(row.get(role, ""))
        if not price or price.get("input") is None or price.get("output") is None:
            return None
        parts.append(
            entry["input_tokens"] / 1_000_000 * price["input"]
            + entry["output_tokens"] / 1_000_000 * price["output"]
        )
    return round(sum(parts), 4) if parts else None


def _flatten_stats(row: dict[str, Any]) -> dict[str, Any]:
    stats = row.get("stats") or {}
    merged: dict[str, Any] = {
        "calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "duration_ms": 0.0,
    }
    for role in ("critic", "judge"):
        entry = stats.get(role) or {}
        merged["calls"] += int(entry.get("calls", 0))
        merged["input_tokens"] += int(entry.get("input_tokens", 0))
        merged["output_tokens"] += int(entry.get("output_tokens", 0))
        merged["duration_ms"] += float(entry.get("duration_ms", 0.0))
    return merged


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "combo_id",
                "critic",
                "judge",
                "accepted_precision",
                "gold_recall",
                "unsupported_acceptance_rate",
                "calls",
                "input_tokens",
                "output_tokens",
                "duration_ms",
                "cost_cny_estimate",
            ],
        )
        writer.writeheader()
        for row in rows:
            metrics = row["metrics"]
            stats = _flatten_stats(row)
            writer.writerow(
                {
                    "combo_id": row["combo_id"],
                    "critic": row["critic"],
                    "judge": row["judge"],
                    "accepted_precision": metrics.get("accepted_precision"),
                    "gold_recall": metrics.get("gold_recall"),
                    "unsupported_acceptance_rate": metrics.get(
                        "unsupported_acceptance_rate"
                    ),
                    "calls": stats["calls"],
                    "input_tokens": stats["input_tokens"],
                    "output_tokens": stats["output_tokens"],
                    "duration_ms": stats["duration_ms"],
                    "cost_cny_estimate": row.get("cost_cny_estimate"),
                }
            )


def _markdown(
    rows: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    benchmark: dict[str, Any],
    case_limit: int,
) -> str:
    scope = benchmark.get("scope") or "自定义案例集"
    lines = [
        "# 决策机制对比实验报告",
        "",
        f"生成时间（UTC）：{datetime.now(UTC).isoformat()}",
        "",
        f"> 案例集：{benchmark.get('benchmark_id', 'unknown')}（本次 {case_limit} 条）。{scope}",
        "",
        "| 组合 | 批判者 | 裁判 | 接收精确率 | Gold 召回 | 不支持接收率 | 调用 | in tokens | out tokens | 耗时 ms | 成本(约¥) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        metrics = row["metrics"]
        stats = _flatten_stats(row)
        lines.append(
            "| {id} | {c} | {j} | {p} | {r} | {u} | {calls} | {it} | {ot} | {ms} | {cost} |".format(
                id=row["combo_id"],
                c=row["critic"],
                j=row["judge"],
                p=metrics.get("accepted_precision"),
                r=metrics.get("gold_recall"),
                u=metrics.get("unsupported_acceptance_rate"),
                calls=stats["calls"],
                it=stats["input_tokens"],
                ot=stats["output_tokens"],
                ms=round(stats["duration_ms"], 1),
                cost=(
                    row["cost_cny_estimate"]
                    if row.get("cost_cny_estimate") is not None
                    else "未定价"
                ),
            )
        )
    if skipped:
        lines.append("")
        lines.append("## 跳过的组合（缺 Key 等）")
        for item in skipped:
            lines.append(f"- {item['combo_id']}：{item['reason']}")
    lines.append("")
    lines.append("注：Wilson 95% 区间与逐案例明细见 summary.json / cases.csv。")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
