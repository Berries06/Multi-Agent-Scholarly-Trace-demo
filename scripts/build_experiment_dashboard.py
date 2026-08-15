from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "outputs" / "experiments"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "experiment-dashboard.html"


def _latest_run(experiment_dir: Path) -> Path:
    runs = sorted(
        (
            path
            for path in experiment_dir.iterdir()
            if path.is_dir() and (path / "summary.json").exists()
        ),
        key=lambda path: path.name,
    )
    if not runs:
        raise FileNotFoundError(f"No completed run under {experiment_dir}")
    return runs[-1]


def load_latest_runs(root: Path) -> list[dict[str, Any]]:
    experiments = []
    for experiment_dir in sorted(root.glob("[0-9][0-9]_*")):
        if not experiment_dir.is_dir():
            continue
        run_dir = _latest_run(experiment_dir)
        config = json.loads(
            (run_dir / "run_config.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (run_dir / "summary.json").read_text(encoding="utf-8")
        )
        experiments.append(
            {
                "slug": config["slug"],
                "title": config["title"],
                "purpose": config["purpose"],
                "mode": config["mode"],
                "data_kind": config.get("data_kind", "unknown"),
                "run_dir": run_dir,
                "summary": summary,
            }
        )
    if len(experiments) != 6:
        raise ValueError(f"Expected six completed experiments, found {len(experiments)}")
    return experiments


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _summary_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>无汇总行。</p>"
    preferred = [
        "variant",
        "data_multiplier",
        "feedback",
        "case_runs",
        "accepted_precision",
        "gold_recall",
        "unsupported_acceptance_rate",
        "evidence_coverage",
        "decision_accuracy",
        "pressure_block_rate",
        "trace_complete_rate",
        "mean_total_ms",
        "p95_total_ms",
    ]
    available = {key for row in rows for key in row}
    columns = [key for key in preferred if key in available]
    head = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(_format_value(row.get(column, '')))}</td>"
            for column in columns
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def render_dashboard(experiments: list[dict[str, Any]]) -> str:
    cards = []
    for experiment in experiments:
        cards.append(
            """
            <section class="card">
              <div class="meta"><span>{slug}</span><span>{mode}</span><span>{kind}</span></div>
              <h2>{title}</h2>
              <p>{purpose}</p>
              {table}
              <p class="path">最新运行：{path}</p>
            </section>
            """.format(
                slug=html.escape(experiment["slug"]),
                mode=html.escape(experiment["mode"]),
                kind=html.escape(experiment["data_kind"]),
                title=html.escape(experiment["title"]),
                purpose=html.escape(experiment["purpose"]),
                table=_summary_table(experiment["summary"]),
                path=html.escape(str(experiment["run_dir"])),
            )
        )
    generated_at = datetime.now(timezone.utc).isoformat()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>研海寻踪 · P0 实验看板</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, "Microsoft YaHei", sans-serif; background: #f4f7fb; color: #182230; }}
    body {{ margin: 0; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 40px 24px 64px; }}
    header {{ margin-bottom: 28px; }}
    h1 {{ margin: 0 0 10px; font-size: 32px; }}
    .notice {{ padding: 14px 18px; border-left: 4px solid #d97706; background: #fff7ed; border-radius: 8px; }}
    .grid {{ display: grid; gap: 20px; }}
    .card {{ background: white; padding: 22px; border-radius: 14px; box-shadow: 0 8px 30px rgba(31, 45, 61, .08); }}
    .card h2 {{ margin: 10px 0 8px; font-size: 21px; }}
    .meta {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .meta span {{ background: #e8eef8; border-radius: 999px; padding: 4px 9px; font-size: 12px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; min-width: 720px; width: 100%; margin-top: 14px; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child {{ text-align: left; }}
    .path {{ color: #64748b; font-size: 12px; word-break: break-all; }}
    footer {{ margin-top: 28px; color: #64748b; font-size: 12px; }}
  </style>
</head>
<body><main>
  <header>
    <h1>研海寻踪 · P0 三智能体实验看板</h1>
    <p class="notice"><strong>口径：</strong>各卡片按配置标记为 synthetic_proxy、self_supervised_proxy 或 simulation_only；均非 real_gt / human_eval，只证明对应主张上限内的工程行为。</p>
  </header>
  <div class="grid">{''.join(cards)}</div>
  <footer>UTC 生成时间：{html.escape(generated_at)}</footer>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    experiments = load_latest_runs(args.input_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_dashboard(experiments), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
