from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.store import KnowledgeGraphStore  # noqa: E402


class VerticalAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")

    def test_vertical_slice_has_thirty_peer_reviewed_papers(self) -> None:
        self.assertEqual(30, len(self.kb.vertical_corpus.papers))
        self.assertEqual(8, len(self.kb.vertical_corpus.evidence_papers))
        self.assertTrue(
            all(
                "aclanthology.org" in paper.source_url
                for paper in self.kb.vertical_corpus.evidence_papers
            )
        )
        metadata_only = [
            record
            for record in self.kb.vertical_corpus.paper_records.values()
            if record["evidence_tier"] == "metadata_only"
        ]
        self.assertEqual(22, len(metadata_only))
        self.assertTrue(
            all(record["exclude_from_evidence_graph"] for record in metadata_only)
        )

    def test_registry_exposes_three_reproducible_vertical_slices(self) -> None:
        expected = {
            "scientific-ie-kg": 30,
            "materials-discovery-gnn": 30,
            "educational-knowledge-tracing": 30,
        }
        self.assertEqual(set(expected), set(self.kb.domain_configs))
        for domain_id, paper_count in expected.items():
            kb = KnowledgeBase(
                PROJECT_ROOT / "data" / "knowledge",
                domain_id,
            )
            self.assertEqual(paper_count, len(kb.vertical_corpus.papers))
            self.assertTrue(
                all(
                    kb.vertical_corpus.paper_records[paper.paper_id][
                        "peer_reviewed"
                    ]
                    for paper in kb.vertical_corpus.papers
                )
            )

    def test_metadata_only_records_cannot_create_graph_evidence(self) -> None:
        for domain_id in self.kb.domain_configs:
            kb = KnowledgeBase(
                PROJECT_ROOT / "data" / "knowledge",
                domain_id,
            )
            graph_paper_ids = {
                item["paper_id"]
                for item in kb.extracted_paper_graph()["papers"]
            }
            metadata_only_ids = {
                paper_id
                for paper_id, record in kb.vertical_corpus.paper_records.items()
                if record["evidence_tier"] == "metadata_only"
            }
            self.assertTrue(graph_paper_ids)
            self.assertTrue(metadata_only_ids)
            self.assertTrue(graph_paper_ids.isdisjoint(metadata_only_ids))
            metadata_id = next(iter(metadata_only_ids))
            self.assertFalse(kb.evidence_is_valid(metadata_id))
            self.assertEqual([], kb.evidence_details([metadata_id]))

    def test_every_vertical_slice_builds_a_grounded_graph(self) -> None:
        for domain_id in self.kb.domain_configs:
            kb = KnowledgeBase(
                PROJECT_ROOT / "data" / "knowledge",
                domain_id,
            )
            payload = kb.extracted_paper_graph()
            evidence_ids = {
                item["evidence_id"] for item in payload["evidence"]
            }
            self.assertGreaterEqual(len(payload["entities"]), 10)
            self.assertGreaterEqual(len(payload["relations"]), 15)
            self.assertEqual(
                1.0,
                payload["audit"]["quality"]["relation_evidence_coverage"],
            )
            self.assertTrue(
                all(
                    relation["evidence_ids"]
                    and set(relation["evidence_ids"]).issubset(evidence_ids)
                    for relation in payload["relations"]
                )
            )

    def test_each_relation_keeps_evidence_span_provenance(self) -> None:
        payload = self.kb.extracted_paper_graph()
        evidence_ids = {item["evidence_id"] for item in payload["evidence"]}
        self.assertGreaterEqual(len(payload["relations"]), 20)
        self.assertTrue(
            all(
                relation["evidence_ids"]
                and set(relation["evidence_ids"]).issubset(evidence_ids)
                for relation in payload["relations"]
            )
        )

    def test_sqlite_store_rebuilds_all_core_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "knowledge.db"
            counts = KnowledgeGraphStore(path).rebuild(
                self.kb.extracted_paper_graph()
            )
            self.assertEqual(8, counts["papers"])
            self.assertGreater(counts["entities"], 0)
            self.assertGreater(counts["relations"], 0)
            connection = sqlite3.connect(path)
            try:
                stored = connection.execute(
                    "SELECT COUNT(*) FROM relation_evidence"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertGreater(stored, 0)


if __name__ == "__main__":
    unittest.main()
