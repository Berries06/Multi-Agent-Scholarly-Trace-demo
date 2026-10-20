from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.models import Paper  # noqa: E402
from yanhai.sources import (  # noqa: E402
    ArxivRetriever,
    CrossrefRetriever,
    MultiSourceRetriever,
    OfficialDocsRetriever,
    OpenAlexRetriever,
    search_multi_source,
)


class StubAdapter:
    def __init__(self, source_id: str, papers: list[Paper] | None = None) -> None:
        self.source_id = source_id
        self.papers = papers

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        if self.papers is None:
            raise TimeoutError("simulated")
        return self.papers


def paper(
    paper_id: str,
    title: str,
    *,
    doi: str = "",
    authority_tier: int = 2,
) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        authors=("Author",),
        year=2026,
        published="2026-01-01",
        categories=("embedded audio",),
        summary=f"{title} discusses ESP32 I2S portable audio.",
        concepts=("ESP32", "I2S"),
        source_url=f"https://example.test/{paper_id}",
        authority_tier=authority_tier,
        external_ids={"doi": doi} if doi else {},
    )


class SourceAdapterTests(unittest.TestCase):
    def test_official_catalog_returns_esp32_audio_sources(self) -> None:
        retriever = OfficialDocsRetriever(
            PROJECT_ROOT / "data" / "knowledge" / "official_sources.json"
        )
        results = retriever.search(["ESP32 portable audio amplifier"], limit=6)
        self.assertGreaterEqual(len(results), 3)
        self.assertTrue(all(item.authority_tier == 1 for item in results))
        self.assertTrue(
            any(item.paper_id == "official:espressif:esp-idf-i2s" for item in results)
        )

    def test_arxiv_query_keeps_anchor_and_uses_or_for_supporting_terms(self) -> None:
        query = ArxivRetriever._normalise_query("ESP32 portable audio amplifier design")
        self.assertTrue(query.startswith("all:ESP32 AND"))
        self.assertIn(" OR ", query)

    def test_openalex_reconstructs_abstract_and_ids(self) -> None:
        def getter(url: str, headers: dict[str, str], timeout: float) -> dict:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.1/test",
                        "title": "ESP32 Audio",
                        "publication_year": 2025,
                        "publication_date": "2025-01-01",
                        "authorships": [{"author": {"display_name": "A"}}],
                        "primary_location": {
                            "landing_page_url": "https://example.test/work",
                            "source": {"display_name": "Journal"},
                        },
                        "open_access": {"oa_status": "gold"},
                        "abstract_inverted_index": {"ESP32": [0], "audio": [1]},
                        "topics": [{"display_name": "Embedded systems"}],
                    }
                ]
            }

        result = OpenAlexRetriever(getter=getter).search(["ESP32 audio"], limit=3)[0]
        self.assertEqual("ESP32 audio", result.summary)
        self.assertEqual("10.1/test", result.external_ids["doi"])
        self.assertEqual("gold", result.license)

    def test_crossref_normalises_doi_and_markup(self) -> None:
        def getter(url: str, headers: dict[str, str], timeout: float) -> dict:
            return {
                "message": {
                    "items": [
                        {
                            "DOI": "10.2/TEST",
                            "title": ["I2S Audio"],
                            "author": [{"given": "A", "family": "B"}],
                            "published": {"date-parts": [[2024, 2]]},
                            "abstract": "<jats:p>Digital audio interface.</jats:p>",
                            "URL": "https://doi.org/10.2/TEST",
                            "subject": ["Engineering"],
                            "publisher": "Publisher",
                            "type": "book-chapter",
                        }
                    ]
                }
            }

        result = CrossrefRetriever(getter=getter).search(["I2S audio"], limit=3)[0]
        self.assertEqual("doi:10.2/test", result.paper_id)
        self.assertEqual("Digital audio interface.", result.summary)

    def test_multi_source_keeps_partial_success_and_deduplicates_doi(self) -> None:
        lower = paper("openalex:W1", "ESP32 Audio", doi="10.3/test")
        official = paper(
            "official:doc",
            "Official ESP32 Audio Guide",
            doi="10.3/test",
            authority_tier=1,
        )
        retriever = MultiSourceRetriever(
            PROJECT_ROOT / "data" / "knowledge" / "official_sources.json",
            adapters=[
                StubAdapter("timed_out"),
                StubAdapter("openalex", [lower]),
                StubAdapter("official_docs", [official]),
            ],
        )
        results = retriever.search(["ESP32 audio"], limit=5)
        self.assertEqual(1, len(results))
        self.assertEqual("official:doc", results[0].paper_id)
        self.assertIn("timed_out 检索失败：TimeoutError", retriever.last_report.warnings)
        self.assertEqual(
            ["official_docs", "openalex"],
            retriever.last_report.successful_sources,
        )

    def test_multi_source_prioritises_official_documents(self) -> None:
        scholarly = paper(
            "doi:paper",
            "ESP32 Portable Audio Amplifier with I2S Speaker",
            doi="10.4/paper",
        )
        official = paper(
            "official:guide",
            "ESP32 Audio Guide",
            authority_tier=1,
        )
        retriever = MultiSourceRetriever(
            PROJECT_ROOT / "data" / "knowledge" / "official_sources.json",
            adapters=[
                StubAdapter("crossref", [scholarly]),
                StubAdapter("official_docs", [official]),
            ],
        )
        results = retriever.search(["ESP32 portable audio amplifier I2S"], limit=5)
        self.assertEqual("official:guide", results[0].paper_id)

    def test_search_multi_source_marks_candidates_and_reports_sources(self) -> None:
        sample = paper(
            "doi:sample",
            "Sample Knowledge Graph Paper",
            doi="10.5/sample",
        )
        retriever = MultiSourceRetriever(
            PROJECT_ROOT / "data" / "knowledge" / "official_sources.json",
            adapters=[StubAdapter("arxiv", [sample])],
        )
        result = search_multi_source(
            "knowledge graph construction", retriever=retriever
        )
        self.assertEqual("multi_source", result["source"])
        self.assertEqual(1, len(result["results"]))
        self.assertEqual(
            "candidate_requires_local_parsing", result["results"][0]["status"]
        )
        self.assertEqual(
            ["arxiv"], result["report"]["successful_sources"]
        )

    def test_search_multi_source_degrades_when_all_sources_fail(self) -> None:
        retriever = MultiSourceRetriever(
            PROJECT_ROOT / "data" / "knowledge" / "official_sources.json",
            adapters=[StubAdapter("arxiv")],
        )
        result = search_multi_source(
            "knowledge graph construction", retriever=retriever
        )
        self.assertFalse(result["network_used"])
        self.assertEqual([], result["results"])
        self.assertIn("不可达", result["warning"])


if __name__ == "__main__":
    unittest.main()
