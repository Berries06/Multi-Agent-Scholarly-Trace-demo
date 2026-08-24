from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_ROOT / "config" / "literature_corpus_100.json"
AUDIT_PATH = PROJECT_ROOT / "artifacts" / "literature" / "literature_audit_100.json"


class LiteratureCorpusTests(unittest.TestCase):
    def test_frozen_corpus_has_one_hundred_unique_papers(self) -> None:
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        papers = corpus["papers"]
        self.assertEqual(len(papers), 100)
        self.assertEqual(len({paper["id"] for paper in papers}), 100)
        self.assertEqual(len({paper["title"] for paper in papers}), 100)
        self.assertEqual(
            Counter(paper["bucket"] for paper in papers),
            {
                "scientific_ie": 15,
                "verification": 15,
                "rag": 15,
                "multi_agent": 15,
                "graph_temporal": 15,
                "personalization": 10,
                "evaluation": 10,
                "research_systems": 5,
            },
        )
        for paper in papers:
            self.assertTrue(paper["gap"])
            self.assertTrue(paper["hypotheses"])

    def test_audit_matches_corpus_and_records_targeted_reading(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        corpus_hash = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
        self.assertEqual(audit["corpus_sha256"], corpus_hash)
        self.assertEqual(audit["paper_count"], 100)
        self.assertEqual(audit["read_status_counts"], {"targeted_sections_read": 100})
        self.assertEqual(len(audit["papers"]), 100)
        for paper in audit["papers"]:
            self.assertEqual(paper["read_status"], "targeted_sections_read")
            source_hash = paper.get("pdf_sha256") or paper.get("html_sha256")
            self.assertIsNotNone(source_hash)
            self.assertEqual(len(source_hash), 64)
            self.assertGreater(paper["text_chars"], 0)
            self.assertIn("abstract", paper["sections_found"])
            self.assertIn("conclusion", paper["sections_found"])


if __name__ == "__main__":
    unittest.main()
