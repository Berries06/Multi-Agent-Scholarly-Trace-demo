from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai import ScholarlyTraceOrchestrator  # noqa: E402


class CurrentPipelineBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
        cls.result = cls.orchestrator.run("undergraduate_ai")

    def test_run_signature_has_no_archived_preset_argument(self) -> None:
        parameters = inspect.signature(self.orchestrator.run).parameters
        self.assertNotIn("config", parameters)
        self.assertNotIn("preset", parameters)

    def test_current_trace_contains_exactly_three_decision_agents(self) -> None:
        self.assertEqual(3, self.result["core_method"]["agent_count"])
        self.assertEqual(
            {"关联提出", "反证与约束", "置信裁决"},
            {item["role"] for item in self.result["agent_trace"]},
        )

    def test_track_a_exposes_only_current_decision_variants(self) -> None:
        variants = {
            item["variant_id"] for item in self.result["ablation"]["variants"]
        }
        self.assertEqual(
            {
                "rule_program",
                "single_pass",
                "homogeneous_vote",
                "evidence_triad",
            },
            variants,
        )

    def test_unsupported_pressure_claim_is_not_accepted(self) -> None:
        pressure = next(
            claim
            for claim in self.result["claims"]
            if claim["relation"] == "guarantees"
        )
        self.assertNotEqual("accepted", pressure["status"])

    def test_every_accepted_claim_has_valid_evidence_details(self) -> None:
        accepted = [
            claim for claim in self.result["claims"] if claim["status"] == "accepted"
        ]
        self.assertTrue(accepted)
        self.assertTrue(
            all(
                all(
                    self.orchestrator.kb.evidence_is_valid(item)
                    for item in claim["evidence_ids"]
                )
                and self.result["evidence_details"][claim["claim_id"]]
                for claim in accepted
            )
        )

if __name__ == "__main__":
    unittest.main()
