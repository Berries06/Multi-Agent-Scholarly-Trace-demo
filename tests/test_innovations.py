from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai import ScholarlyTraceOrchestrator, get_preset  # noqa: E402


class InnovationPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)

    def test_default_api_remains_legacy(self) -> None:
        result = self.orchestrator.run("undergraduate_ai")
        self.assertEqual("legacy", result["system_config"]["name"])
        self.assertEqual(3, len(result["agent_trace"]))
        self.assertFalse(result["system_config"]["flags"]["sentence_provenance"])
        self.assertEqual([], result["innovations"]["hypotheses"])
        self.assertFalse(result["resources"]["blue_ocean"]["enabled"])

    def test_full_preset_exposes_research_mechanisms(self) -> None:
        result = self.orchestrator.run(
            "undergraduate_ai",
            "请分析该领域的研究空白并提出待验证假设。",
            config="full",
        )
        self.assertEqual("full", result["system_config"]["name"])
        self.assertGreater(result["innovations"]["debate_view_count"], 0)
        self.assertGreater(result["innovations"]["falsification"]["rounds"], 0)
        self.assertEqual(3, len(result["innovations"]["hypotheses"]))
        self.assertGreater(len(result["innovations"]["discovery"]["timeline"]), 0)
        self.assertTrue(result["innovations"]["knowledge_state"]["concepts"])

    def test_sentence_level_provenance_is_traceable(self) -> None:
        result = self.orchestrator.run("graduate_cross_domain", config="full")
        supported = [
            claim for claim in result["claims"] if claim["evidence_ids"]
        ]
        self.assertTrue(all(claim["evidence_spans"] for claim in supported))
        valid_ids = set(self.orchestrator.kb.paper_by_id)
        self.assertTrue(
            all(
                span["paper_id"] in valid_ids
                for claim in supported
                for span in claim["evidence_spans"]
            )
        )
        self.assertTrue(
            any(edge["evidence_spans"] for edge in result["graph"]["edges"])
        )

    def test_ablation_changes_only_requested_switch(self) -> None:
        full = get_preset("full").flags.to_dict()
        ablated = get_preset("no_falsification").flags.to_dict()
        changed = {key for key in full if full[key] != ablated[key]}
        self.assertEqual({"sequential_falsification"}, changed)

    def test_no_judge_ablation_exposes_pressure_claim(self) -> None:
        result = self.orchestrator.run("undergraduate_ai", config="no_judge")
        pressure = next(
            claim for claim in result["claims"] if claim["relation"] == "guarantees"
        )
        self.assertEqual("accepted", pressure["status"])
        self.assertGreater(result["metrics"]["hallucination_proxy_rate"], 0)

    def test_pressure_claim_uses_explicit_abstention(self) -> None:
        result = self.orchestrator.run("enterprise_analyst", config="full")
        pressure = next(
            claim for claim in result["claims"] if claim["relation"] == "guarantees"
        )
        self.assertEqual("abstained", pressure["status"])
        self.assertGreater(len(pressure["falsification_steps"]), 0)
        graph_labels = {node["label"] for node in result["graph"]["nodes"]}
        self.assertNotIn("零幻觉科研结论", graph_labels)

    def test_performance_probe_contains_real_stage_timings(self) -> None:
        result = self.orchestrator.run("undergraduate_ai", config="full")
        probe = result["performance"]
        self.assertEqual("time.perf_counter_ns", probe["clock"])
        self.assertGreater(probe["total_ms"], 0)
        self.assertTrue(all(stage["duration_ms"] >= 0 for stage in probe["stages"]))
        self.assertEqual(len(result["claims"]), probe["counters"]["claims_proposed"])


if __name__ == "__main__":
    unittest.main()
