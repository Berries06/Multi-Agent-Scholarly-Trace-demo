"""学术研究后端 skill 的行为测试（团队研究工具，非产品板块）。

重点锁定引用核验的口径：只做 DOI 格式与标题-URL 一致性初筛，
绝不返回权威核验结论（VERIFIED 状态已被移除）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.skills.academic_researcher import verify_citation  # noqa: E402


def paper(doi: str | None, title: str, source_url: str) -> dict:
    return {
        "paper_id": "p1",
        "title": title,
        "source_url": source_url,
        "external_ids": {"DOI": doi} if doi else {},
    }


class CitationCheckTests(unittest.TestCase):
    def test_valid_doi_and_matching_url_is_only_preliminary(self) -> None:
        result = verify_citation(
            paper(
                "10.1038/s41586-021-03500-x",
                "A Benchmark Study of Language Models",
                "https://example.org/benchmark-study-language-models",
            )
        )
        self.assertEqual("PRELIMINARY", result.verification_status)
        self.assertNotIn("VERIFIED", result.verification_status)

    def test_malformed_doi_is_major(self) -> None:
        result = verify_citation(
            paper(
                "not-a-doi",
                "A Benchmark Study of Language Models",
                "https://example.org/paper",
            )
        )
        self.assertEqual("MAJOR", result.verification_status)
        self.assertTrue(any("格式异常" in issue for issue in result.issues))

    def test_missing_doi_with_url_is_minor(self) -> None:
        result = verify_citation(
            paper(None, "A Benchmark Study of Language Models", "https://example.org/paper")
        )
        self.assertEqual("MINOR", result.verification_status)
        self.assertTrue(any("缺少 DOI" in issue for issue in result.issues))

    def test_missing_everything_is_unverifiable(self) -> None:
        result = verify_citation(paper(None, "Short Title", ""))
        self.assertEqual("UNVERIFIABLE", result.verification_status)

    def test_title_url_mismatch_is_reported(self) -> None:
        result = verify_citation(
            paper(
                "10.1038/s41586-021-03500-x",
                "Benchmarking Graph Neural Networks",
                "https://example.org/unrelated-paper",
            )
        )
        self.assertTrue(any("标题与链接可能不匹配" in issue for issue in result.issues))


if __name__ == "__main__":
    unittest.main()
