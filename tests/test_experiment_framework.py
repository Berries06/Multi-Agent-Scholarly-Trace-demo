from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.experiments.framework import (  # noqa: E402
    CURRENT_PIPELINE,
    DECISION_VARIANTS,
    SUPPORTED_EVALUATION_TYPES,
    execute_experiment,
    load_experiment_config,
    verify_experiment_artifacts,
)


EXPERIMENT_ROOT = PROJECT_ROOT / "tests" / "experiments"


class ExperimentFrameworkTests(unittest.TestCase):
    def test_all_six_configs_use_current_protocols(self) -> None:
        paths = sorted(EXPERIMENT_ROOT.glob("[0-9][0-9]_*/experiment.json"))
        self.assertEqual(6, len(paths))
        for path in paths:
            with self.subTest(path=path):
                config = load_experiment_config(path)
                self.assertNotIn("presets", config)
                self.assertIn(
                    config["evaluation_type"],
                    SUPPORTED_EVALUATION_TYPES,
                )
                self.assertTrue(config["claim_ceiling"])
                if config["mode"] == "decision_ablation":
                    self.assertTrue(set(config["variants"]).issubset(DECISION_VARIANTS))
                else:
                    self.assertEqual([CURRENT_PIPELINE], config["variants"])

    def test_all_six_experiment_entries_complete_in_smoke_mode(self) -> None:
        paths = sorted(EXPERIMENT_ROOT.glob("[0-9][0-9]_*/experiment.json"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            for path in paths:
                with self.subTest(path=path):
                    output = execute_experiment(
                        path,
                        output_root=output_root,
                        repetitions_override=1,
                    )
                    expected_files = {
                        "REPORT.md",
                        "cases.csv",
                        "raw_results.json",
                        "run_config.json",
                        "summary.json",
                        "verification.json",
                    }
                    self.assertEqual(
                        expected_files,
                        {item.name for item in output.iterdir()},
                    )
                    rows = json.loads(
                        (output / "raw_results.json").read_text(encoding="utf-8")
                    )
                    self.assertTrue(rows)
                    config = load_experiment_config(path)
                    self.assertTrue(
                        all(
                            row["evaluation_type"] == config["evaluation_type"]
                            and row["data_kind"] == config["evaluation_type"]
                            and row["claim_ceiling"] == config["claim_ceiling"]
                            for row in rows
                        )
                    )
                    summary = json.loads(
                        (output / "summary.json").read_text(encoding="utf-8")
                    )
                    self.assertTrue(
                        all(
                            row["claim_ceiling"] == config["claim_ceiling"]
                            for row in summary
                        )
                    )
                    receipt = json.loads(
                        (output / "verification.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual("passed", receipt["status"])
                    self.assertEqual(5, len(receipt["verified_sha256"]))
                    if config["mode"] == "orchestrator":
                        self.assertTrue(
                            all(
                                row["timing_scope"]
                                == "core_pipeline_excluding_decision_ablation"
                                for row in rows
                            )
                        )
                    verify_experiment_artifacts(output)

    def test_archived_preset_config_is_rejected(self) -> None:
        payload = {
            "slug": "invalid",
            "title": "invalid",
            "purpose": "invalid",
            "mode": "orchestrator",
            "evaluation_type": "synthetic_proxy",
            "claim_ceiling": "invalid",
            "presets": ["full"],
            "primary_metrics": ["invalid"],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "experiment.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "archived six-agent presets"):
                load_experiment_config(path)


if __name__ == "__main__":
    unittest.main()
