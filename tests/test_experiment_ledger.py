from __future__ import annotations

import json
import unittest
from pathlib import Path

from yanhai.experiment_ledger import build_experiment_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ExperimentLedgerTests(unittest.TestCase):
    def test_lists_all_versioned_protocols(self) -> None:
        ledger = build_experiment_ledger(PROJECT_ROOT)
        self.assertEqual(ledger["schema_version"], "1.0.0")
        self.assertEqual(ledger["protocol_count"], 6)
        self.assertEqual(len(ledger["protocols"]), 6)
        self.assertEqual(ledger["mlflow_url"], "http://127.0.0.1:5000/")
        self.assertIn("tests.experiments.run_all", ledger["run_command"])
        for protocol in ledger["protocols"]:
            self.assertTrue(protocol["slug"])
            self.assertTrue(protocol["title"])
            self.assertIn(
                protocol["evaluation_type"],
                {"synthetic_proxy", "self_supervised_proxy", "simulation_only"},
            )

    def test_every_indexed_run_has_a_verification_receipt(self) -> None:
        ledger = build_experiment_ledger(PROJECT_ROOT)
        for run in ledger["runs"]:
            receipt = PROJECT_ROOT / run["artifact_path"] / "verification.json"
            self.assertTrue(receipt.is_file())
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(run["status"], payload["status"])


if __name__ == "__main__":
    unittest.main()
