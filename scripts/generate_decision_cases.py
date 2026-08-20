"""L2 真实证据机制用例生成器。

从真实抽取图谱的 accepted 关系程序化生成决策测试用例：
  - positive        真实关系 + 真实证据（gold_supported=true）
  - no_evidence     同一三元组去掉全部证据（false）
  - wrong_evidence  换成不相关论文的真实证据 ID（false）
  - overclaim       关系谓词改写为绝对化 guarantees（false）
  - type_mismatch   换成违反 schema 类型约束的关系类型（false）

标签全部由构造方式客观决定，不依赖模型判断；positive 标签以规则抽取的
accepted 关系为基准，须由 L3 人工抽查核验（见 docs/项目说明/测试数据交付规格.md）。

用法：
  python scripts/generate_decision_cases.py            # 生成默认 v1 文件
  python scripts/generate_decision_cases.py --out data/evaluation/generated-decision-cases-v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.knowledge import KnowledgeBase  # noqa: E402


def load_schema() -> dict[str, Any]:
    path = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def find_mismatched_type(
    relation_type: str,
    source_type: str,
    target_type: str,
    constraints: dict[str, Any],
) -> str | None:
    """Return a relation type whose constraints reject (source_type, target_type)."""
    for candidate in constraints:
        if candidate == relation_type:
            continue
        rule = constraints[candidate]
        if not rule:
            continue
        if source_type not in rule.get("source", []) or target_type not in rule.get(
            "target", []
        ):
            return candidate
    return None


def unrelated_evidence_id(
    relation: dict[str, Any],
    evidence_by_id: dict[str, Any],
    entities_by_id: dict[str, Any],
    rng: random.Random,
) -> str | None:
    source = entities_by_id[relation["source_id"]]
    target = entities_by_id[relation["target_id"]]
    names = {
        source["canonical_name"].casefold(),
        target["canonical_name"].casefold(),
        *{alias.casefold() for alias in source["aliases"]},
        *{alias.casefold() for alias in target["aliases"]},
    }
    relation_papers = {
        evidence_by_id[eid]["paper_id"]
        for eid in relation["evidence_ids"]
        if eid in evidence_by_id
    }
    candidates = [
        item
        for item in evidence_by_id.values()
        if item["paper_id"] not in relation_papers
        and not any(name and name in item["text"].casefold() for name in names)
    ]
    if not candidates:
        return None
    return rng.choice(candidates)["evidence_id"]


def generate(seed: int) -> tuple[dict[str, Any], dict[str, int]]:
    schema = load_schema()
    kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
    graph = kb.extracted_paper_graph()
    entities_by_id = {item["entity_id"]: item for item in graph["entities"]}
    evidence_by_id = {item["evidence_id"]: item for item in graph["evidence"]}
    relations = [
        item
        for item in graph["relations"]
        if item["status"] == "accepted" and item["relation_type"] != "RELATED_TO"
    ]
    rng = random.Random(seed)

    cases: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for relation in relations:
        source = entities_by_id[relation["source_id"]]
        target = entities_by_id[relation["target_id"]]
        base = {
            "source": source["canonical_name"],
            "target": target["canonical_name"],
            "relation": relation["relation_type"].lower(),
            "relation_type": relation["relation_type"],
            "base_confidence": float(relation["confidence"]),
            "evidence_ids": list(relation["evidence_ids"]),
            "annotators": ["auto-generated"],
        }

        def add(kind: str, payload: dict[str, Any]) -> None:
            cases.append(payload)
            counts[kind] = counts.get(kind, 0) + 1

        if relation["evidence_ids"]:
            add(
                "positive",
                {
                    **base,
                    "claim_id": f"L2-POS-{relation['relation_id']}",
                    "gold_supported": True,
                    "error_type": None,
                    "note": "真实关系 + 真实证据；标签以规则抽取为准，需 L3 抽查",
                },
            )
        add(
            "no_evidence",
            {
                **base,
                "claim_id": f"L2-NOE-{relation['relation_id']}",
                "evidence_ids": [],
                "gold_supported": False,
                "error_type": "no_evidence",
                "note": "同一三元组去掉全部证据",
            },
        )
        wrong = unrelated_evidence_id(
            relation, evidence_by_id, entities_by_id, rng
        )
        if wrong:
            add(
                "wrong_evidence",
                {
                    **base,
                    "claim_id": f"L2-WEV-{relation['relation_id']}",
                    "evidence_ids": [wrong],
                    "gold_supported": False,
                    "error_type": "wrong_evidence_id",
                    "note": "换成不相关论文的真实证据 ID",
                },
            )
        add(
            "overclaim",
            {
                **base,
                "claim_id": f"L2-OVC-{relation['relation_id']}",
                "relation": "guarantees",
                "relation_type": "speculative",
                "gold_supported": False,
                "error_type": "overclaim",
                "note": "关系谓词改写为绝对化 guarantees",
            },
        )
        mismatched = find_mismatched_type(
            relation["relation_type"],
            source["entity_type"],
            target["entity_type"],
            schema.get("relation_constraints", {}),
        )
        if mismatched:
            add(
                "type_mismatch",
                {
                    **base,
                    "claim_id": f"L2-TMM-{relation['relation_id']}",
                    "relation": mismatched.lower(),
                    "relation_type": mismatched,
                    "gold_supported": False,
                    "error_type": "type_mismatch",
                    "note": f"换成违反约束的 {mismatched}",
                },
            )

    cases.sort(key=lambda item: item["claim_id"])
    payload = {
        "benchmark_id": "generated-decision-cases-v1",
        "domain": kb.selected_domain_id,
        "frozen_on": datetime.now(UTC).strftime("%Y-%m-%d"),
        "scope": (
            "L2 真实证据机制用例：从默认领域 accepted 关系程序化生成。"
            "标签由构造方式客观决定；positive 标签以规则抽取为基准，"
            "必须经 L3 人工抽查核验。不得在生成后修改标签；若人工推翻某条，"
            "写入 separate corrections 记录而非改文件。"
        ),
        "generation": {
            "seed": seed,
            "source_relation_count": len(relations),
            "generated_on": datetime.now(UTC).isoformat(),
        },
        "cases": cases,
    }
    return payload, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument(
        "--out",
        default=str(
            PROJECT_ROOT
            / "data"
            / "evaluation"
            / "generated-decision-cases-v1.json"
        ),
    )
    args = parser.parse_args()

    payload, counts = generate(args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    out_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    positive = counts.get("positive", 0)
    negative = sum(v for k, v in counts.items() if k != "positive")
    print(json.dumps(
        {
            "output": str(out_path),
            "sha256": digest,
            "case_count": len(payload["cases"]),
            "positive": positive,
            "negative": negative,
            "by_type": counts,
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
