"""通用抽取（`src/yanhai/fresh_extraction.py`）的测试。

这一层存在的理由只有一个：内置词表里的 188 个概念来自仓库那五批样本文献，
用户自己研究方向上的论文一个都命中不了，导入之后零实体零关系零证据，
工作台跑起来什么也说不出来。所以这里守三件事：

1. 词表外的论文也能抽出实体与关系，而且**证据偏移能切回原文**；
2. 关系类型仍走共享本体，候选置信度压在接收线以下（一律待人复核）；
3. 词表内的论文不走这条路，抽取器仍报 `schema-guided-pattern`。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import PlainTextParser, SchemaGuidedExtractor  # noqa: E402
from yanhai.fresh_extraction import extract_documents_generic  # noqa: E402
from yanhai.fresh_pipeline import run_fresh_paper_pipeline  # noqa: E402
from yanhai.models import LearnerProfile  # noqa: E402

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"

#: 一篇"蛋白质相分离"的摘要：内置词表里没有任何一个概念能命中。
OFF_VOCABULARY = (
    "Protein phase separation and gelation in biomolecular condensates. "
    "We train a coacervate model on the FUS-LC dataset. "
    "The coacervate model achieves a saturation concentration of 12 micromolar. "
    "We compare against a single-chain RGG baseline. "
    "Titration shows that the sticker-and-spacer architecture improves clustering. "
)

#: 材料领域的摘要：内置词表能命中，抽取器不该回退。
IN_VOCABULARY = (
    "Graph neural networks for materials property prediction. "
    "We train a crystal graph convolutional network on the Materials Project dataset. "
    "The model achieves a mean absolute error of 0.039 eV per atom on formation energy. "
    "The angular symmetry functions improve accuracy over the radial basis function baseline."
)


def _profile() -> LearnerProfile:
    return LearnerProfile(
        profile_id="test-profile",
        name="测试学习者",
        persona="跑测试用的画像",
        education="硕士",
        role="研究者",
        goal="验证通用抽取这条路能不能走通",
        interests=["图神经网络"],
        knowledge_scores={"领域基础": 50},
        preferred_style="结构化",
        expected_difficulty=3,
        required_concepts=["证据判断"],
        synthetic=True,
    )


class GenericExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.extractor = SchemaGuidedExtractor.from_path(SCHEMA_PATH)

    def document(self, text: str):
        return PlainTextParser().parse_text(
            text,
            paper_id="oov-paper",
            fallback_title="Protein phase separation",
            source_url="pasted-text",
        )

    def test_builtin_schema_finds_nothing_in_an_off_vocabulary_paper(self) -> None:
        """先确认问题真的存在：内置词表在这篇论文上一条关系都抽不出来。"""
        guided = self.extractor.extract_documents([self.document(OFF_VOCABULARY)])
        self.assertEqual([], [relation.to_dict() for relation in guided.relations])

    def test_generic_extraction_mines_entities_and_relations(self) -> None:
        document = self.document(OFF_VOCABULARY)
        payload = extract_documents_generic(self.extractor, [document]).to_dict()
        self.assertGreater(len(payload["entities"]), 0, "一个实体都没挖出来")
        self.assertGreater(len(payload["relations"]), 0, "一条关系都没挖出来")

        entity_types = {item["entity_type"] for item in payload["entities"]}
        allowed = {"DATASET", "METHOD", "METRIC", "TASK", "FINDING", "DOMAIN", "LIMITATION"}
        self.assertTrue(entity_types.issubset(allowed), entity_types)

        names = {item["canonical_name"] for item in payload["entities"]}
        self.assertTrue(
            any("coacervate" in name.lower() or "fus" in name.lower() for name in names),
            names,
        )

        schema_types = set(self.extractor.schema["relation_types"])
        for relation in payload["relations"]:
            self.assertIn(relation["relation_type"], schema_types)
            self.assertTrue(relation["evidence_ids"], relation)
            # 置信度压在接收线以下：这些都是待人复核的候选，机器不替人决定
            self.assertLess(relation["confidence"], self.extractor.accept_threshold)

    def test_evidence_offsets_cut_back_to_the_source_text(self) -> None:
        """证据必须是原文里的一段，偏移要对得上——对不上就等于编。"""
        document = self.document(OFF_VOCABULARY)
        payload = extract_documents_generic(self.extractor, [document]).to_dict()
        sections = {"title": document.title, **document.sections}
        self.assertTrue(payload["evidence"])
        for span in payload["evidence"]:
            text = sections[span["section_id"]]
            self.assertEqual(text[span["char_start"] : span["char_end"]], span["text"])

    def test_pipeline_falls_back_when_the_schema_finds_no_relations(self) -> None:
        profile = _profile()
        off = run_fresh_paper_pipeline(
            paper_id="oov-paper",
            title="Protein phase separation",
            text=OFF_VOCABULARY,
            profile=profile,
            schema_path=SCHEMA_PATH,
        )
        self.assertEqual("generic-pattern", off["summary"]["extractor"])
        self.assertGreater(off["summary"]["candidate_relation_count"], 0)

    def test_pipeline_keeps_the_schema_path_when_it_does_find_relations(self) -> None:
        """词表抽得出来就别换路子——换不换只看"有没有抽到关系"。"""
        from unittest.mock import patch

        from yanhai.extraction import (
            EvidenceSpan,
            ExtractedEntity,
            ExtractedRelation,
            ExtractionResult,
        )

        evidence = EvidenceSpan(
            evidence_id="evidence:toy:abc:0",
            paper_id="toy-paper",
            section_id="title",
            sentence_index=0,
            text="We evaluate SCIIE on SCIERC.",
            char_start=0,
            char_end=28,
        )
        source = ExtractedEntity(
            entity_id="entity:source", canonical_name="SCIIE", entity_type="METHOD"
        )
        target = ExtractedEntity(
            entity_id="entity:target", canonical_name="SCIERC", entity_type="DATASET"
        )
        relation = ExtractedRelation(
            relation_id="relation:toy",
            source_id="entity:source",
            target_id="entity:target",
            relation_type="EVALUATES_ON",
            evidence_ids=[evidence.evidence_id],
            confidence=0.8,
        )
        fake = ExtractionResult(
            schema_version="test",
            papers=[
                {
                    "paper_id": "toy-paper",
                    "title": "Toy paper",
                    "source_url": "pasted-text",
                }
            ],
            entities=[source, target],
            relations=[relation],
            evidence=[evidence],
            communities=[],
            audit={"proposer": {"method": "schema-guided-pattern"}},
        )
        with patch.object(SchemaGuidedExtractor, "extract_documents", return_value=fake):
            result = run_fresh_paper_pipeline(
                paper_id="toy-paper",
                title="Toy paper",
                text=IN_VOCABULARY,
                profile=_profile(),
                schema_path=SCHEMA_PATH,
            )
        self.assertEqual("schema-guided-pattern", result["summary"]["extractor"])
        self.assertEqual(1, result["summary"]["candidate_relation_count"])


if __name__ == "__main__":
    unittest.main()
