"""12 组模型矩阵 × 3 领域冻结 L2（合计 390 条）顺序执行驱动器。

背景：
- run_decision_experiment.py 一次只能挂一个 --domain 的知识库，而 390 条 L2
  分布在三个领域冻结文件里（140+130+120），所以矩阵按"组 × 领域"共 36 次调用，
  每条案例在每组组合上恰好跑一次；
- 组定义与 docs/协作与运维/模型选型与接入方案_2026-08-23.md 第 4 节矩阵一致：
  H1–H6 同质（--models 单模型），E1–E6 异质（--pairs 显式配对）；
- 每次调用一个独立 run 目录（runner 自带时间戳目录），失败不中断、逐条记录。

用法：
  python scripts/run_decision_matrix.py                 # 全量 36 次
  python scripts/run_decision_matrix.py --groups H1,H4,E1
  python scripts/run_decision_matrix.py --domains scientific-ie-kg

产物：
  outputs/experiments/matrix-manifest-<UTC时间戳>.json —— 36 条的
  group/domain/exit_code/run_dir/起止时间台账，与各 run 目录的 summary.json 互证。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "scripts" / "run_decision_experiment.py"
OUT_ROOT = PROJECT_ROOT / "outputs" / "experiments"

DOMAINS: dict[str, tuple[str, int]] = {
    "scientific-ie-kg": (
        "data/evaluation/generated-decision-cases-v1.json",
        140,
    ),
    "educational-knowledge-tracing": (
        "data/evaluation/generated-decision-cases-v1-educational-knowledge-tracing.json",
        130,
    ),
    "materials-discovery-gnn": (
        "data/evaluation/generated-decision-cases-v1-materials-discovery-gnn.json",
        120,
    ),
}

GROUPS: list[dict[str, str]] = [
    # 同质组 H1–H6：批判者与裁判同模型
    {"id": "H1", "mode": "homo", "critic": "deepseek:deepseek-v4-flash", "arg": "--models", "value": "deepseek:deepseek-v4-flash"},
    {"id": "H2", "mode": "homo", "critic": "zhipu:glm-4-flash", "arg": "--models", "value": "zhipu:glm-4-flash"},
    {"id": "H3", "mode": "homo", "critic": "kimi:kimi-k2.6", "arg": "--models", "value": "kimi:kimi-k2.6"},
    {"id": "H4", "mode": "homo", "critic": "deepseek:deepseek-v4-pro", "arg": "--models", "value": "deepseek:deepseek-v4-pro"},
    {"id": "H5", "mode": "homo", "critic": "zhipu:glm-5-turbo", "arg": "--models", "value": "zhipu:glm-5-turbo"},
    {"id": "H6", "mode": "homo", "critic": "kimi:kimi-k3", "arg": "--models", "value": "kimi:kimi-k3"},
    # 异质组 E1–E6：批判者 > 裁判
    {"id": "E1", "mode": "hetero", "critic": "zhipu:glm-4-flash", "judge": "deepseek:deepseek-v4-pro", "arg": "--pairs", "value": "zhipu:glm-4-flash>deepseek:deepseek-v4-pro"},
    {"id": "E2", "mode": "hetero", "critic": "kimi:kimi-k2.6", "judge": "deepseek:deepseek-v4-pro", "arg": "--pairs", "value": "kimi:kimi-k2.6>deepseek:deepseek-v4-pro"},
    {"id": "E3", "mode": "hetero", "critic": "deepseek:deepseek-v4-flash", "judge": "zhipu:glm-5-turbo", "arg": "--pairs", "value": "deepseek:deepseek-v4-flash>zhipu:glm-5-turbo"},
    {"id": "E4", "mode": "hetero", "critic": "zhipu:glm-4-flash", "judge": "kimi:kimi-k3", "arg": "--pairs", "value": "zhipu:glm-4-flash>kimi:kimi-k3"},
    {"id": "E5", "mode": "hetero", "critic": "deepseek:deepseek-v4-pro", "judge": "zhipu:glm-4-flash", "arg": "--pairs", "value": "deepseek:deepseek-v4-pro>zhipu:glm-4-flash"},
    {"id": "E6", "mode": "hetero", "critic": "kimi:kimi-k2.6", "judge": "kimi:kimi-k3", "arg": "--pairs", "value": "kimi:kimi-k2.6>kimi:kimi-k3"},
]


def existing_run_dirs() -> set[str]:
    return {
        item.name
        for item in OUT_ROOT.iterdir()
        if item.is_dir() and item.name.startswith("decision-matrix-")
    }


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", default="", help="只跑这些组（逗号分隔，如 H1,E1）")
    parser.add_argument("--domains", default="", help="只跑这些领域（逗号分隔）")
    args = parser.parse_args()

    group_filter = {item.strip() for item in args.groups.split(",") if item.strip()}
    domain_filter = {item.strip() for item in args.domains.split(",") if item.strip()}
    groups = [item for item in GROUPS if not group_filter or item["id"] in group_filter]
    domains = {
        key: value
        for key, value in DOMAINS.items()
        if not domain_filter or key in domain_filter
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_path = OUT_ROOT / f"matrix-manifest-{stamp}.json"
    entries: list[dict] = []

    def save() -> None:
        manifest_path.write_text(
            json.dumps(
                {"started_at_utc": stamp, "entries": entries},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    for group in groups:
        for domain_id, (cases_rel, expected) in domains.items():
            before = existing_run_dirs()
            started = datetime.now(UTC).isoformat()
            command = [
                sys.executable,
                str(RUNNER),
                group["arg"],
                group["value"],
                "--cases",
                str(PROJECT_ROOT / cases_rel),
                "--domain",
                domain_id,
            ]
            print(f"[{group['id']} × {domain_id}] {' '.join(command[2:])}", flush=True)
            result = subprocess.run(command, cwd=str(PROJECT_ROOT))
            finished = datetime.now(UTC).isoformat()
            new_dirs = sorted(existing_run_dirs() - before)
            entries.append(
                {
                    "group": group["id"],
                    "mode": group["mode"],
                    "critic": group["critic"],
                    "judge": group.get("judge", group["critic"]),
                    "domain": domain_id,
                    "domain_cases": expected,
                    "exit_code": result.returncode,
                    "run_dir": new_dirs[0] if new_dirs else None,
                    "started_at_utc": started,
                    "finished_at_utc": finished,
                }
            )
            save()
            if result.returncode != 0:
                print(
                    f"[{group['id']} × {domain_id}] 退出码 {result.returncode}，"
                    "已记录并继续下一组。",
                    flush=True,
                )

    failures = [item for item in entries if item["exit_code"] != 0 or not item["run_dir"]]
    print(f"manifest: {manifest_path}")
    print(f"完成 {len(entries)} 次调用，失败 {len(failures)} 次。")
    if failures:
        for item in failures:
            print(f"  - {item['group']} × {item['domain']}: exit={item['exit_code']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
