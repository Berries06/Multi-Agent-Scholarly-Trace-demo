from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.evaluation import evaluate_orchestrator  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)

    def test_three_synthetic_profiles_are_available(self) -> None:
        profiles = self.orchestrator.list_profiles()
        self.assertEqual(3, len(profiles))
        self.assertTrue(all(profile["synthetic"] for profile in profiles))

    def test_complete_six_agent_trace_is_returned(self) -> None:
        result = self.orchestrator.run("undergraduate_ai")
        roles = {step["role"] for step in result["agent_trace"]}
        self.assertEqual(6, len(result["agent_trace"]))
        self.assertEqual(9, len(result["claims"]))
        self.assertEqual(
            {
                "画像分析",
                "证据召回",
                "关联提出",
                "反证与约束",
                "置信裁决",
                "资源编排",
            },
            roles,
        )

    def test_unsupported_absolute_claim_is_rejected(self) -> None:
        result = self.orchestrator.run("graduate_cross_domain")
        pressure_claim = next(
            claim for claim in result["claims"] if claim["relation"] == "guarantees"
        )
        self.assertEqual("rejected", pressure_claim["status"])
        self.assertEqual([], pressure_claim["evidence_ids"])

    def test_all_accepted_claims_have_traceable_evidence(self) -> None:
        result = self.orchestrator.run("enterprise_analyst")
        accepted = [
            claim for claim in result["claims"] if claim["status"] == "accepted"
        ]
        self.assertGreater(len(accepted), 0)
        self.assertTrue(all(claim["evidence_ids"] for claim in accepted))
        self.assertTrue(
            all(
                paper_id in self.orchestrator.kb.paper_by_id
                for claim in accepted
                for paper_id in claim["evidence_ids"]
            )
        )

    def test_three_resource_types_are_generated(self) -> None:
        resources = self.orchestrator.run("undergraduate_ai")["resources"]
        self.assertIn("briefing", resources)
        self.assertIn("practical_guide", resources)
        self.assertIn("quiz", resources)
        self.assertGreaterEqual(len(resources["quiz"]["items"]), 2)

    def test_feedback_changes_target_difficulty(self) -> None:
        hard = self.orchestrator.run_with_feedback(
            "graduate_cross_domain", "too_hard"
        )
        easy = self.orchestrator.run_with_feedback(
            "graduate_cross_domain", "too_easy"
        )
        self.assertEqual(2, hard["diagnosis"]["target_difficulty"])
        self.assertEqual(4, easy["diagnosis"]["target_difficulty"])

    def test_graph_contains_evidence_nodes_and_edges(self) -> None:
        graph = self.orchestrator.run("graduate_cross_domain")["graph"]
        self.assertTrue(any(node["kind"] == "paper" for node in graph["nodes"]))
        self.assertTrue(any(edge["label"] == "evidence" for edge in graph["edges"]))

    def test_engineering_thresholds_pass(self) -> None:
        report = evaluate_orchestrator(self.orchestrator)
        self.assertEqual(9, report["case_count"])
        self.assertTrue(all(report["thresholds"].values()))


if __name__ == "__main__":
    unittest.main()
