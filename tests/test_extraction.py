from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import (  # noqa: E402
    PlainTextParser,
    PyPDFParser,
    SchemaGuidedExtractor,
    normalize_name,
)
from yanhai.knowledge import KnowledgeBase  # noqa: E402


class ExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = SchemaGuidedExtractor.from_path(
            PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
        )
        cls.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        cls.result = cls.extractor.extract_papers(cls.kb.papers)
        cls.payload = cls.result.to_dict()

    def test_normalization_is_unicode_and_case_stable(self) -> None:
        self.assertEqual(normalize_name(" Multi-Agent_System "), "multi agent system")
        self.assertEqual(normalize_name("科研 文献"), "科研 文献")

    def test_entities_are_merged_by_canonical_identity(self) -> None:
        names = [item["canonical_name"] for item in self.payload["entities"]]
        self.assertEqual(len(names), len(set(names)))
        multi_agent = next(
            item
            for item in self.payload["entities"]
            if item["canonical_name"] == "multi-agent system"
        )
        self.assertGreaterEqual(len(multi_agent["mentions"]), 2)

    def test_every_relation_has_valid_endpoints_and_evidence(self) -> None:
        entity_ids = {item["entity_id"] for item in self.payload["entities"]}
        evidence_ids = {item["evidence_id"] for item in self.payload["evidence"]}
        self.assertGreater(len(self.payload["relations"]), 0)
        for relation in self.payload["relations"]:
            self.assertIn(relation["source_id"], entity_ids)
            self.assertIn(relation["target_id"], entity_ids)
            self.assertTrue(relation["evidence_ids"])
            self.assertTrue(set(relation["evidence_ids"]).issubset(evidence_ids))

    def test_generic_cooccurrence_is_not_auto_accepted(self) -> None:
        generic = [
            item
            for item in self.payload["relations"]
            if item["relation_type"] == "RELATED_TO"
        ]
        self.assertTrue(generic)
        self.assertTrue(all(item["status"] == "needs_review" for item in generic))

    def test_plain_text_parser_preserves_sections(self) -> None:
        document = PlainTextParser().parse_text(
            "# Example\n\n## Method\nMulti-agent debate improves factuality.",
            paper_id="example",
            fallback_title="fallback",
        )
        self.assertEqual("Example", document.title)
        self.assertIn("method", document.sections)

    def test_graph_exposes_provenance_edges_and_communities(self) -> None:
        edges = self.payload["graph"]["edges"]
        self.assertTrue(any(edge["label"] == "MENTIONS" for edge in edges))
        self.assertTrue(self.payload["communities"])
        self.assertEqual(
            1.0,
            self.payload["audit"]["quality"]["relation_evidence_coverage"],
        )


class PyPDFBytesTests(unittest.TestCase):
    def test_parse_bytes_preserves_page_sections(self) -> None:
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")
        pdfs = sorted(
            (PROJECT_ROOT / "papers" / "scientific-ie-kg").glob("*.pdf")
        )
        if not pdfs:
            self.skipTest("no local sample PDFs")
        document = PyPDFParser().parse_bytes(
            pdfs[0].read_bytes(), paper_id="pdf-test", title="pdf-test"
        )
        self.assertEqual("pdf-test", document.paper_id)
        self.assertTrue(document.sections)
        self.assertTrue(
            all(name.startswith("page-") for name in document.sections)
        )


if __name__ == "__main__":
    unittest.main()
