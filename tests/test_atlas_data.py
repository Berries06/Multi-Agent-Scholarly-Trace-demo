"""证据图谱（Atlas）数据层测试：领域数量、题录计数与未知领域分支。

不依赖 httpx/TestClient，直接测 /api/atlas 端点背后的数据逻辑。

这里不再写死"总数 333""主领域 49 篇"这类数字：语料在持续扩充
（`scripts/语料/收集开放全文.py` 会往五个 `manifest.json` 追加论文），数字一写死，
每扩一次语料就得手改测试，改到最后没人知道哪个数字才是对的。现在改成两层核对：

1. 从 `data/vertical_kb/registry.json` 找到五个领域的清单，现场数出每个领域有多少条；
2. 与 `display/data.json`（导出给网页看的文件）逐条对齐——导出文件与清单一致，
   才是这几个测试真正要保的东西。

总数本身不再是断言对象，只有"清单与导出文件对不上"才会让测试不过。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_manifest as cm  # noqa: E402

from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402

# 这两个领域是摘要级证据卡（不是全文逐字卡），provenance 声明的既有检查范围。
CARD_BASIS_DOMAINS = ("single-cell-transcriptomics", "quantum-computing")


class AtlasDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 先把五个清单读成快照，再让编排器读到同一份字节：
        # 采集脚本正在写这些文件，分两次读会拿到不同时间的数字。
        cm.load_all()
        with cm.frozen_manifests(cm.domain_ids()):
            cls.orchestrator = ScholarlyTraceOrchestrator(PROJECT_ROOT)
            # 五个领域的运行时在这里一次建好，后面取到的都是同一份快照。
            for domain_id in cls.orchestrator.kb.domain_configs:
                cls.orchestrator._runtime(domain_id)

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

    def test_five_registered_domains_and_totals_match_manifest(self) -> None:
        """领域数量与逐领域题录数都不写死，改成现场对清单与导出文件。

        "五个领域"以 `data/vertical_kb/registry.json` 为准；总数只是把各领域加起来，
        不再当断言对象。真正要保的是：`display/data.json` 里每个领域的题录、
        证据层、只有题录三组数字与清单一致。
        """
        rows = self._domain_summaries()
        registered = cm.domain_ids()
        self.assertEqual(
            len(registered),
            len(rows),
            f"运行时加载的领域数 {len(rows)} 与注册表里的 {len(registered)} 不一致",
        )
        self.assertEqual(registered, [row["domain_id"] for row in rows])

        display = cm.display_domains()
        self.assertEqual(
            set(registered),
            set(display),
            "display/data.json 的领域集合与注册表对不上："
            f"只在一侧的领域 {sorted(set(registered) ^ set(display))}",
        )

        manifest_total = 0
        display_total = 0
        for row in rows:
            domain_id = row["domain_id"]
            records = cm.records(domain_id)
            # 证据层的判据是"排除出证据图这一位为假"（有知识卡的才算），
            # 不是"档位不是 metadata_only"：拿到开放全文但还没写知识卡的也不算进图。
            evidence = cm.evidence_layer_count(domain_id)
            not_in_evidence_layer = len(records) - evidence
            manifest_total += len(records)

            with self.subTest(domain=domain_id):
                self.assertEqual(
                    len(records),
                    row["paper_count"],
                    f"{domain_id}：清单里有 {len(records)} 条题录，"
                    f"运行时语料只加载了 {row['paper_count']} 条",
                )
                self.assertEqual(
                    evidence,
                    row["evidence_paper_count"],
                    f"{domain_id}：清单里 {evidence} 条记录进证据层，"
                    f"运行时却数出 {row['evidence_paper_count']} 条证据层记录",
                )
                self.assertEqual(not_in_evidence_layer, row["metadata_only_count"])

                entry = display[domain_id]
                self.assertEqual(
                    len(records),
                    entry.get("paper_count"),
                    f"{domain_id}：display/data.json 写的题录数 {entry.get('paper_count')} "
                    f"与清单里的 {len(records)} 不一致（导出文件要重新生成）",
                )
                self.assertEqual(
                    evidence,
                    entry.get("evidence_paper_count"),
                    f"{domain_id}：display/data.json 写的证据层条数 "
                    f"{entry.get('evidence_paper_count')} 与清单里的 {evidence} 不一致",
                )
                self.assertEqual(not_in_evidence_layer, entry.get("metadata_only_count"))
                cm.assert_display_matches_manifest(self, domain_id, entry)
                display_total += int(entry.get("paper_count") or 0)

        self.assertEqual(
            manifest_total,
            display_total,
            f"五个领域清单共 {manifest_total} 条题录，display/data.json 只导出了 "
            f"{display_total} 条",
        )

    def test_per_domain_evidence_metadata_split(self) -> None:
        """逐领域核对"题录数 / 证据层数 / 只有题录数"三组数字与导出文件一致。

        以前这里是写死的元组（主领域 49 篇 8 条证据层……），语料一长就报错；
        现在改成从五个 `manifest.json` 现场数，主领域读
        `data/vertical_kb/manifest.json`，其余四个读 `domains/<domain_id>/manifest.json`。
        """
        rows = {row["domain_id"]: row for row in self._domain_summaries()}
        display = cm.display_domains()

        for domain_id in cm.domain_ids():
            with self.subTest(domain=domain_id):
                records = cm.records(domain_id)
                tiers = cm.tier_counts(domain_id)
                evidence = cm.evidence_layer_count(domain_id)
                # 导出文件里的 `metadata_only_count` 是"没进证据层的篇数"，
                # 与档位 `metadata_only` 不是一回事（拿到开放全文但没写知识卡的那些也没进图）。
                not_in_evidence_layer = len(records) - evidence
                row = rows[domain_id]
                entry = display[domain_id]

                self.assertEqual(len(records), row["paper_count"])
                self.assertEqual(evidence, row["evidence_paper_count"])
                self.assertEqual(not_in_evidence_layer, row["metadata_only_count"])
                # 档位三档加起来必须等于总篇数（防止出现没写档位的记录）
                self.assertEqual(
                    sum(tiers.values()),
                    len(records),
                    f"{domain_id}：按 evidence_tier 数出来的条数与题录总数不一致，"
                    f"分档是 {tiers}",
                )

                # 导出文件与清单必须逐条对得上，两个方向都查。
                cm.assert_display_matches_manifest(self, domain_id, entry)
                self.assertEqual(
                    len(entry.get("papers", [])),
                    row["paper_count"],
                    f"{domain_id}：display/data.json 里列了 "
                    f"{len(entry.get('papers', []))} 篇，运行时语料有 {row['paper_count']} 篇",
                )

    def test_unknown_domain_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.orchestrator._runtime("no-such-domain")

    def test_every_evidence_paper_carries_provenance_basis(self) -> None:
        # 摘要级证据卡必须声明"不是全文逐字摘录"类 provenance，防止冒充精读。
        # 该约定适用于两个新领域（摘要卡）；旧三领域为逐字证据卡，不受此限。
        #
        # "至少查到多少条"改成从清单现场数：这两个领域里 evidence_card 档的记录条数。
        # 原先写死 150，语料一长这个下限就形同虚设；现在它等于实际要查的条数。
        # 另外，这里只查知识卡那一档：full_text 档是"下到开放全文、还没有知识卡"的记录，
        # 不在这条 provenance 约定的范围内（它有没有本地文档由
        # tests/test_vertical_assets.py::test_every_graph_evidenced_record_has_a_local_document 管）。
        checked = 0
        for domain_id in CARD_BASIS_DOMAINS:
            expected = cm.tier_counts(domain_id).get("evidence_card", 0)
            kb, _, _ = self.orchestrator._runtime(domain_id)
            found = 0
            for record in kb.vertical_corpus.paper_records.values():
                if record.get("evidence_tier") != "evidence_card":
                    continue
                basis = str(record.get("knowledge_card_basis", "")).lower()
                self.assertTrue(
                    basis or record.get("source_verified_against_original") is True,
                    f"{record.get('paper_id')} 证据卡缺少 provenance 声明",
                )
                found += 1
            self.assertEqual(
                expected,
                found,
                f"{domain_id}：清单里 {expected} 条 evidence_card 记录，运行时只查到 {found} 条",
            )
            checked += found
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
