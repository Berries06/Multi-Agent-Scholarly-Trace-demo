from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.agents import CriticAgent, JudgeAgent, ProposerAgent  # noqa: E402
from yanhai.extraction import PlainTextParser, SchemaGuidedExtractor  # noqa: E402
from yanhai.fresh_kb import FreshPaperKB  # noqa: E402
from yanhai.fresh_pipeline import run_fresh_paper_pipeline  # noqa: E402
from yanhai.models import LearnerProfile, Paper  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"


class FreshPaperDecisionTests(unittest.TestCase):
    """Regression for the critic's evidence-span coverage check.

    The check used to compare the English canonical name against the evidence
    text, so entities matched via Chinese aliases were falsely rejected. It now
    uses mention linkage with an alias-aware fallback.
    """

    def _adjudicate(self, text: str) -> list[dict[str, object]]:
        document = PlainTextParser().parse_text(
            text,
            paper_id="cn-paper",
            fallback_title="cn-paper",
        )
        extraction = SchemaGuidedExtractor.from_path(SCHEMA_PATH).extract_documents(
            [document]
        ).to_dict()
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        kb = FreshPaperKB(extraction, schema)
        paper = Paper(
            paper_id="cn-paper",
            title="cn-paper",
            authors=(),
            year=2026,
            published="",
            categories=(),
            summary="",
            concepts=(),
            source_url="test",
        )
        claims = ProposerAgent().propose(kb, [paper])
        claims = CriticAgent().critique(claims, kb)
        claims = JudgeAgent().adjudicate(claims, kb)
        return [claim.to_dict() for claim in claims]

    def test_chinese_alias_relation_is_not_falsely_rejected_by_span_check(self) -> None:
        claims = self._adjudicate(
            "我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。"
        )
        target = next(
            claim
            for claim in claims
            if claim["source"] == "multi-agent debate"
            and claim["target"] == "hallucination control"
        )
        self.assertEqual("accepted", target["status"])
        self.assertNotIn(
            "证据跨度没有同时覆盖关系两端实体。",
            target["criticisms"],
        )

    def test_unsupported_absolute_claim_is_still_rejected(self) -> None:
        claims = self._adjudicate(
            "我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。"
        )
        pressure = next(claim for claim in claims if claim["relation"] == "guarantees")
        self.assertEqual("rejected", pressure["status"])
        self.assertFalse(pressure["evidence_ids"])


class FreshPipelineTests(unittest.TestCase):
    def test_full_pipeline_generates_resources_with_evidence_guard(self) -> None:
        profile = LearnerProfile.from_dict(
            json.loads(
                (PROJECT_ROOT / "data" / "profiles" / "profiles.json").read_text(
                    encoding="utf-8"
                )
            )[0]
        )
        result = run_fresh_paper_pipeline(
            paper_id="pipeline-paper",
            title="pipeline",
            text="我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。",
            profile=profile,
            schema_path=SCHEMA_PATH,
        )
        self.assertEqual(0, result["summary"]["accepted_without_evidence_count"])
        self.assertGreaterEqual(result["summary"]["accepted_count"], 1)
        for key in ("briefing", "practical_guide", "quiz", "blue_ocean"):
            self.assertIn(key, result["resources"])


if __name__ == "__main__":
    unittest.main()
