from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import (  # noqa: E402
    JatsXmlParser,
    SchemaGuidedExtractor,
)


# JATS 常见的第一套 DTD：-//NLM//DTD JATS，元素带前缀。
NLM_JATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.3 20210809//EN" "JATS-archivearticle1-3.dtd">
<article xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink" article-type="research-article" dtd-version="1.3">
  <front>
    <journal-meta><journal-title-group><journal-title>Journal of Demo Studies</journal-title></journal-title-group></journal-meta>
    <article-meta>
      <title-group><article-title>Graph Neural Networks for Materials Discovery</article-title></title-group>
    </article-meta>
  </front>
  <body>
    <p>Lead paragraph before any numbered section.</p>
    <sec id="s1" sec-type="intro">
      <title>Introduction</title>
      <p>The GNN model improves materials discovery for the Materials Project dataset.</p>
      <sec id="s1-1">
        <title>Earlier work</title>
        <p>Earlier work uses the Materials Project dataset.</p>
      </sec>
    </sec>
    <sec id="s2">
      <title>Method</title>
      <p>We use graph neural networks on the Materials Project dataset.</p>
      <list list-type="bullet">
        <list-item><p>First setup step</p></list-item>
        <list-item><p>Second setup step</p></list-item>
      </list>
      <fig id="f1">
        <label>Figure 1</label>
        <caption><p>Overall pipeline of the model.</p></caption>
      </fig>
    </sec>
    <sec id="s3">
      <title>Results</title>
      <p>The model improves accuracy on the benchmark dataset.</p>
    </sec>
  </body>
  <back><ack><p>Thanks to the reviewers.</p></ack></back>
</article>
"""

# 第二套 DTD：journalpublishing，前缀与第一套不同，还混了一处无命名空间元素。
JOURNAL_PUBLISHING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns="http://www.ncbi.nlm.nih.gov/JATS/journalpublishing/1.0" xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="1.0">
  <front><article-meta><title-group><article-title>&#22270;&#35889;&#31070;&#32463;&#32593;&#32476;&#29992;&#20110;&#26448;&#26009;&#21457;&#29616;</article-title></title-group></article-meta></front>
  <body>
    <sec id="sec1">
      <title>Introduction</title>
      <p>This work uses graph neural networks for materials discovery.</p>
    </sec>
    <sec id="sec2">
      <title>Methods</title>
      <p><![CDATA[The pipeline improves prediction accuracy.]]></p>
    </sec>
  </body>
</article>
"""

BROKEN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article><body><sec><title>Broken</title><p>The tag below never closes.</body></article>
"""

EMPTY_BODY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article><front><article-meta><title-group><article-title>Empty</article-title>
</title-group></article-meta></front><body><sec id="s1"><title>Only a title</title></sec></body></article>
"""


class JatsPageLayoutTests(unittest.TestCase):
    """页码口径与 section 展开。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.parser = JatsXmlParser()
        cls.document = cls.parser.parse_text(
            NLM_JATS_XML, paper_id="jats-demo", source_url="https://example.org/jats-demo"
        )

    def test_top_level_sections_become_numbered_pages(self) -> None:
        # 一页 = 一个顶层 sec；正文前言单独占最先一页，于是共 4 页。
        self.assertEqual(
            list(self.document.sections),
            ["page-001", "page-002", "page-003", "page-004"],
        )

    def test_preamble_page_comes_first(self) -> None:
        self.assertIn("Lead paragraph before any numbered section.", self.document.sections["page-001"])

    def test_nested_section_text_stays_on_its_top_level_page(self) -> None:
        introduction = self.document.sections["page-002"]
        self.assertIn("Introduction", introduction)
        self.assertIn("Earlier work", introduction)
        self.assertIn("Earlier work uses the Materials Project dataset.", introduction)
        self.assertNotIn(
            "Earlier work uses the Materials Project dataset.",
            self.document.sections["page-003"],
        )

    def test_inline_tags_keep_their_text_and_drop_their_tags(self) -> None:
        method = self.document.sections["page-003"]
        self.assertIn("We use graph neural networks on the Materials Project dataset.", method)
        self.assertNotIn("<", method)
        self.assertNotIn(">", method)

    def test_lists_figures_labels_and_captions_are_kept(self) -> None:
        method = self.document.sections["page-003"]
        for expected in ("First setup step", "Second setup step", "Figure 1", "Overall pipeline of the model."):
            self.assertIn(expected, method)

    def test_back_matter_is_not_part_of_body_pages(self) -> None:
        for text in self.document.sections.values():
            self.assertNotIn("Thanks to the reviewers.", text)

    def test_page_text_carries_parser_identity_not_pdf_identity(self) -> None:
        self.assertEqual("jats-xml-v1", self.document.parser)
        self.assertEqual("jats-xml-v1", JatsXmlParser.identity())

    def test_title_comes_from_jats_front_matter(self) -> None:
        self.assertEqual(
            "Graph Neural Networks for Materials Discovery", self.document.title
        )

    def test_explicit_title_overrides_jats_title(self) -> None:
        document = self.parser.parse_text(
            NLM_JATS_XML, paper_id="jats-demo", title="清单里的标题"
        )
        self.assertEqual("清单里的标题", document.title)


class JatsOffsetTests(unittest.TestCase):
    """字符偏移要能逐字切回页文本。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.parser = JatsXmlParser()
        cls.document = cls.parser.parse_text(NLM_JATS_XML, paper_id="jats-offsets")
        cls.extractor = SchemaGuidedExtractor.from_path(
            PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
        )
        cls.result = cls.extractor.extract_documents([cls.document])
        cls.page_texts = {"title": cls.document.title, **cls.document.sections}

    def test_every_evidence_span_slices_back_to_its_exact_text(self) -> None:
        self.assertTrue(self.result.evidence)
        for span in self.result.evidence:
            with self.subTest(evidence_id=span.evidence_id):
                page_text = self.page_texts[span.section_id]
                self.assertEqual(span.text, page_text[span.char_start : span.char_end])

    def test_every_entity_mention_offsets_stay_inside_its_span(self) -> None:
        evidence_by_id = {span.evidence_id: span for span in self.result.evidence}
        mentions = [
            mention for entity in self.result.entities for mention in entity.mentions
        ]
        self.assertTrue(mentions)
        for mention in mentions:
            with self.subTest(mention_id=mention.mention_id):
                span = evidence_by_id[mention.evidence_id]
                self.assertGreaterEqual(mention.char_start, 0)
                self.assertLessEqual(mention.char_end, len(span.text))
                self.assertTrue(
                    span.text[mention.char_start : mention.char_end].casefold()
                    == mention.surface_form.casefold()
                )

    def test_section_records_carry_parser_and_text_fingerprint(self) -> None:
        records = [item for item in self.result.sections if item["paper_id"] == "jats-offsets"]
        self.assertTrue(records)
        for record in records:
            self.assertEqual("jats-xml-v1", record["parser"])
            self.assertEqual(64, len(record["text_sha256"]))
            if record["section_id"] in self.page_texts:
                self.assertEqual(
                    len(self.page_texts[record["section_id"]]), record["char_count"]
                )

    def test_offsets_are_page_relative_not_document_relative(self) -> None:
        # 第二页的第一条证据必须落在该页文本范围内，而不是整篇文档范围。
        page_two = self.document.sections["page-002"]
        spans = [
            span for span in self.result.evidence if span.section_id == "page-002"
        ]
        self.assertTrue(spans)
        for span in spans:
            self.assertLessEqual(span.char_end, len(page_two))


class JatsExtractionTests(unittest.TestCase):
    """JATS 正文要能抽出实体与关系。"""

    @classmethod
    def setUpClass(cls) -> None:
        parser = JatsXmlParser()
        extractor = SchemaGuidedExtractor.from_path(
            PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
        )
        cls.document = parser.parse_text(NLM_JATS_XML, paper_id="jats-extract")
        cls.result = extractor.extract_documents([cls.document])

    def test_entities_are_extracted_from_body_pages(self) -> None:
        names = {entity.canonical_name for entity in self.result.entities}
        self.assertIn("Materials Project", names)
        self.assertTrue(self.result.entities)

    def test_relations_are_extracted_with_evidence(self) -> None:
        self.assertTrue(self.result.relations)
        evidence_ids = {span.evidence_id for span in self.result.evidence}
        for relation in self.result.relations:
            with self.subTest(relation_id=relation.relation_id):
                self.assertTrue(relation.evidence_ids)
                self.assertTrue(set(relation.evidence_ids).issubset(evidence_ids))

    def test_relation_types_are_readable_from_real_sentences(self) -> None:
        relation_types = {relation.relation_type for relation in self.result.relations}
        self.assertTrue(
            relation_types
            & {"IMPROVES", "USES", "EVALUATES_ON", "ADDRESSES", "ENABLES", "REPORTS"}
        )


class JatsNamespaceTests(unittest.TestCase):
    """两套常见 DTD（前缀不同、无前缀）都要能解析。"""

    def setUp(self) -> None:
        self.parser = JatsXmlParser()

    def test_nlm_dtd_with_prefixes_parses(self) -> None:
        document = self.parser.parse_text(NLM_JATS_XML, paper_id="nlm")
        self.assertEqual("jats-xml-v1", document.parser)
        self.assertTrue(all(name.startswith("page-") for name in document.sections))
        self.assertEqual(4, len(document.sections))

    def test_journalpublishing_dtd_with_default_namespace_parses(self) -> None:
        document = self.parser.parse_text(JOURNAL_PUBLISHING_XML, paper_id="jp")
        self.assertEqual(["page-001", "page-002"], list(document.sections))
        self.assertIn("This work uses graph neural networks", document.sections["page-001"])

    def test_character_entities_and_cdata_both_come_through(self) -> None:
        document = self.parser.parse_text(JOURNAL_PUBLISHING_XML, paper_id="jp")
        # 标题是数字字符引用，正文第二段是 CDATA。
        self.assertEqual("图谱神经网络用于材料发现", document.title)
        self.assertIn("The pipeline improves prediction accuracy.", document.sections["page-002"])

    def test_namespaced_and_unprefixed_documents_give_same_page_keys(self) -> None:
        nlm = self.parser.parse_text(NLM_JATS_XML, paper_id="nlm")
        plain = self.parser.parse_text(
            NLM_JATS_XML.replace(" xmlns:xlink=\"http://www.w3.org/1999/xlink\"", ""),
            paper_id="plain",
        )
        self.assertEqual(list(nlm.sections), list(plain.sections))


class JatsFailureTests(unittest.TestCase):
    """不合法输入要明确报错，不静默产出空文本。"""

    def setUp(self) -> None:
        self.parser = JatsXmlParser()

    def test_broken_xml_raises_with_original_parse_error(self) -> None:
        with self.assertRaises(ValueError) as context:
            self.parser.parse_text(BROKEN_XML, paper_id="broken")
        message = str(context.exception)
        self.assertIn("broken", message)
        self.assertIn("JATS XML 不合法", message)

    def test_undeclared_entity_is_rejected(self) -> None:
        xml = (
            "<article><body><sec><title>t</title>"
            "<p>Values &nbsp; are not declared here.</p></sec></body></article>"
        )
        with self.assertRaises(ValueError):
            self.parser.parse_text(xml, paper_id="entity")

    def test_empty_body_raises_instead_of_returning_nothing(self) -> None:
        with self.assertRaises(ValueError) as context:
            self.parser.parse_text(EMPTY_BODY_XML, paper_id="empty")
        self.assertIn("拒绝静默产出空文本", str(context.exception))

    def test_plain_text_input_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.parser.parse_text("This is not XML at all.", paper_id="plain")

    def test_missing_file_raises_oserror(self) -> None:
        with self.assertRaises(OSError):
            self.parser.parse(Path(PROJECT_ROOT) / ".tmp" / "not-here-12345.xml")


class JatsFileParsingTests(unittest.TestCase):
    """走文件这条路要和走字符串这条路结果一致。"""

    def test_parse_from_file_matches_parse_text(self) -> None:
        parser = JatsXmlParser()
        expected = parser.parse_text(NLM_JATS_XML, paper_id="from-file")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jats-demo.xml"
            path.write_text(NLM_JATS_XML, encoding="utf-8")
            parsed = parser.parse(path, paper_id="from-file", title="")
        self.assertEqual(expected.sections, parsed.sections)
        self.assertEqual(expected.title, parsed.title)
        self.assertEqual("jats-xml-v1", parsed.parser)

    def test_paper_id_and_source_url_default_to_file_metadata(self) -> None:
        parser = JatsXmlParser()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "some-paper.xml"
            path.write_text(JOURNAL_PUBLISHING_XML, encoding="utf-8")
            parsed = parser.parse(path)
        self.assertEqual("some-paper", parsed.paper_id)
        self.assertEqual(str(path.resolve()), parsed.source_url)


if __name__ == "__main__":
    unittest.main()
