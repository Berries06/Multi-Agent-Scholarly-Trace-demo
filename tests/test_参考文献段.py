"""参考文献段识别（信号 A：段落标题；信号 B：引文式句子占比）的单元测试。

判据本体在 ``src/yanhai/extraction.py``：``reference_region`` / ``citation_style_sentence_share``
/ ``looks_like_citation_style``。这里只测纯函数与抽取器的开关，不碰库、不碰网络。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import (  # noqa: E402
    REFERENCE_CITATION_SHARE,
    REFERENCE_MIN_SENTENCES,
    SchemaGuidedExtractor,
    ScientificDocument,
    citation_style_sentence_share,
    layout_signal_applies,
    looks_like_citation_style,
    parser_skips_reference_judgement,
    reference_layout_page_floor,
    reference_page_number,
    reference_page_total,
    reference_region,
)

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"

#: 一段引文式写法（参考文献条目）。信号 B 就是数这类句子占多少。
REFERENCE_ENTRIES = "\n".join(
    [
        "Ahmed, S., and Smith, J. 2021. Relation extraction with graphs. "
        "In Proceedings of ACL, pages 1–10. https://doi.org/10.1000/xyz.",
        "Chen, L. et al. 2019. Knowledge graph embedding. vol. 12, pp. 33–45.",
        "Davis, P. 2020. Named entity recognition for materials. arXiv preprint arXiv:2001.00001.",
        "Evans, R. 2018. Document-level relation extraction. In Proceedings of EMNLP.",
        "Frank, T. et al. 2022. Scientific information extraction. Journal of NLP.",
        "Gupta, M. 2023. Polymer property extraction. Bioinformatics, 39(1):1–9.",
        "Hansen, K. 2021. Coreference resolution. In Proceedings of NAACL.",
    ]
)

#: 一段正常正文（没有任何引文式写法）。
BODY_TEXT = "\n".join(
    [
        "We propose a new framework for polymer property extraction.",
        "The framework reads full text articles and produces a knowledge graph.",
        "Each article is parsed into pages and each page is split into sentences.",
        "The extractor then looks up concept aliases in every sentence.",
        "Relations are proposed only when a trigger word sits between two entities.",
        "This keeps the graph small enough for a human to review.",
    ]
)


class ReferenceRegionTests(unittest.TestCase):
    def test_heading_at_start_is_cut_at_heading(self) -> None:
        text = "References\n" + REFERENCE_ENTRIES
        region = reference_region(text)
        self.assertIsNotNone(region)
        assert region is not None
        self.assertEqual(region.char_start, 0)
        self.assertEqual(region.char_end, len(text))
        self.assertIn("title", region.signal)
        self.assertEqual(region.heading.casefold(), "references")

    def test_heading_in_middle_keeps_text_before_it(self) -> None:
        text = BODY_TEXT + "\nReferences\n" + REFERENCE_ENTRIES
        region = reference_region(text)
        self.assertIsNotNone(region)
        assert region is not None
        # 切在标题处，标题之前的正文照旧留着。
        self.assertEqual(region.char_start, text.index("References"))
        self.assertEqual(text[region.char_start : region.char_start + 10], "References")
        self.assertEqual(text[: region.char_start].strip(), BODY_TEXT.strip())

    def test_heading_with_section_number_is_recognised(self) -> None:
        for heading in ("7 References", "7. References", "REFERENCES", "Bibliography", "Works Cited"):
            with self.subTest(heading=heading):
                text = f"{heading}\n" + REFERENCE_ENTRIES
                region = reference_region(text)
                self.assertIsNotNone(region)
                assert region is not None
                self.assertLessEqual(region.char_start, len(heading))

    def test_chinese_headings_are_recognised(self) -> None:
        for heading in ("参考文献", "引用文献", "参考文献（References）"):
            with self.subTest(heading=heading):
                text = f"{heading}\n[1] 张三. 2021. 基于知识图谱的关系抽取. 计算机学报."
                region = reference_region(text)
                self.assertIsNotNone(region)
                assert region is not None
                self.assertEqual(region.char_start, 0)

    def test_body_mention_of_references_is_not_a_heading(self) -> None:
        # 正文里出现 "References to prior work" 不算标题。
        text = BODY_TEXT + "\nReferences to prior work are many, but none of them apply here."
        self.assertIsNone(reference_region(text))
        # "(e.g. references)" 也不算。
        text2 = "We collected cited papers (e.g. references) and sentences from them."
        self.assertIsNone(reference_region(text2))

    def test_layout_signal_catches_page_without_heading(self) -> None:
        # 没有标题，但整页几乎全是参考文献条目：信号 B 兜底。
        # 这一页必须同时落在论文后 1/3 的页面里（第 8/9 页）。
        text = "5113 " + REFERENCE_ENTRIES
        region = reference_region(text, page_number=8, page_total=9)
        self.assertIsNotNone(region)
        assert region is not None
        self.assertEqual(region.signal, "layout")
        self.assertEqual(region.char_start, 0)
        self.assertEqual(region.char_end, len(text))
        self.assertGreaterEqual(region.citation_share, REFERENCE_CITATION_SHARE)

    def test_layout_signal_without_page_position_is_off(self) -> None:
        """页码或全篇页数不知道时信号 B 不生效：位置判不出来就不用这条判据。"""
        text = "5113 " + REFERENCE_ENTRIES
        self.assertIsNone(reference_region(text))
        self.assertIsNone(reference_region(text, page_number=None, page_total=9))
        self.assertIsNone(reference_region(text, page_number=1, page_total=None))

    def test_layout_signal_only_applies_in_the_last_third(self) -> None:
        """位置约束：同一段文字，在论文前 2/3 的页面上不判，在后 1/3 上判。"""
        text = "5113 " + REFERENCE_ENTRIES
        # 9 页的论文：起始页码 = ceil(9 × 2/3) = 6，第 5 页还不算后 1/3。
        self.assertIsNone(reference_region(text, page_number=5, page_total=9))
        region = reference_region(text, page_number=6, page_total=9)
        self.assertIsNotNone(region)
        assert region is not None
        self.assertEqual(region.signal, "layout")

    def test_layout_page_floor_is_ceiling_of_two_thirds(self) -> None:
        expected = {1: 1, 2: 2, 3: 2, 4: 3, 5: 4, 6: 4, 7: 5, 9: 6, 12: 8, 20: 14}
        for total, floor in expected.items():
            with self.subTest(total=total):
                self.assertEqual(floor, reference_layout_page_floor(total))
        self.assertEqual(1, reference_layout_page_floor(0))
        self.assertEqual(1, reference_layout_page_floor(-3))
        self.assertTrue(layout_signal_applies(page_number=6, page_total=9))
        self.assertFalse(layout_signal_applies(page_number=5, page_total=9))
        self.assertFalse(layout_signal_applies(page_number=None, page_total=9))
        self.assertFalse(layout_signal_applies(page_number=6, page_total=0))

    def test_heading_signal_is_not_limited_by_position(self) -> None:
        """信号 A 不分位置：短论文的参考文献页排在第 2 页也照样切。"""
        text = BODY_TEXT + "\nReferences\n" + REFERENCE_ENTRIES
        region = reference_region(text, page_number=2, page_total=9)
        self.assertIsNotNone(region)
        assert region is not None
        self.assertEqual(region.char_start, text.index("References"))
        self.assertEqual(region.signal, "title")

    def test_page_number_and_total_read_from_section_ids(self) -> None:
        self.assertEqual(3, reference_page_number("page-003"))
        self.assertIsNone(reference_page_number("title"))
        self.assertIsNone(reference_page_number("introduction"))
        # 全篇页数取最大页码：解析器会跳过抽不出文字的页，页码本身才是版面页号。
        self.assertEqual(12, reference_page_total(["page-001", "page-012", "title"]))
        self.assertEqual(0, reference_page_total(["title", "body"]))

    def test_xml_papers_skip_the_whole_judgement(self) -> None:
        """JATS XML 那一路整篇不做判定：既不认标题也不算占比。"""
        self.assertTrue(parser_skips_reference_judgement("jats-xml-v1"))
        self.assertTrue(parser_skips_reference_judgement("JATS-XML"))
        self.assertFalse(parser_skips_reference_judgement("pypdf 6.1.1"))
        self.assertFalse(parser_skips_reference_judgement(""))
        document = ScientificDocument(
            paper_id="PMC-test",
            title="An XML paper",
            sections={"page-001": BODY_TEXT + "\nReferences\n" + REFERENCE_ENTRIES},
            parser="jats-xml-v1",
        )
        extractor = SchemaGuidedExtractor.from_path(
            SCHEMA_PATH, drop_reference_spans=True
        )
        payload = extractor.extract_documents([document]).to_dict()
        self.assertEqual([], payload["reference_exclusions"])
        kept = SchemaGuidedExtractor.from_path(SCHEMA_PATH).extract_documents(
            [document]
        ).to_dict()
        self.assertEqual(len(kept["evidence"]), len(payload["evidence"]))

    def test_normal_body_is_not_flagged(self) -> None:
        self.assertIsNone(reference_region(BODY_TEXT))
        # 正文里带一两条引用标记也不该整段被排掉。
        prose = BODY_TEXT + "\nFollowing Chen et al. (2019), we use the same split."
        self.assertIsNone(reference_region(prose))

    def test_layout_signal_needs_enough_sentences(self) -> None:
        # 句子太少时不判：三句里有三句引文式，占比 1.0 也不够 REFERENCE_MIN_SENTENCES。
        short = "Chen, L. et al. 2019. Knowledge graph embedding. vol. 12, pp. 33–45."
        self.assertLess(3, REFERENCE_MIN_SENTENCES)
        self.assertIsNone(reference_region(short))

    def test_empty_and_citation_free_text(self) -> None:
        self.assertIsNone(reference_region(""))
        self.assertIsNone(reference_region("   \n  \t "))
        self.assertIsNone(reference_region("just one sentence with nothing special"))
        self.assertEqual(citation_style_sentence_share(""), (0, 0, 0.0))
        self.assertEqual(citation_style_sentence_share("   "), (0, 0, 0.0))
        flagged, total, share = citation_style_sentence_share(BODY_TEXT)
        self.assertEqual(flagged, 0)
        self.assertGreater(total, 0)
        self.assertEqual(share, 0.0)

    def test_citation_style_judgement_on_single_sentences(self) -> None:
        self.assertTrue(looks_like_citation_style("Ahmed, S. 2021. A title. In Proceedings of ACL."))
        self.assertTrue(looks_like_citation_style("We follow Chen et al. (2019) for preprocessing."))
        self.assertTrue(looks_like_citation_style("Data at https://example.org/data."))
        self.assertTrue(looks_like_citation_style("[12] Smith, J. 2018. Another title."))
        self.assertFalse(looks_like_citation_style(""))
        self.assertFalse(looks_like_citation_style("We train the model for ten epochs."))


class DropReferenceSpansTests(unittest.TestCase):
    """开关的默认值与排除效果；默认关时抽取结果与从前逐项一致。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = ScientificDocument(
            paper_id="paper-1",
            title="A paper about relation extraction",
            sections={
                "page-001": BODY_TEXT + "\nReferences\n" + REFERENCE_ENTRIES,
            },
            parser="test",
        )

    def _extract(self, *, drop: bool) -> dict:
        extractor = SchemaGuidedExtractor.from_path(
            SCHEMA_PATH, drop_reference_spans=drop
        )
        return extractor.extract_documents([self.document]).to_dict()

    def test_default_is_off_and_keeps_reference_spans(self) -> None:
        extractor = SchemaGuidedExtractor.from_path(SCHEMA_PATH)
        self.assertFalse(extractor.drop_reference_spans)
        payload = extractor.extract_documents([self.document]).to_dict()
        self.assertEqual(payload["reference_exclusions"], [])
        kept = self._extract(drop=False)
        self.assertEqual(kept["evidence"], payload["evidence"])

    def test_drop_flag_removes_only_reference_spans(self) -> None:
        kept = self._extract(drop=False)
        dropped = self._extract(drop=True)
        self.assertLess(len(dropped["evidence"]), len(kept["evidence"]))
        # 保留下来的跨度逐字与不排除时相同（没动偏移口径）。
        dropped_ids = {item["evidence_id"] for item in dropped["evidence"]}
        self.assertTrue(dropped_ids <= {item["evidence_id"] for item in kept["evidence"]})
        for item in dropped["evidence"]:
            self.assertNotIn("Ahmed, S.", item["text"])
            self.assertNotIn("Chen, L. et al.", item["text"])
        # 排除明细只记段号与信号，不改库表结构。
        self.assertEqual(len(dropped["reference_exclusions"]), 1)
        record = dropped["reference_exclusions"][0]
        self.assertEqual(record["section_id"], "page-001")
        self.assertIn("title", record["signal"])
        self.assertGreaterEqual(record["excluded_evidence_count"], 1)

    def test_layout_gate_keeps_front_pages_and_drops_tail_pages(self) -> None:
        """抽取器把页码与全篇页数传进判据：靠前那页保住，后 1/3 那页排掉。"""
        document = ScientificDocument(
            paper_id="paper-2",
            title="A paper about relation extraction",
            sections={
                # 第 1 页是正文页，但行内引用密（占比过线）；第 3 页是参考文献续表。
                "page-001": REFERENCE_ENTRIES,
                "page-002": BODY_TEXT,
                "page-003": REFERENCE_ENTRIES,
            },
            parser="pypdf 6.1.1",
        )
        extractor = SchemaGuidedExtractor.from_path(
            SCHEMA_PATH, drop_reference_spans=True
        )
        payload = extractor.extract_documents([document]).to_dict()
        # 3 页的论文：起始页码 = ceil(3 × 2/3) = 2，第 1 页不算后 1/3。
        self.assertEqual(
            ["page-003"],
            [record["section_id"] for record in payload["reference_exclusions"]],
        )
        record = payload["reference_exclusions"][0]
        self.assertEqual(record["signal"], "layout")
        self.assertTrue(all(item["section_id"] != "page-003" for item in payload["evidence"]))
        self.assertTrue(any(item["section_id"] == "page-001" for item in payload["evidence"]))


if __name__ == "__main__":
    unittest.main()
