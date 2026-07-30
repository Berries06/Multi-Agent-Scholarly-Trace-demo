from __future__ import annotations

import unittest
from pathlib import Path

from yanhai.agents import IntentPerceptionAgent
from yanhai.graph_rag import GraphRAGLiteEngine
from yanhai.knowledge import KnowledgeBase


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class IntentRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = IntentPerceptionAgent()

    def test_literature_query_routes_to_breadth_search(self) -> None:
        intent = self.agent.perceive("请检索并推荐知识图谱构建相关论文")
        self.assertEqual("literature_retrieval", intent["primary_intent"])
        self.assertEqual("graph_breadth", intent["route"])
        self.assertGreaterEqual(intent["confidence"], 0.7)

    def test_analysis_query_routes_to_depth_search(self) -> None:
        intent = self.agent.perceive("分析 GLiNER 如何支持实体抽取")
        self.assertEqual("analysis_reasoning", intent["primary_intent"])
        self.assertEqual("graph_depth", intent["route"])

    def test_idea_query_routes_to_hybrid_drift(self) -> None:
        intent = self.agent.perceive("从现有知识图谱寻找研究空白和 idea")
        self.assertEqual("idea_discovery", intent["primary_intent"])
        self.assertEqual("hybrid_drift", intent["route"])

    def test_unknown_query_falls_back_with_an_explicit_flag(self) -> None:
        intent = self.agent.perceive("xyz")
        self.assertEqual("graph_breadth", intent["route"])
        self.assertTrue(intent["fallback_used"])


class GraphRAGLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        cls.intent_agent = IntentPerceptionAgent()
        cls.engine = GraphRAGLiteEngine(cls.kb)

    def query(self, text: str) -> dict[str, object]:
        return self.engine.query(text, self.intent_agent.perceive(text))

    def test_concept_subgraph_contains_no_document_nodes(self) -> None:
        result = self.query("请推荐知识图谱构建论文")
        graph = result["concept_subgraph"]
        self.assertEqual("knowledge_concepts_only", graph["node_semantics"])
        self.assertTrue(graph["nodes"])
        self.assertTrue(
            all(
                node["entity_type"]
                in {
                    "METHOD",
                    "TASK",
                    "DATASET",
                    "METRIC",
                    "FINDING",
                    "LIMITATION",
                    "DOMAIN",
                }
                for node in graph["nodes"]
            )
        )
        self.assertTrue(all(edge["evidence_ids"] for edge in graph["edges"]))

    def test_depth_route_returns_multi_hop_auditable_paths(self) -> None:
        result = self.query("分析 GLiNER 如何支持实体抽取与知识图谱构建")
        self.assertEqual("graph_depth", result["retrieval_plan"]["route"])
        self.assertTrue(result["paths"])
        self.assertTrue(
            any(len(path["relation_ids"]) >= 2 for path in result["paths"])
        )
        self.assertTrue(
            all(path["evidence_ids"] for path in result["paths"])
        )

    def test_recommendations_are_derived_from_selected_graph_evidence(self) -> None:
        result = self.query("请检索并推荐知识图谱构建相关论文")
        recommendations = result["recommended_papers"]
        self.assertGreaterEqual(len(recommendations), 2)
        self.assertTrue(
            all(item["evidence_ids"] for item in recommendations)
        )
        self.assertTrue(
            all(item["matched_concepts"] for item in recommendations)
        )

    def test_implementation_does_not_mislabel_itself_as_official_runtime(self) -> None:
        result = self.query("寻找研究 idea 和知识空白")
        implementation = result["implementation"]
        self.assertEqual(
            "graphrag-inspired-offline-baseline",
            implementation["current"],
        )
        self.assertEqual(
            "microsoft-graphrag-runtime",
            implementation["not_claimed"],
        )


if __name__ == "__main__":
    unittest.main()
