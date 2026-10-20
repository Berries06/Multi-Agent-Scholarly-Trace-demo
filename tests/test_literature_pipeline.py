"""Unit tests for the literature pipeline (chunking + scan helpers).

Network code paths (arxiv fetch / LLM interpret) are not exercised here; the
tested logic is pure and deterministic.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT / "scripts", PROJECT_ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from chunk_corpus import (  # noqa: E402
    chunk_document,
    needs_ocr_flag,
    split_sentences,
)
from weekly_literature_scan import known_match, load_known_titles, normalize_title  # noqa: E402


class ChunkingTests(unittest.TestCase):
    def test_sentence_spans_cover_text_without_splitting(self) -> None:
        text = "第一句。第二句！第三句？"
        spans = split_sentences(text)
        self.assertEqual(3, len(spans))
        # 全局偏移连续覆盖原文
        self.assertEqual(0, spans[0]["char_start"])
        self.assertEqual(len(text), spans[-1]["char_end"])
        for span in spans:
            self.assertEqual(text[span["char_start"] : span["char_end"]], span["text"])

    def test_blocks_never_split_a_sentence(self) -> None:
        text = "句1。句2。句3。句4。句5。句6。句7。句8。句9。"
        result = chunk_document("p1", {"摘要": text}, block_size=3, overlap=1)
        all_sentence_ids = [sid for block in result["chunks"] for sid in block["sentence_ids"]]
        # 每句至少完整出现在一个块中（重叠不算割裂），且按序
        unique_in_order = []
        for sid in all_sentence_ids:
            if not unique_in_order or unique_in_order[-1] != sid:
                unique_in_order.append(sid)
        self.assertEqual(9, len(unique_in_order))

    def test_overlap_between_blocks(self) -> None:
        text = "句1。句2。句3。句4。句5。"
        result = chunk_document("p1", {"正文": text}, block_size=3, overlap=1)
        first = result["chunks"][0]["sentence_ids"]
        second = result["chunks"][1]["sentence_ids"]
        self.assertEqual(first[-1], second[0])  # 重叠 1 句

    def test_table_like_blocks_get_ocr_flag(self) -> None:
        self.assertTrue(needs_ocr_flag("Table 1 对比结果"))
        self.assertTrue(needs_ocr_flag("1 2 3 4 5 6 7 8 9 0 1 2 3"))
        self.assertFalse(needs_ocr_flag("这是一段普通正文句子。"))

    def test_chunk_metadata_fields_present(self) -> None:
        result = chunk_document("p1", {"摘要": "第一句。第二句。"}, block_size=8)
        block = result["chunks"][0]
        for field in ("paper_id", "section", "sentence_ids", "char_start", "char_end", "needs_human_ocr"):
            self.assertIn(field, block)


class ScanHelperTests(unittest.TestCase):
    def test_normalize_title(self) -> None:
        self.assertEqual("multi agent debate", normalize_title("Multi-Agent Debate!"))

    def test_known_match_finds_similar_title(self) -> None:
        known = [normalize_title("Multiagent Debate for Language Models")]
        self.assertIsNotNone(known_match("Multi-Agent Debate for Language Models", known))

    def test_known_match_rejects_unrelated_title(self) -> None:
        known = [normalize_title("Multiagent Debate for Language Models")]
        self.assertIsNone(known_match("Protein Folding with Graph Networks", known))

    def test_load_known_titles_reads_frozen_corpus(self) -> None:
        titles = load_known_titles()
        self.assertGreaterEqual(len(titles), 100)


if __name__ == "__main__":
    unittest.main()
