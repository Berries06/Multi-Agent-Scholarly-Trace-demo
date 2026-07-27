from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.config import PRESETS  # noqa: E402
from yanhai.orchestrator import DEFAULT_QUERY, ScholarlyTraceOrchestrator  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one Yanhai multi-agent flow.")
    parser.add_argument(
        "--profile",
        default="undergraduate_ai",
        choices=["undergraduate_ai", "graduate_cross_domain", "enterprise_analyst"],
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--preset", choices=sorted(PRESETS), default="full")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or PROJECT_ROOT / "outputs" / f"demo-{args.profile}.json"
    result = ScholarlyTraceOrchestrator(PROJECT_ROOT).run(
        args.profile, args.query, config=args.preset
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"画像：{result['profile']['name']} / {result['profile']['persona']}")
    print(f"方案：{result['system_config']['label']} ({args.preset})")
    print(
        "指标："
        f"幻觉代理 {result['metrics']['hallucination_proxy_rate']}%，"
        f"适配 {result['metrics']['adaptation_accuracy']}%，"
        f"覆盖 {result['metrics']['knowledge_coverage_rate']}%"
    )
    print(f"输出：{output}")


if __name__ == "__main__":
    main()
