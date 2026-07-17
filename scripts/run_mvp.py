from __future__ import annotations

import argparse
import json
from pathlib import Path

from yanhai.pipeline import ScholarlyTracePipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Scholarly Trace MVP pipeline.")
    parser.add_argument(
        "--documents",
        type=Path,
        default=Path("data/mvp/documents.jsonl"),
        help="Path to input documents JSONL.",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("data/mvp/gold_claims.jsonl"),
        help="Path to gold triples JSONL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/mvp_results.json"),
        help="Path to output result JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pipeline = ScholarlyTracePipeline()
    result = pipeline.run(args.documents, args.gold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MVP pipeline complete. Output: {args.output}")


if __name__ == "__main__":
    main()
