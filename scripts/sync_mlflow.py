"""Import verified experiment directories into the local/shared MLflow store."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.mlflow_tracking import sync_all_verified_runs, sync_verified_run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="只同步一个含 verification.json 的运行目录；默认扫描全部。",
    )
    args = parser.parse_args()
    if args.run_dir:
        run_dir = args.run_dir
        if not run_dir.is_absolute():
            run_dir = PROJECT_ROOT / run_dir
        results = [sync_verified_run(PROJECT_ROOT, run_dir)]
    else:
        results = sync_all_verified_runs(PROJECT_ROOT)
    print(
        json.dumps(
            {
                "run_count": len(results),
                "imported": sum(item["status"] == "imported" for item in results),
                "skipped": sum(item["status"] == "skipped" for item in results),
                "runs": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

