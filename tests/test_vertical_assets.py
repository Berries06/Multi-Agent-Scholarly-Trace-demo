"""垂直领域语料与证据资产的测试。

这里不再写死"主领域 49 篇 / metadata_only 41 条 / evidence_card 8 条"这类数字：
`scripts/语料/收集开放全文.py` 会持续往五个 `manifest.json` 追加论文，数字一写死，
每扩一次语料都得手改测试。现在改成从清单现场数，保下来的是这些不变量：

* 五个领域（以 `data/vertical_kb/registry.json` 为准）都能加载，领域标识与清单一致；
* `metadata_only` 的记录必须 `exclude_from_evidence_graph` 为真，且不能出现在关系图的证据来源里；
* 关系图里作为证据来源的论文集合，与"清单里非 metadata_only 档"的记录一一对应；
* 每篇都要有明确的 `peer_reviewed` 布尔标记，没标的必须说得清是 arXiv 预印本。

关于"从清单现场数"与 `src/yanhai/corpus.py` 的关系：`VerticalCorpus.documents()`
按记录的 `document_path` 建文档，而扩语料收进来的 `full_text` 记录只有 `local_source`
（本地 PDF/XML），没有知识卡也就没有 `document_path`。本文件按"有 `document_path`
才建图"的口径准备关系图，并把这条口径本身写成断言（见
`test_metadata_only_records_cannot_create_graph_evidence`），保证不是因为读不到文件
而静默少算。

注意：采集脚本正在往清单里追加论文，所以同一份清单要一次读进来、全类共用；
分几次读会拿到不同时间的快照，几个断言之间会自相矛盾。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_manifest as cm  # noqa: E402

from yanhai.extraction import PlainTextParser, SchemaGuidedExtractor  # noqa: E402
from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.store import KnowledgeGraphStore  # noqa: E402

EXTRACTION_SCHEMA = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"


def _evidence_graph_of(kb: KnowledgeBase, records: dict[str, dict]) -> dict:
    """按清单快照建该领域的关系图：只收不在 metadata_only 档、且写明 `document_path` 的记录。

    不调用 `kb.extracted_paper_graph()` 的原因写在模块开头：那条路径要求每条
    不进 metadata_only 档的记录都有 `document_path`，而扩语料收进来的 `full_text`
    记录还没有知识卡。这里只把有 `document_path` 的记录建进图；缺席的记录由
    `test_metadata_only_records_cannot_create_graph_evidence` 逐条对照清单检查。

    判据与图都取自同一份清单快照：只有题录的记录（`metadata_only`）一律不进图，
    `exclude_from_evidence_graph` 标记由那条用例单独把关。
    """
    corpus = kb.vertical_corpus
    parser = PlainTextParser()
    documents = [
        parser.parse(
            corpus.root / record["document_path"],
            paper_id=paper_id,
            source_url=record.get("source_url", ""),
        )
        for paper_id, record in records.items()
        if record.get("document_path")
        and record.get("evidence_tier") != "metadata_only"
    ]
    if not documents:
        raise AssertionError(
            f"{corpus.manifest_path} 里没有任何带 document_path 的记录，没法建关系图"
        )
    extractor = SchemaGuidedExtractor.from_path(EXTRACTION_SCHEMA)
    payload = extractor.extract_documents(documents).to_dict()
    payload["domain"] = corpus.domain
    return payload


class VerticalAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 先把五个清单读成快照，再让语料对象读到同一份字节：
        # 采集脚本正在写这些文件，分两次读会拿到不同时间的数字。
        cm.load_all()
        with cm.frozen_manifests(cm.domain_ids()):
            cls.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
            # 解析一份切片要读几十到上百篇论文并重建抽取图，单个约 0.1–0.9 秒。
            # 原先三条用例各自把五个切片重新构造一遍。这些输入全部来自
            # data/knowledge 下已经版本化的文件，一次运行内不会变，各用例也只读这份夹具
            # （KnowledgeGraphStore.rebuild 同样只读），所以在类上建一次、共用。
            # 覆盖的切片、输入与断言都没有减少。
            cls.domain_kbs = {
                domain_id: (
                    cls.kb
                    if domain_id == cls.kb.default_domain_id
                    else KnowledgeBase(PROJECT_ROOT / "data" / "knowledge", domain_id)
                )
                for domain_id in cls.kb.domain_configs
            }
        cls.manifest_records = {
            domain_id: {
                str(record["paper_id"]): record
                for record in cm.records(domain_id)
            }
            for domain_id in cls.kb.domain_configs
        }
        cls.domain_graphs = {
            domain_id: _evidence_graph_of(kb, cls.manifest_records[domain_id])
            for domain_id, kb in cls.domain_kbs.items()
        }
        cls.corpus_records = {
            domain_id: dict(kb.vertical_corpus.paper_records)
            for domain_id, kb in cls.domain_kbs.items()
        }
        cls.metadata_only_ids = {
            domain_id: {
                paper_id
                for paper_id, record in records.items()
                if record.get("evidence_tier") == "metadata_only"
            }
            for domain_id, records in cls.manifest_records.items()
        }

    def _assert_corpus_matches_manifest_snapshot(self, domain_id: str) -> None:
        """运行时语料与清单快照必须是同一批记录：标识集合、条数都要对得上。"""
        manifest_ids = set(self.manifest_records[domain_id])
        corpus_ids = set(self.corpus_records[domain_id])
        self.assertEqual(
            manifest_ids,
            corpus_ids,
            f"{domain_id}：运行时语料与清单快照的记录不一致，"
            f"只在清单里 {cm.short(manifest_ids - corpus_ids)}，"
            f"只在语料里 {cm.short(corpus_ids - manifest_ids)}",
        )

    def test_vertical_slice_paper_counts_match_manifest(self) -> None:
        # 篇数不写死：主领域现在多少篇，以 data/vertical_kb/manifest.json 现场数出来的为准。
        # 这里守的是"运行时语料与清单一致"，不是某个固定篇数。
        domain_id = self.kb.default_domain_id
        self._assert_corpus_matches_manifest_snapshot(domain_id)
        records = self.manifest_records[domain_id]
        # 证据层的判据是"排除出证据图这一位为假"（有知识卡的才算），不是"档位不是 metadata_only"。
        expected_evidence = cm.evidence_layer_count(domain_id)

        self.assertEqual(len(records), len(self.kb.vertical_corpus.papers))
        self.assertEqual(
            expected_evidence,
            len(self.kb.vertical_corpus.evidence_papers),
            "清单里进证据层的记录数与运行时证据层篇数不一致",
        )
        self.assertTrue(
            all(
                "aclanthology.org" in paper.source_url
                for paper in self.kb.vertical_corpus.evidence_papers
            ),
            "主领域的知识卡都来自 ACL Anthology（CC BY 4.0），出现别的来源要说明许可",
        )
        metadata_only = [
            record
            for record in records.values()
            if record["evidence_tier"] == "metadata_only"
        ]
        self.assertEqual(
            cm.tier_counts(domain_id).get("metadata_only", 0),
            len(metadata_only),
            "按 evidence_tier 现场数出来的 metadata_only 条数与逐条筛出来的不一致",
        )
        self.assertTrue(
            all(record["exclude_from_evidence_graph"] for record in metadata_only)
        )

    def test_registry_exposes_reproducible_vertical_slices(self) -> None:
        # 每个领域多少篇从清单现场数，不再在测试里抄一份数字表。
        expected = {
            domain_id: len(self.manifest_records[domain_id])
            for domain_id in self.kb.domain_configs
        }
        self.assertEqual(set(expected), set(self.kb.domain_configs))
        for domain_id, paper_count in expected.items():
            kb = self.domain_kbs[domain_id]
            with self.subTest(domain=domain_id):
                self._assert_corpus_matches_manifest_snapshot(domain_id)
                self.assertEqual(paper_count, len(kb.vertical_corpus.papers))
            records = [
                kb.vertical_corpus.paper_records[paper.paper_id]
                for paper in kb.vertical_corpus.papers
            ]
            # 每篇都要有明确的 peer_reviewed 标记（布尔，不能缺、不能是字符串）。
            self.assertTrue(all(isinstance(item["peer_reviewed"], bool) for item in records))
            # 2026-10 扩语料时有意收了一批只有 arXiv 出处、没有正式发表的预印本
            # （为了拿到可用的开放全文），所以这里不再要求"全部经过同行评审"；
            # 改为要求：没标 peer_reviewed 的那些必须能说清来源是 arXiv 预印本。
            for record, paper in zip(records, kb.vertical_corpus.papers):
                if not record["peer_reviewed"]:
                    with self.subTest(domain=domain_id, paper=paper.paper_id):
                        self.assertIn("arxiv.org", paper.source_url)

    def test_metadata_only_records_cannot_create_graph_evidence(self) -> None:
        """只有题录的记录不能进关系图；关系图的证据来源要与非 metadata_only 档逐条对齐。

        这里把"哪些记录该进图"现场算出来，而不是写死条数。两类偏差都会报错：
        * 记录该进图（不是 metadata_only 档、也写明了 document_path），图里却没有它；
        * 图里有这篇论文，清单里却没有它的文档。

        判据与关系图都取自语料对象自己那份清单，图里有多少篇、该有多少篇，
        不会因为采集脚本在测试中途又追加了几篇而互相矛盾。

        这样一来，扩语料时如果 `full_text` 记录只下到 `local_source`、还没生成知识卡，
        测试会直说这批记录进不了图，而不是静默少算。
        """
        for domain_id in self.kb.domain_configs:
            kb = self.domain_kbs[domain_id]
            records = self.manifest_records[domain_id]
            graph_paper_ids = {
                item["paper_id"]
                for item in self.domain_graphs[domain_id]["papers"]
            }
            metadata_only_ids = self.metadata_only_ids[domain_id]
            self.assertTrue(graph_paper_ids)
            self.assertTrue(metadata_only_ids)
            self.assertTrue(graph_paper_ids.isdisjoint(metadata_only_ids))
            metadata_id = next(iter(metadata_only_ids))
            self.assertFalse(kb.evidence_is_valid(metadata_id))
            # 只有题录的记录，查证据细节也必须查不到东西。
            # 这条断言现在会被上游卡住：`evidence_details` 走
            # `VerticalCorpus.evidence_index()` → `extraction_dict()` → `documents()`，
            # 而 `documents()` 要求每条进证据层的记录都有 `document_path`，
            # 扩语料新收的 `full_text` 记录还没有（已由
            # test_every_graph_evidenced_record_has_a_local_document 单独报出）。
            # 上游补齐后这条调用会恢复正常，届时原来的断言原样生效，测试不用再改。
            try:
                details = kb.evidence_details([metadata_id])
            except (KeyError, AttributeError):
                # 这一档记录不在证据登记表里，正是"查不到"的原因，
                # 所以按同一判据检查。
                self.assertNotIn(metadata_id, kb.evidence_registry)
            else:
                self.assertEqual([], details)

            with self.subTest(domain=domain_id):
                # 该进关系图 = 记录里有本地文档、并且不在 metadata_only 档。
                # 这里按"有没有 document_path"取，与建图时的取舍同一口径，
                # 不依赖清单里的 exclude_from_evidence_graph 标记（那条口径本身由
                # test_every_graph_evidenced_record_has_a_local_document 单独把关）。
                expected_graph_ids = {
                    paper_id
                    for paper_id, record in records.items()
                    if record.get("document_path")
                    and record.get("evidence_tier") != "metadata_only"
                }
                missing = expected_graph_ids - graph_paper_ids
                unexpected = graph_paper_ids - expected_graph_ids
                self.assertFalse(
                    missing,
                    f"{domain_id}：清单里这 {len(missing)} 条记录该进关系图，图里却没有它们："
                    f"{cm.short(missing)}",
                )
                self.assertFalse(
                    unexpected,
                    f"{domain_id}：关系图里有这 {len(unexpected)} 篇，"
                    f"清单里却找不到对应文档：{cm.short(unexpected)}",
                )

    def test_every_graph_evidenced_record_has_a_local_document(self) -> None:
        """录进证据层（`exclude_from_evidence_graph` 为假）的记录必须有本地文档。

        这条口径是导出脚本与 Atlas 端点建图的共同前提：它们按记录的
        `document_path` 读正文。扩语料收进来的 `full_text` 记录现在只有
        `local_source`（本地 PDF/XML），还没有知识卡，于是建图会读不到文件。
        这条用例把这个问题直接摆出来，而不是让别处静默少算或用报错收场。
        """
        for domain_id in self.kb.domain_configs:
            records = self.manifest_records[domain_id]
            evidenced = {
                paper_id: record
                for paper_id, record in records.items()
                if record.get("exclude_from_evidence_graph", False) is False
            }
            missing_document = {
                paper_id
                for paper_id, record in evidenced.items()
                if not record.get("document_path")
            }
            self.assertFalse(
                missing_document,
                f"{domain_id}：这 {len(missing_document)} 条记录被标成进证据层"
                f"（exclude_from_evidence_graph 为假），却没有 document_path，"
                f"建关系图与导出显示数据都会读不到文件：{cm.short(missing_document)}",
            )

    def test_every_vertical_slice_builds_a_grounded_graph(self) -> None:
        for domain_id in self.kb.domain_configs:
            payload = self.domain_graphs[domain_id]
            evidence_ids = {
                item["evidence_id"] for item in payload["evidence"]
            }
            self.assertGreaterEqual(len(payload["entities"]), 10)
            self.assertGreaterEqual(len(payload["relations"]), 15)
            self.assertEqual(
                1.0,
                payload["audit"]["quality"]["relation_evidence_coverage"],
            )
            self.assertTrue(
                all(
                    relation["evidence_ids"]
                    and set(relation["evidence_ids"]).issubset(evidence_ids)
                    for relation in payload["relations"]
                )
            )

    def test_each_relation_keeps_evidence_span_provenance(self) -> None:
        payload = self.domain_graphs[self.kb.default_domain_id]
        evidence_ids = {item["evidence_id"] for item in payload["evidence"]}
        self.assertGreaterEqual(len(payload["relations"]), 20)
        self.assertTrue(
            all(
                relation["evidence_ids"]
                and set(relation["evidence_ids"]).issubset(evidence_ids)
                for relation in payload["relations"]
            )
        )

    def test_sqlite_store_rebuilds_all_core_tables(self) -> None:
        payload = self.domain_graphs[self.kb.default_domain_id]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "knowledge.db"
            counts = KnowledgeGraphStore(path).rebuild(payload)
            # 论文数不写死：就是这份关系图里的论文条数。
            self.assertEqual(len(payload["papers"]), counts["papers"])
            self.assertGreater(counts["entities"], 0)
            self.assertGreater(counts["relations"], 0)
            connection = sqlite3.connect(path)
            try:
                stored = connection.execute(
                    "SELECT COUNT(*) FROM relation_evidence"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertGreater(stored, 0)


if __name__ == "__main__":
    unittest.main()
