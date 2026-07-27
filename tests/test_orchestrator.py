from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.evaluation import evaluate_orchestrator  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.providers import ProviderConfig  # noqa: E402


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)

    def test_three_synthetic_profiles_are_available(self) -> None:
        profiles = self.orchestrator.list_profiles()
        self.assertEqual(3, len(profiles))
        self.assertTrue(all(profile["synthetic"] for profile in profiles))

    def test_complete_three_agent_trace_is_returned(self) -> None:
        result = self.orchestrator.run("undergraduate_ai")
        roles = {step["role"] for step in result["agent_trace"]}
        self.assertEqual(3, len(result["agent_trace"]))
        self.assertEqual(9, len(result["claims"]))
        self.assertEqual(
            {
                "学情诊断与学习规划",
                "证据检索与知识图谱构建",
                "个性化教学与反馈",
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
        self.assertIn("feedback_form", resources)
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

    def test_quality_gate_is_separate_from_agent_trace(self) -> None:
        result = self.orchestrator.run("undergraduate_ai", config="full")
        quality = result["quality_assessment"]
        self.assertEqual("non_agent_quality_gate", quality["kind"])
        self.assertTrue(quality["enforced"])
        self.assertNotIn(
            quality["module"],
            {step["agent"] for step in result["agent_trace"]},
        )

    def test_questionnaire_updates_concept_state_in_memory(self) -> None:
        baseline = self.orchestrator.run("undergraduate_ai", config="full")
        focus = baseline["report"]["knowledge_state"]["next_focus"]
        updated = self.orchestrator.run_with_feedback(
            "undergraduate_ai",
            "suitable",
            config="full",
            prior_knowledge_state=baseline["report"]["knowledge_state"],
            concept_feedback={focus: {"correct": True, "self_rating": 4}},
            questionnaire={
                "relevance": 5,
                "difficulty_fit": 4,
                "clarity": 5,
                "evidence_trust": 4,
                "usefulness": 5,
            },
        )
        previous = next(
            item["posterior_mastery"]
            for item in baseline["report"]["knowledge_state"]["concepts"]
            if item["concept"] == focus
        )
        current = next(
            item["posterior_mastery"]
            for item in updated["report"]["knowledge_state"]["concepts"]
            if item["concept"] == focus
        )
        self.assertGreater(current, previous)
        self.assertEqual(92.0, updated["quality_assessment"]["scores"]["user_feedback"])
    def test_graph_is_concept_first_and_keeps_paper_provenance_on_edges(self) -> None:
        graph = self.orchestrator.run("graduate_cross_domain")["graph"]
        self.assertEqual("paper_grounded_concept_graph", graph["graph_type"])
        self.assertEqual("zh-CN", graph["language"])
        self.assertTrue(graph["nodes"])
        self.assertTrue(all(node["kind"] == "concept" for node in graph["nodes"]))
        self.assertTrue(all(edge["evidence_ids"] for edge in graph["edges"]))
        self.assertTrue(all(edge["evidence_titles"] for edge in graph["edges"]))

    def test_engineering_thresholds_pass(self) -> None:
        report = evaluate_orchestrator(self.orchestrator)
        self.assertEqual(9, report["case_count"])
        self.assertTrue(all(report["thresholds"].values()))

    def test_dashboard_metrics_are_computed_not_hardcoded(self) -> None:
        result = self.orchestrator.run("undergraduate_ai")
        metrics = result["metrics"]
        self.assertGreater(metrics["hallucination_proxy_rate"], 0)
        self.assertLess(metrics["hallucination_proxy_rate"], 100)
        self.assertGreater(metrics["adaptation_accuracy"], 0)
        self.assertLess(metrics["adaptation_accuracy"], 100)
        self.assertGreater(metrics["knowledge_coverage_rate"], 0)
        self.assertLess(metrics["knowledge_coverage_rate"], 100)
        self.assertNotIn("metric_details", metrics)
    def test_explicit_mock_provider_preserves_offline_pipeline(self) -> None:
        result = self.orchestrator.run_with_provider(
            "undergraduate_ai",
            "多智能体科研推理如何降低幻觉？",
            ProviderConfig.from_payload({"provider": "mock"}),
            config="full",
        )
        self.assertEqual("offline_mock", result["provider_run"]["mode"])
        self.assertEqual("local_mock", result["provider_run"]["source_mode"])
        self.assertEqual(
            len(result["papers"]),
            result["provider_run"]["source_counts"]["local_knowledge_base"],
        )
        self.assertEqual(
            len(result["papers"]), result["provider_run"]["selected_paper_count"]
        )
        self.assertEqual(0, result["provider_run"]["usage"]["total_tokens"])


if __name__ == "__main__":
    unittest.main()
