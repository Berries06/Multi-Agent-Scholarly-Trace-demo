from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    output_path = Path("outputs/mvp_results.json")
    if not output_path.exists():
        raise SystemExit("outputs/mvp_results.json not found. Run scripts/run_mvp.py first.")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    evaluation = payload.get("evaluation")
    if not evaluation:
        raise SystemExit("Evaluation block missing in output. Ensure gold file is provided.")

    print("Evaluation summary")
    for k, v in evaluation.items():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    main()
