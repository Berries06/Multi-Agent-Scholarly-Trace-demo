"""生成三领域 × 三演示画像的固定输入—中间—输出案例。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402


def build_cases() -> dict[str, object]:
    orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
    domains = orchestrator.list_domains()
    cases: list[dict[str, object]] = []
    for domain in domains:
        for profile_id in orchestrator.profiles:
            result = orchestrator.run(
                profile_id,
                domain["query_example"],
                domain_id=domain["domain_id"],
            )
            cases.append(
                {
                    **result,
                    "case_id": f"{domain['domain_id']}--{profile_id}",
                    "input_snapshot": {
                        "domain_id": domain["domain_id"],
                        "query": domain["query_example"],
                        "learner_profile": result["profile"],
                    },
                    "contract": {
                        "input_fields": [
                            "input_snapshot.domain_id",
                            "input_snapshot.query",
                            "input_snapshot.learner_profile",
                        ],
                        "multi_agent_intermediate_fields": [
                            "specialist_agent_trace",
                            "agent_trace",
                            "claims",
                            "graph_retrieval",
                        ],
                        "personalized_output_fields": [
                            "resources",
                            "report",
                            "assistant_response",
                        ],
                    },
                }
            )
    return {
        "generated_from": "ScholarlyTraceOrchestrator",
        "generated_at": datetime.now(UTC).isoformat(),
        "domain_count": len(domains),
        "profile_count": len(orchestrator.profiles),
        "case_count": len(cases),
        "requirement_mapping": {
            "vertical_domain_slices": len(domains),
            "differentiated_learner_profiles": len(orchestrator.profiles),
            "complete_input_intermediate_output_examples": len(cases),
            "profile_data_note": "全部为脱敏合成画像，不含真实个人信息。",
        },
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "examples" / "complete_demo_cases.json",
    )
    args = parser.parse_args()
    payload = build_cases()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({key: payload[key] for key in ("domain_count", "profile_count", "case_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
