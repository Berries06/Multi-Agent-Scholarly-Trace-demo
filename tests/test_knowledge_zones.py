from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.models import Paper  # noqa: E402


class KnowledgeZoneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")

    def candidate(self) -> Paper:
        return Paper(
            paper_id="candidate-1",
            title="Candidate Source",
            authors=("Researcher",),
            year=2026,
            published="2026-07-01",
            categories=("cs.AI",),
            summary="A candidate source awaiting verification.",
            concepts=("evidence",),
            source_url="https://example.org/candidate-1",
        )

    def test_local_seed_papers_are_verified(self) -> None:
        self.assertTrue(
            all(paper.knowledge_status == "verified" for paper in self.kb.papers)
        )
        self.assertEqual([], self.kb.knowledge_zones()["candidate"])

    def test_candidate_can_be_staged_and_promoted_with_review_note(self) -> None:
        staged = self.kb.stage_candidates([self.candidate()])
        self.assertEqual("candidate", staged[0]["status"])
        self.assertNotIn("candidate-1", self.kb.paper_by_id)
        verified = self.kb.promote_candidate(
            "candidate-1",
            "来源和摘要已经人工复核。",
        )
        self.assertEqual("verified", verified.knowledge_status)
        self.assertIn("candidate-1", self.kb.paper_by_id)
        self.assertEqual([], self.kb.knowledge_zones()["candidate"])

    def test_candidate_cannot_be_promoted_without_review_note(self) -> None:
        self.kb.stage_candidates([self.candidate()])
        with self.assertRaises(ValueError):
            self.kb.promote_candidate("candidate-1", "")


if __name__ == "__main__":
    unittest.main()
