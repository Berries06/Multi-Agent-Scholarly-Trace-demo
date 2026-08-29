"""证据图谱（Atlas）数据层测试：领域数量、论文计数与未知领域分支。

不依赖 httpx/TestClient，直接测 /api/atlas 端点背后的数据逻辑。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402


class AtlasDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)

    def _domain_summaries(self):
        rows = []
        for did, cfg in self.orchestrator.kb.domain_configs.items():
            kb, _, _ = self.orchestrator._runtime(did)
            corpus = kb.vertical_corpus
            rows.append(
                {
                    "domain_id": did,
                    "paper_count": len(corpus.papers),
                    "evidence_paper_count": len(corpus.evidence_papers),
                    "metadata_only_count": len(corpus.papers) - len(corpus.evidence_papers),
                }
            )
        return rows

    def test_five_domains_and_290_papers(self) -> None:
        rows = self._domain_summaries()
        self.assertEqual(5, len(rows))
        self.assertEqual(290, sum(row["paper_count"] for row in rows))

    def test_per_domain_evidence_metadata_split(self) -> None:
        rows = {row["domain_id"]: row for row in self._domain_summaries()}
        expected = {
            "scientific-ie-kg": (30, 8),
            "materials-discovery-gnn": (30, 5),
            "educational-knowledge-tracing": (30, 6),
            "single-cell-transcriptomics": (100, 78),
            "quantum-computing": (100, 84),
        }
        for domain_id, (total, evidence) in expected.items():
            with self.subTest(domain=domain_id):
                row = rows[domain_id]
                self.assertEqual(total, row["paper_count"])
                self.assertEqual(evidence, row["evidence_paper_count"])
                self.assertEqual(total - evidence, row["metadata_only_count"])

    def test_unknown_domain_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.orchestrator._runtime("no-such-domain")

    def test_every_evidence_paper_carries_provenance_basis(self) -> None:
        # 摘要级证据卡必须声明"不是全文逐字摘录"类 provenance，防止冒充精读。
        # 该约定适用于两个新领域（摘要卡）；旧三领域为逐字证据卡，不受此限。
        checked = 0
        for domain_id in ("single-cell-transcriptomics", "quantum-computing"):
            kb, _, _ = self.orchestrator._runtime(domain_id)
            for record in kb.vertical_corpus.paper_records.values():
                if record.get("exclude_from_evidence_graph", False):
                    continue
                basis = str(record.get("knowledge_card_basis", "")).lower()
                self.assertTrue(
                    basis or record.get("source_verified_against_original") is True,
                    f"{record.get('paper_id')} 证据卡缺少 provenance 声明",
                )
                checked += 1
        self.assertGreaterEqual(checked, 150)


if __name__ == "__main__":
    unittest.main()
