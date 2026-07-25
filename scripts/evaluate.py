from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.evaluation import evaluate_orchestrator  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402


def main() -> None:
    report = evaluate_orchestrator(ScholarlyTraceOrchestrator(PROJECT_ROOT))
    output = PROJECT_ROOT / "outputs" / "engineering-evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(json.dumps(report["thresholds"], ensure_ascii=False, indent=2))
    print(f"工程回归用例：{report['case_count']}；输出：{output}")
    if not all(report["thresholds"].values()):
        raise SystemExit("One or more engineering thresholds were not met.")


if __name__ == "__main__":
    main()
