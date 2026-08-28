from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.evaluation import evaluate_orchestrator  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.providers import ProviderConfig, ProviderError  # noqa: E402


class OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)

    def test_three_synthetic_profiles_are_available(self) -> None:
        profiles = self.orchestrator.list_profiles()
        self.assertEqual(3, len(profiles))
        self.assertTrue(all(profile["synthetic"] for profile in profiles))

    def test_only_three_core_decision_agents_are_in_the_trace(self) -> None:
        result = self.orchestrator.run("undergraduate_ai")
        self.assertEqual(3, len(result["agent_trace"]))
        self.assertEqual(
            {"关联提出", "反证与约束", "置信裁决"},
            {step["role"] for step in result["agent_trace"]},
        )
        self.assertEqual(3, result["core_method"]["agent_count"])
        self.assertEqual(5, result["core_method"]["system_agent_count"])
        self.assertEqual(2, len(result["specialist_agent_trace"]))
        self.assertEqual(3, len(result["service_trace"]))

    def test_intent_and_extraction_specialists_are_exposed(self) -> None:
        result = self.orchestrator.run(
            "undergraduate_ai",
            "分析 GLiNER 如何支持实体抽取",
        )
        specialist_roles = {
            item["role"] for item in result["specialist_agent_trace"]
        }
        self.assertEqual(
            {"论文解析与知识建图", "意图识别与检索路由"},
            specialist_roles,
        )
        self.assertEqual(
            "graph_depth",
            result["graph_retrieval"]["retrieval_plan"]["route"],
        )
        self.assertEqual(
            result["graph_retrieval"]["answer"],
            result["assistant_response"],
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
        self.assertTrue(
            all(
                self.orchestrator.kb.evidence_is_valid(evidence_id)
                for claim in accepted
                for evidence_id in claim["evidence_ids"]
            )
        )

    def test_three_resource_types_and_grounded_profile_focus_are_generated(
        self,
    ) -> None:
        result = self.orchestrator.run("undergraduate_ai")
        resources = result["resources"]
        self.assertIn("briefing", resources)
        self.assertIn("practical_guide", resources)
        self.assertIn("quiz", resources)
        self.assertGreaterEqual(len(resources["quiz"]["items"]), 2)
        self.assertEqual(
            set(result["profile"]["interests"]).intersection(
                {"论文信息抽取", "知识图谱", "证据溯源"}
            ),
            {"论文信息抽取", "知识图谱", "证据溯源"},
        )
        self.assertTrue(resources["coverage_provenance"])

    def test_feedback_changes_target_difficulty(self) -> None:
        hard = self.orchestrator.run_with_feedback(
            "graduate_cross_domain", "too_hard"
        )
        easy = self.orchestrator.run_with_feedback(
            "graduate_cross_domain", "too_easy"
        )
        self.assertEqual(2, hard["diagnosis"]["target_difficulty"])
        self.assertEqual(4, easy["diagnosis"]["target_difficulty"])

    def test_remote_provider_failure_returns_preserved_offline_baseline(self) -> None:
        class FailingProvider:
            def complete_json(self, *args, **kwargs):
                raise ProviderError("research_plan：模拟结构化输出失败。")

        config = ProviderConfig.from_payload(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "test-key",
            }
        )
        events: list[dict[str, object]] = []
        with patch("yanhai.orchestrator.create_provider", return_value=FailingProvider()):
            result = self.orchestrator.run_with_provider(
                "graduate_cross_domain",
                "多智能体如何减少抽取错误？",
                provider_config=config,
                on_step=events.append,
            )

        self.assertEqual("degraded_offline", result["provider_run"]["mode"])
        self.assertTrue(result["provider_run"]["degraded"])
        self.assertGreater(len(result["papers"]), 0)
        self.assertGreater(len(result["claims"]), 0)
        self.assertIn("research_plan", result["provider_run"]["warnings"][0])
        progress = [event for event in events if event.get("event_type") == "progress"]
        self.assertEqual("baseline", progress[0]["phase"])
        self.assertEqual("degraded", progress[-1]["state"])

    def test_offline_provider_emits_real_milestone_progress(self) -> None:
        events: list[dict[str, object]] = []
        config = ProviderConfig.from_payload(
            {"provider": "mock", "model": "offline-rules"}
        )
        result = self.orchestrator.run_with_provider(
            "graduate_cross_domain",
            "多智能体如何减少抽取错误？",
            provider_config=config,
            on_step=events.append,
            include_ablation=False,
        )

        progress = [event for event in events if event.get("event_type") == "progress"]
        self.assertEqual("offline_mock", result["provider_run"]["mode"])
        self.assertEqual("diagnosis", progress[0]["phase"])
        self.assertEqual(97, progress[-1]["percent"])
        self.assertEqual("resources", progress[-1]["phase"])
        self.assertNotIn("ablation", result)

    def test_extracted_graph_contains_paper_evidence_entity_chain(self) -> None:
        graph = self.orchestrator.run("graduate_cross_domain")[
            "knowledge_graph"
        ]["graph"]
        self.assertTrue(any(node["kind"] == "paper" for node in graph["nodes"]))
        self.assertTrue(any(node["kind"] == "evidence" for node in graph["nodes"]))
        self.assertTrue(any(edge["label"] == "CONTAINS" for edge in graph["edges"]))
        self.assertTrue(any(edge["label"] == "MENTIONS" for edge in graph["edges"]))

    def test_ablation_and_graph_ideas_are_exposed(self) -> None:
        result = self.orchestrator.run("graduate_cross_domain")
        variants = {
            item["variant_id"]: item for item in result["ablation"]["variants"]
        }
        self.assertEqual(
            {
                "rule_program",
                "single_pass",
                "homogeneous_vote",
                "evidence_triad",
            },
            set(variants),
        )
        self.assertGreater(
            variants["evidence_triad"]["metrics"]["accepted_precision"],
            variants["single_pass"]["metrics"]["accepted_precision"],
        )
        triad = variants["evidence_triad"]
        self.assertEqual(24, result["ablation"]["case_count"])
        self.assertLess(triad["metrics"]["accepted_precision"], 1.0)
        self.assertLess(triad["metrics"]["gold_recall"], 1.0)
        self.assertGreater(
            triad["metrics"]["unsupported_acceptance_rate"],
            0.0,
        )
        self.assertEqual(
            "structural_guardrail",
            triad["metrics"]["evidence_coverage_kind"],
        )
        self.assertEqual(
            {"B013", "B014", "B019", "B020"},
            {
                item["claim_id"]
                for item in triad["cases"]
                if not item["correct"]
            },
        )
        self.assertGreaterEqual(
            len(result["graph_insights"]["research_ideas"]),
            1,
        )
        self.assertTrue(
            all(
                idea["novelty_status"] == "unverified"
                for idea in result["graph_insights"]["research_ideas"]
            )
        )

    def test_engineering_thresholds_pass(self) -> None:
        report = evaluate_orchestrator(self.orchestrator)
        self.assertEqual(9, report["case_count"])
        self.assertTrue(all(report["thresholds"].values()))

if __name__ == "__main__":
    unittest.main()
