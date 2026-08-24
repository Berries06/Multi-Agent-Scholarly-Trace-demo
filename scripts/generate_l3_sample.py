"""L3 人工核验抽查表生成器。

从 L2 案例集分层随机抽取 N 条，生成可直接分给成员填写的 CSV 核验表。
核验结论只记录在核验表副本里，不改动冻结的 L2 文件（见测试案例集扩充指南）。

用法：
  python scripts/generate_l3_sample.py
  python scripts/generate_l3_sample.py --cases data/evaluation/generated-decision-cases-v1.json \
      --positives 8 --per-negative 5 --out outputs/l3-sample.csv --seed 20260820
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def sample_cases(
    cases: list[dict[str, Any]], positives: int, per_negative: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in cases:
        kind = "positive" if item["gold_supported"] else str(item["error_type"])
        by_type.setdefault(kind, []).append(item)
    picked: list[dict[str, Any]] = []
    for kind, pool in by_type.items():
        limit = positives if kind == "positive" else per_negative
        picked.extend(rng.sample(pool, min(limit, len(pool))))
    picked.sort(key=lambda item: item["claim_id"])
    return picked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(
            PROJECT_ROOT
            / "data"
            / "evaluation"
            / "generated-decision-cases-v1.json"
        ),
    )
    parser.add_argument("--positives", type=int, default=8)
    parser.add_argument("--per-negative", type=int, default=5)
    parser.add_argument(
        "--out", default=str(PROJECT_ROOT / "outputs" / "l3-sample.csv")
    )
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()

    payload = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    picked = sample_cases(
        payload["cases"], args.positives, args.per_negative, args.seed
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "claim_id",
                "类型",
                "命题(source→target)",
                "关系类型",
                "证据ID数",
                "自动标签(gold_supported)",
                "核验人",
                "核验结论",
                "备注",
            ]
        )
        for item in picked:
            writer.writerow(
                [
                    item["claim_id"],
                    (
                        "positive"
                        if item["gold_supported"]
                        else str(item["error_type"])
                    ),
                    f"{item['source']} → {item['target']}",
                    item["relation_type"],
                    len(item["evidence_ids"]),
                    "true" if item["gold_supported"] else "false",
                    "",
                    "",
                    item.get("note", ""),
                ]
            )
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "output": str(out_path),
                "sha256": digest,
                "sample_size": len(picked),
                "instructions": (
                    "核验结论只填三种：支持 / 推翻 / 存疑。"
                    "推翻或存疑的条目在备注里写理由。"
                    "核验完成后把结论汇总给我，我计算一致率并更新锚点集。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
