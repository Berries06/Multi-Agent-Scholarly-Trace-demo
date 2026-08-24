"""CLI：语义力度检查器（演示/自检用）。

用法：
  python scripts/check_semantic_strength.py "我们证明了该方法零幻觉"
  python scripts/check_semantic_strength.py --file sentences.txt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.semantic_check import check_semantic_strength  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?", default="")
    parser.add_argument("--file", default="")
    args = parser.parse_args()

    if args.file:
        lines = [
            line.strip()
            for line in Path(args.file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif args.text:
        lines = [args.text]
    else:
        lines = [
            line.strip() for line in sys.stdin if line.strip()
        ]

    results = [check_semantic_strength(line) for line in lines]
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
