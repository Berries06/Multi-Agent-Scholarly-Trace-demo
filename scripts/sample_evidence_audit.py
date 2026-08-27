"""人工证据审计抽样：两个新领域各抽 20 张证据卡，生成复核表。

用法：
  python scripts/sample_evidence_audit.py [--per-domain 20] [--seed 42]

产出 outputs/evidence-audit-sample.csv，列：领域、论文 ID、DOI、标题、
摘要卡出处声明、复核结论（空）、复核备注（空）。复核人逐行核对摘要、
关系与证据跨度后填写结论，完成 P1 人工证据审计锚点。
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEW_DOMAINS = ["single-cell-transcriptomics", "quantum-computing"]
FIELD_ORDER = ["domain", "paper_id", "doi", "title", "knowledge_card_basis", "conclusion", "note"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-domain", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    rng = random.Random(args.seed)
    for domain_id in NEW_DOMAINS:
        manifest_path = (
            PROJECT_ROOT
            / "data"
            / "vertical_kb"
            / "domains"
            / domain_id
            / "manifest.json"
        )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        evidence_papers = [
            paper
            for paper in payload.get("papers", [])
            if not paper.get("exclude_from_evidence_graph", False)
        ]
        sample = rng.sample(evidence_papers, min(args.per_domain, len(evidence_papers)))
        for paper in sample:
            rows.append(
                {
                    "domain": domain_id,
                    "paper_id": paper.get("paper_id", ""),
                    "doi": paper.get("doi", ""),
                    "title": paper.get("title", ""),
                    "knowledge_card_basis": paper.get("knowledge_card_basis", ""),
                    "conclusion": "",
                    "note": "",
                }
            )

    output_path = PROJECT_ROOT / "outputs" / "evidence-audit-sample.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELD_ORDER)
        writer.writeheader()
        writer.writerows(rows)
    print(f"抽样 {len(rows)} 张证据卡 -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
