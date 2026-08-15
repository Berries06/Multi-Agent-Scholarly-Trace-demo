from __future__ import annotations

import argparse
from pathlib import Path

from tests.experiments.framework import execute_experiment


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    configs = sorted(ROOT.glob("[0-9][0-9]_*/experiment.json"))
    if not configs:
        raise SystemExit("No experiment configs found.")
    for config in configs:
        output_dir = execute_experiment(
            config,
            output_root=args.output_root,
            repetitions_override=args.repetitions,
        )
        print(f"{config.parent.name}: {output_dir}")


if __name__ == "__main__":
    main()
