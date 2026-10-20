from __future__ import annotations

import json
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.agents import CriticAgent, JudgeAgent, ProposerAgent  # noqa: E402
from yanhai.extraction import PlainTextParser, PyPDFParser, SchemaGuidedExtractor  # noqa: E402
from yanhai.fresh_kb import FreshPaperKB  # noqa: E402
from yanhai.fresh_pipeline import run_fresh_document_pipeline, run_fresh_paper_pipeline  # noqa: E402
from yanhai.models import LearnerProfile, Paper  # noqa: E402
from yanhai.skills.academic_researcher import verify_citation  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"


class FreshPaperMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        document = PlainTextParser().parse_text(
            "我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。",
            paper_id="metadata-paper",
            fallback_title="Metadata source",
            source_url="member-pasted-text",
        )
        self.extraction = SchemaGuidedExtractor.from_path(SCHEMA_PATH).extract_documents(
            [document]
        ).to_dict()

    def test_extracted_document_has_paper_metadata_without_invented_bibliography(self) -> None:
        kb = FreshPaperKB(self.extraction, self.schema)
        paper = kb.paper_by_id["metadata-paper"]
        self.assertIs(paper, kb.papers[0])
        self.assertIsInstance(paper, Paper)
        self.assertEqual("Metadata source", paper.title)
        self.assertEqual("member-pasted-text", paper.source_url)
        self.assertEqual(0, paper.year)
        self.assertEqual((), paper.authors)
        self.assertEqual("", paper.published)
        for evidence_id in kb.evidence_by_id:
            self.assertIn(kb.paper_id_for_evidence(evidence_id), kb.paper_by_id)

    def test_supplied_bibliography_is_preserved(self) -> None:
        self.extraction["papers"][0].update(
            authors=["A. Researcher"], year=2024, published="Example venue",
            categories=["cs.AI"], summary="A benchmark study.",
            concepts=["multi-agent debate"], external_ids={"DOI": "10.1234/example"},
            source_type="preprint", authority_tier=3,
        )
        paper = FreshPaperKB(self.extraction, self.schema).paper_by_id["metadata-paper"]
        self.assertEqual(("A. Researcher",), paper.authors)
        self.assertEqual(2024, paper.year)
        self.assertEqual("Example venue", paper.published)
        self.assertEqual(("cs.AI",), paper.categories)
        self.assertEqual("A benchmark study.", paper.summary)
        self.assertEqual(("multi-agent debate",), paper.concepts)
        self.assertEqual({"DOI": "10.1234/example"}, paper.external_ids)
        self.assertEqual("preprint", paper.source_type)
        self.assertEqual(3, paper.authority_tier)

    def test_critic_actually_checks_the_source_metadata(self) -> None:
        kb = FreshPaperKB(self.extraction, self.schema)
        claims = ProposerAgent().propose(kb, kb.papers)
        with patch("yanhai.agents.verify_citation", wraps=verify_citation) as verifier:
            CriticAgent().critique(claims, kb)
        self.assertGreater(verifier.call_count, 0)
        for call in verifier.call_args_list:
            self.assertEqual(kb.paper_by_id["metadata-paper"].to_dict(), call.args[0])


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
        paper = kb.paper_by_id["cn-paper"]
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
    def test_uploaded_pdf_keeps_paper_identity_and_page_sources(self) -> None:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        for text in (
            "Multi-agent debate improves hallucination control.",
            "Retrieval-augmented generation uses knowledge graph.",
        ):
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({
                    NameObject("/F1"): DictionaryObject({
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica"),
                    }),
                }),
            })
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = content
        payload = io.BytesIO()
        writer.write(payload)
        document = PyPDFParser().parse_bytes(
            payload.getvalue(), paper_id="two-page-upload", title="Two-page fixture",
        )
        profile = LearnerProfile.from_dict(json.loads(
            (PROJECT_ROOT / "data/profiles/profiles.json").read_text(encoding="utf-8")
        )[0])
        result = run_fresh_document_pipeline(
            document=document, profile=profile, schema_path=SCHEMA_PATH,
        )
        self.assertEqual({"page-001", "page-002"}, set(result["document"]["sections"]))
        self.assertEqual({"page-001", "page-002"}, {
            span["section_id"] for span in result["extraction"]["evidence"]
        })
        self.assertEqual({"two-page-upload"}, {
            span["paper_id"] for span in result["extraction"]["evidence"]
        })
        self.assertEqual("member-uploaded-pdf", result["extraction"]["papers"][0]["source_url"])
        self.assertEqual(0, result["summary"]["accepted_without_evidence_count"])
        self.assertGreater(result["summary"]["accepted_count"], 0)

    def test_full_pipeline_generates_resources_with_evidence_guard(self) -> None:
        profile = LearnerProfile.from_dict(
            json.loads(
                (PROJECT_ROOT / "data" / "profiles" / "profiles.json").read_text(
                    encoding="utf-8"
                )
            )[0]
        )
        original_propose = ProposerAgent.propose
        with patch(
            "yanhai.fresh_pipeline.ProposerAgent.propose",
            autospec=True,
            side_effect=original_propose,
        ) as proposer:
            result = run_fresh_paper_pipeline(
                paper_id="pipeline-paper",
                title="pipeline",
                text="我们提出一种多智能体辩论机制，用于减少检索增强生成中的幻觉。",
                profile=profile,
                schema_path=SCHEMA_PATH,
            )
        _, kb, papers = proposer.call_args.args
        self.assertIs(kb.paper_by_id["pipeline-paper"], papers[0])
        self.assertEqual(0, result["summary"]["accepted_without_evidence_count"])
        self.assertGreaterEqual(result["summary"]["accepted_count"], 1)
        for key in ("briefing", "practical_guide", "quiz", "blue_ocean"):
            self.assertIn(key, result["resources"])


if __name__ == "__main__":
    unittest.main()
