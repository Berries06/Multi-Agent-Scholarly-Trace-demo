# -*- coding: utf-8 -*-
"""`src/yanhai/independence.py` 的验收用例（确定性、不联网、不读仓库数据）。

九组用例对应任务书里的验收条目：

1. 归一后完全相同的两句（一个只差大小写、一个只差连字符）→ `same_wording`；
2. 同句改几个词、Jaccard 落在 0.6 以上 → `near_duplicate`；
3. 实体集合与数字集合完全一致、措辞不同 → `near_duplicate`（走第二条判据）；
4. 真正独立的两句 → `distinct`；
5. 同义改写的中间档 → `paraphrase`；
6. 缩写与全名（`Deep Knowledge Tracing` + `DKT`）并成一个概念；
   定义对还压过机器猜的类型（并了但要记进 `conflicts_resolved_by_definition`）；
   "一个缩写多个全名"要先按三条等价规则（互为子串 / 词集合 Jaccard ≥ 0.5 /
   字符相似度 ≥ 0.85）判是不是在说同一个东西，判得通就并、报进
   `definitions_rescued_by_equivalence`，判不通才进 `ambiguous_acronyms`；
   碎片全名（缩写重复、一段词重复、以功能词或 -ing 开头）先在归一阶段丢掉；
7. 反例：`graph neural network` 与 `graph neural network potential` 不许并；
   不同领域的同形缩写并起来要报 `conflicts`；
8. 并查集传递闭包：A≈B、B≈C、A 与 C 不直接相似，三条仍合成一个簇；
9. 同一篇论文内的两条近似重复：算同一个簇，独立论文数只加 1。

句子都是构造出来的验收样本（不是论文原文），改动前后只差指定的那几个词，
每条断言都把 Jaccard 落在哪一档写清楚了——阈值一放宽或判据一改，这里就会失败。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import normalize_name  # noqa: E402
from yanhai.independence import (  # noqa: E402
    ENTITY_NUMBER_JACCARD,
    FULL_NAME_CHAR_RATIO,
    NEAR_DUPLICATE_JACCARD,
    PARAPHRASE_JACCARD,
    VERDICT_DISTINCT,
    VERDICT_NEAR_DUPLICATE,
    VERDICT_PARAPHRASE,
    VERDICT_SAME_WORDING,
    EvidenceSpan,
    classify_pair,
    compare_document_frequency,
    concept_keys,
    detect_duplicate_evidence,
    entities_of,
    full_name_fragment_reason,
    full_names_equivalent,
    merge_concepts,
    normalize_concept_key,
    numbers_of,
    summarize_document_frequency,
)


# --------------------------------------------------------------------------
# 构造出来的句子（归一后 35 个词）
# --------------------------------------------------------------------------

BASE = (
    "We train a graph neural network on the Materials Project dataset and evaluate the trained "
    "model on the Open Quantum Materials Database for formation energy prediction and band gap "
    "regression of inorganic crystals, and we report that it achieves a mean absolute error of "
    "0.039 eV per atom with high accuracy and low computational cost."
)
#: 改了两个相邻的词（absolute error → relative deviation）。
BASE_ADJACENT_EDIT = (
    "We train a graph neural network on the Materials Project dataset and evaluate the trained "
    "model on the Open Quantum Materials Database for formation energy prediction and band gap "
    "regression of inorganic crystals, and we report that it achieves a mean relative deviation "
    "of 0.039 eV per atom with high accuracy and low computational cost."
)
#: 改了两个不相邻、且都不是实体的词（evaluate → assess、mean → average）。
BASE_TWO_EDITS = (
    "We train a graph neural network on the Materials Project dataset and assess the trained "
    "model on the Open Quantum Materials Database for formation energy prediction and band gap "
    "regression of inorganic crystals, and we report that it achieves an average absolute error "
    "of 0.039 eV per atom with high accuracy and low computational cost."
)
#: 同上，但改动之一落在实体上（Project → Genome），实体集合就对不上了。
BASE_ENTITY_EDIT = (
    "We train a graph neural network on the Materials Genome dataset and evaluate the trained "
    "model on the Open Quantum Materials Database for formation energy prediction and band gap "
    "regression of inorganic crystals, and we report that it achieves an average absolute error "
    "of 0.039 eV per atom with high accuracy and low computational cost."
)
INDEPENDENT_SENTENCE = (
    "Students who received immediate feedback solved more problems in the tutoring system."
)

# 传递闭包用的三条：B 是 A 的扩写，C 是 B 的后半段，A 与 C 直接比不相似。
CHAIN_A = (
    "We train a graph neural network on the Materials Project dataset and evaluate the trained "
    "model on the Open Catalyst dataset for formation energy prediction."
)
CHAIN_B = (
    "We train a graph neural network on the Materials Project dataset and evaluate the trained "
    "model on the Open Catalyst dataset for formation energy prediction, and it achieves high "
    "accuracy on the Crystal Graph benchmark for adsorption."
)
CHAIN_C = (
    "We evaluate the trained model on the Open Catalyst dataset for formation energy prediction, "
    "and it achieves high accuracy on the Crystal Graph benchmark for adsorption."
)
CHAIN_A_LONGER = (
    "We train a graph neural network on the Materials Project dataset and evaluate the trained "
    "model on the Open Catalyst dataset for formation energy prediction, and it runs with low "
    "computational cost."
)


def span(evidence_id: str, paper_id: str, text: str, section_id: str = "sec-1") -> EvidenceSpan:
    return EvidenceSpan(
        evidence_id=evidence_id,
        paper_id=paper_id,
        section_id=section_id,
        char_start=0,
        char_end=len(text),
        text=text,
    )


class EvidencePairVerdictTests(unittest.TestCase):
    """1–5：四类判定的基本边界。"""

    def test_01_归一后相同_只差大小写与连字符(self) -> None:
        # 只差大小写。
        left = "Deep knowledge tracing predicts student performance from their interaction sequences."
        right = "Deep Knowledge Tracing predicts student performance from their interaction sequences."
        verdict = classify_pair(span("e1", "P1", left), span("e2", "P2", right))
        self.assertEqual(VERDICT_SAME_WORDING, verdict.verdict)
        self.assertEqual(1.0, verdict.jaccard)

        # 只差连字符（single-cell / single cell）。
        left = "Single-cell RNA sequencing reveals heterogeneity in the tumor microenvironment."
        right = "Single cell RNA sequencing reveals heterogeneity in the tumor microenvironment."
        verdict = classify_pair(span("e3", "P1", left), span("e4", "P2", right))
        self.assertEqual(VERDICT_SAME_WORDING, verdict.verdict)
        self.assertEqual(1.0, verdict.jaccard)

    def test_02_改几个词之后仍高于0点6(self) -> None:
        verdict = classify_pair(
            span("e5", "P1", BASE), span("e6", "P2", BASE_ADJACENT_EDIT)
        )
        self.assertGreaterEqual(verdict.jaccard, NEAR_DUPLICATE_JACCARD)
        self.assertEqual(VERDICT_NEAR_DUPLICATE, verdict.verdict)
        # 归一后不是逐字相同，走的是 Jaccard 那条判据。
        self.assertNotEqual(VERDICT_SAME_WORDING, verdict.verdict)
        self.assertIn("≥ 0.6", verdict.basis)

    def test_03_实体与数字一致但措辞不同(self) -> None:
        verdict = classify_pair(span("e7", "P1", BASE), span("e8", "P2", BASE_TWO_EDITS))
        # 这一对必须落在"第二档判据"的区间里：0.4 ≤ Jaccard < 0.6。
        self.assertGreaterEqual(verdict.jaccard, ENTITY_NUMBER_JACCARD)
        self.assertLess(verdict.jaccard, NEAR_DUPLICATE_JACCARD)
        self.assertEqual(VERDICT_NEAR_DUPLICATE, verdict.verdict)
        self.assertIn("实体集合与数字集合一致", verdict.basis)
        # 两边实体集合、数字集合确实一致，判据才有依据。
        self.assertTrue(entities_of(BASE))
        self.assertEqual(entities_of(BASE), entities_of(BASE_TWO_EDITS))
        self.assertEqual(numbers_of(BASE), numbers_of(BASE_TWO_EDITS))

    def test_04_真正独立的两句(self) -> None:
        verdict = classify_pair(
            span("e9", "P1", BASE), span("e10", "P2", INDEPENDENT_SENTENCE)
        )
        self.assertEqual(VERDICT_DISTINCT, verdict.verdict)
        self.assertLess(verdict.jaccard, PARAPHRASE_JACCARD)

    def test_05_同义改写的中间档单独报出来(self) -> None:
        verdict = classify_pair(span("e11", "P1", BASE), span("e12", "P2", BASE_ENTITY_EDIT))
        self.assertGreaterEqual(verdict.jaccard, PARAPHRASE_JACCARD)
        self.assertLess(verdict.jaccard, NEAR_DUPLICATE_JACCARD)
        self.assertEqual(VERDICT_PARAPHRASE, verdict.verdict)
        # 实体集合对不上，所以第二条判据不能把这一对算成近似重复。
        self.assertNotEqual(entities_of(BASE), entities_of(BASE_ENTITY_EDIT))

    def test_01b_短句完全相同也能抓到(self) -> None:
        # 短句产不出 5 个 shingle，靠"归一文本相同"这条索引抓。
        verdict = classify_pair(span("e13", "P1", "DKT works."), span("e14", "P2", "dkt works"))
        self.assertEqual(VERDICT_SAME_WORDING, verdict.verdict)


class ConceptMergeTests(unittest.TestCase):
    """6–7：概念层的同义合并与反例。"""

    def test_06_定义对把全名与缩写并成一条(self) -> None:
        result = merge_concepts(
            [
                {"canonical": "Deep Knowledge Tracing", "entity_type": "METHOD"},
                {"canonical": "DKT", "entity_type": "METHOD"},
            ],
            {"DKT": ["Deep Knowledge Tracing"]},
        )
        self.assertEqual([], [item.to_dict() for item in result.conflicts])
        self.assertEqual(1, len(result.concepts))
        merged = result.concepts[0]
        self.assertEqual("Deep Knowledge Tracing", merged.canonical)
        self.assertEqual(["Deep Knowledge Tracing", "DKT"], merged.merged_from)
        self.assertIn("definition_pair", merged.basis)
        self.assertIn("DKT", merged.aliases)
        self.assertEqual(1, result.stats["merged_away_count"])

    def test_06b_大小写与复数变体也并(self) -> None:
        result = merge_concepts(
            [
                {"canonical": "Knowledge Tracing", "entity_type": "METHOD"},
                {"canonical": "knowledge tracing", "entity_type": "METHOD"},
                {"canonical": "knowledge-tracing", "entity_type": "METHOD"},
                {"canonical": "Knowledge Tracings", "entity_type": "METHOD"},
            ]
        )
        self.assertEqual(1, len(result.concepts))
        merged = result.concepts[0]
        self.assertEqual(4, len(merged.merged_from))
        # 只差大小写、只差连字符、只差复数，三种判据都要出现在 basis 里。
        self.assertIn("case", merged.basis)
        self.assertIn("hyphen_space", merged.basis)
        self.assertIn("plural", merged.basis)

    def test_07_派生词一律不并(self) -> None:
        result = merge_concepts(
            [
                {"canonical": "graph neural network", "entity_type": "METHOD"},
                {"canonical": "graph neural network potential", "entity_type": "METHOD"},
            ]
        )
        self.assertEqual(2, len(result.concepts))
        canonicals = sorted(item.canonical for item in result.concepts)
        self.assertEqual(["graph neural network", "graph neural network potential"], canonicals)
        for item in result.concepts:
            self.assertEqual([], item.basis)
            self.assertEqual([item.canonical], item.merged_from)

    def test_07b_同形缩写类型冲突要报conflicts(self) -> None:
        result = merge_concepts(
            [
                {
                    "canonical": "Association for Computational Linguistics",
                    "aliases": ["ACL"],
                    "entity_type": "DOMAIN",
                    "domain_id": "scientific-ie-kg",
                },
                {
                    "canonical": "Argument Classification",
                    "aliases": ["ACL"],
                    "entity_type": "TASK",
                    "domain_id": "scientific-ie-kg",
                },
            ]
        )
        self.assertEqual(1, len(result.conflicts))
        conflict = result.conflicts[0]
        self.assertEqual("acl", conflict.key)
        self.assertEqual(
            ["Argument Classification", "Association for Computational Linguistics"],
            sorted(conflict.canonicals),
        )
        self.assertEqual(["DOMAIN", "TASK"], sorted(conflict.entity_types))
        # 冲突的两条不许强并，原样各自留着。
        self.assertEqual(2, len(result.concepts))
        self.assertEqual(1, result.stats["conflict_count"])

    def test_06e_定义对压过机器猜的类型(self) -> None:
        """定义对是原文里明写的 `全名 (ACRONYM)`，机器猜的类型不该否决它。"""
        result = merge_concepts(
            [
                {
                    "canonical": "crystal graph convolutional neural network",
                    "entity_type": "DOMAIN",
                },
                {"canonical": "CGCNN", "entity_type": "METHOD"},
            ],
            {"CGCNN": ["crystal graph convolutional neural network"]},
        )
        self.assertEqual(1, len(result.concepts))
        merged = result.concepts[0]
        self.assertEqual("crystal graph convolutional neural network", merged.canonical)
        self.assertEqual(
            ["crystal graph convolutional neural network", "CGCNN"], merged.merged_from
        )
        # 类型取全名那一侧。
        self.assertEqual("DOMAIN", merged.entity_type)
        # 冲突原样记下来，不许悄悄丢。
        self.assertEqual([], result.conflicts)
        self.assertEqual(1, len(result.resolved_conflicts))
        resolved = result.resolved_conflicts[0]
        self.assertEqual(
            ["crystal graph convolutional neural network", "CGCNN"], resolved.canonicals
        )
        self.assertEqual(["DOMAIN", "METHOD"], resolved.entity_types)
        self.assertEqual("crystal graph convolutional neural network", resolved.resolved_from)
        self.assertEqual("DOMAIN", resolved.resolved_entity_type)
        self.assertEqual(1, result.stats["resolved_conflict_count"])
        self.assertEqual(0, result.stats["conflict_count"])

    def test_06f_关掉类型压制就是老口径(self) -> None:
        result = merge_concepts(
            [
                {"canonical": "crystal graph convolutional neural network", "entity_type": "DOMAIN"},
                {"canonical": "CGCNN", "entity_type": "METHOD"},
            ],
            {"CGCNN": ["crystal graph convolutional neural network"]},
            definition_overrides_type=False,
        )
        self.assertEqual(2, len(result.concepts))
        self.assertEqual(1, len(result.conflicts))
        self.assertEqual([], result.resolved_conflicts)

    def test_07c_同形异义缩写不许并(self) -> None:
        """一个缩写对应两个不同全名 → 硬约束：这一组不并，单独报出来。"""
        result = merge_concepts(
            [
                {"canonical": "relation extraction", "entity_type": "DOMAIN"},
                {"canonical": "pl marker", "entity_type": "DOMAIN"},
                {"canonical": "RE", "entity_type": "METHOD"},
            ],
            {"RE": ["relation extraction", "pl marker"]},
            definition_papers={
                "RE": {"relation extraction": ["P1", "P2"], "pl marker": ["P3"]}
            },
        )
        self.assertEqual(3, len(result.concepts))
        self.assertEqual(1, len(result.ambiguity))
        item = result.ambiguity[0]
        self.assertEqual("RE", item.acronym)
        self.assertEqual("re", item.key)
        self.assertEqual(["relation extraction", "pl marker"], item.full_names)
        self.assertEqual(["pl marker", "relation extraction"], item.normalized_full_names)
        self.assertEqual(["P1", "P2"], item.papers_by_full_name["relation extraction"])
        self.assertEqual(["P3"], item.papers_by_full_name["pl marker"])
        self.assertEqual(
            ["RE", "pl marker", "relation extraction"], sorted(item.canonicals)
        )
        self.assertEqual([], result.resolved_conflicts)
        self.assertEqual(1, result.stats["ambiguous_acronym_count"])

    def test_07d_等价规则把疑似歧义救回来(self) -> None:
        # `area under curve` 与 `area under the curve` 词集合 Jaccard = 0.75 ≥ 0.5，
        # 算在说同一个东西 → 不算同形异义，照并。
        result = merge_concepts(
            [
                {"canonical": "area under curve", "entity_type": "METRIC"},
                {"canonical": "AUC", "entity_type": "METRIC"},
            ],
            {"AUC": ["area under curve", "area under the curve"]},
        )
        self.assertEqual(1, len(result.concepts))
        self.assertEqual([], result.ambiguity)
        self.assertEqual(1, len(result.rescued_definitions))
        rescued = result.rescued_definitions[0]
        self.assertEqual("AUC", rescued.acronym)
        self.assertIn("word_jaccard", rescued.rules_hit)
        self.assertEqual(1, result.stats["rescued_definition_count"])

    def test_07f_三条等价规则各自生效(self) -> None:
        # 1) 互为子串
        self.assertEqual((True, "substring"), full_names_equivalent(
            "principal component analysis", "preceding principal component analysis"
        ))
        # 2) 词集合 Jaccard ≥ 0.5
        self.assertEqual((True, "word_jaccard"), full_names_equivalent(
            "crystal graph convolution neural network",
            "crystal graph convolutional neural network",
        ))
        # 3) 字符相似度 ≥ 0.85（拼写差异那一类）。
        #    注意顺序：先判子串、再判词集合 Jaccard，两条都不成立才看字符相似度。
        #    `adjust rand index` / `adjusted rand index` 会先被词集合 Jaccard 命中，
        #    所以这里用一对只有拼写差、没有词重合的。
        self.assertEqual((True, "word_jaccard"), full_names_equivalent(
            "adjust rand index", "adjusted rand index"
        ))
        self.assertEqual((True, "char_similarity"), full_names_equivalent(
            "kullback leiber", "kullback leibler"
        ))
        # 三条都不满足：真的不是一回事
        self.assertEqual((False, ""), full_names_equivalent(
            "relation extraction", "pl marker"
        ))
        self.assertEqual((False, ""), full_names_equivalent(
            "mean absolute error", "baseline skill"
        ))

    def test_07g_拼写差刚好不到阈值就仍算歧义(self) -> None:
        """`gene ontology` vs `gene ontogeny` 字符相似度 0.8462 < 0.85，按现行阈值仍判歧义。

        这一条把阈值卡在哪写死在测试里：以后谁把 `FULL_NAME_CHAR_RATIO` 调低到 0.84，
        这个用例会失败，提醒他这是有意的改动。
        """
        equivalent, _rule = full_names_equivalent("gene ontology", "gene ontogeny")
        self.assertFalse(equivalent)
        result = merge_concepts(
            [
                {"canonical": "gene ontology", "entity_type": "DOMAIN"},
                {"canonical": "GO", "entity_type": "METHOD"},
            ],
            {"GO": ["gene ontology", "gene ontogeny"]},
        )
        self.assertEqual(2, len(result.concepts))
        self.assertEqual(1, len(result.ambiguity))
        pair = result.ambiguity[0].blocked_pairs[0]
        self.assertLess(pair["char_ratio"], FULL_NAME_CHAR_RATIO)
        self.assertGreater(pair["char_ratio"], 0.84)

    def test_07h_碎片全名的判据(self) -> None:
        # 缩写本身出现两次以上、或一段词重复出现
        self.assertEqual("repeated_phrase", full_name_fragment_reason(
            "knowledge tracing knowledge tracing", "KT"
        ))
        self.assertEqual("repeated_phrase", full_name_fragment_reason(
            "bayesian knowledge tracing bayesian knowledge tracing", "BKT"
        ))
        self.assertEqual("acronym_repeated", full_name_fragment_reason("mps mps state", "MPS"))
        # 以功能词开头
        self.assertEqual("leading_function_word", full_name_fragment_reason(
            "while bayesian knowledge tracing", "BKT"
        ))
        self.assertEqual("leading_function_word", full_name_fragment_reason(
            "the quantum approximate optimization algorithm", "QAOA"
        ))
        # 以明确的引导分词/引导词开头（白名单，见 LEADING_PARTICIPLE_MARKERS）
        self.assertEqual("leading_participle", full_name_fragment_reason(
            "preceding principal component analysis", "PCA"
        ))
        self.assertEqual("leading_participle", full_name_fragment_reason(
            "following the training procedure", "FTP"
        ))
        self.assertEqual("leading_participle", full_name_fragment_reason(
            "based on the experimental result", "BOTER"
        ))
        # 别的 -ing 词不算碎片：这些是正经全名（2026-10-17 把这条收窄之后的行为）
        self.assertEqual("", full_name_fragment_reason("scanning electron microsopy", "SEM"))
        self.assertEqual("", full_name_fragment_reason("sequencing quality control", "SEQC"))
        self.assertEqual("", full_name_fragment_reason("learning management system", "LMS"))
        self.assertEqual(
            "",
            full_name_fragment_reason(
                "superconducting nanowire single photon detector", "SNSPD"
            ),
        )
        self.assertEqual(
            "",
            full_name_fragment_reason(
                "meeting of the association for computational linguistic", "ACL"
            ),
        )
        # 正常全名不是碎片
        self.assertEqual("", full_name_fragment_reason("principal component analysis", "PCA"))
        self.assertEqual("", full_name_fragment_reason("graph neural network", "GNN"))

    def test_07i_碎片丢掉之后不再算歧义(self) -> None:
        result = merge_concepts(
            [
                {"canonical": "principal component analysis", "entity_type": "METHOD"},
                {"canonical": "PCA", "entity_type": "METHOD"},
            ],
            {"PCA": ["preceding principal component analysis", "principal component analysis"]},
        )
        self.assertEqual(1, len(result.concepts))
        self.assertEqual([], result.ambiguity)
        self.assertEqual(1, len(result.rescued_definitions))
        self.assertEqual(
            ["preceding principal component analysis"],
            [item["full_name"] for item in result.rescued_definitions[0].dropped_fragments],
        )
        self.assertEqual(1, result.stats["dropped_fragment_count"])

    def test_07j_CGCNN三个拼法要并成一个(self) -> None:
        """三个拼法只在词形上差一点（词集合 Jaccard ≥ 0.5），算在说同一个东西。"""
        result = merge_concepts(
            [
                {
                    "canonical": "crystal graph convolutional neural network",
                    "entity_type": "DOMAIN",
                },
                {"canonical": "CGCNN", "entity_type": "METHOD"},
            ],
            {
                "CGCNN": [
                    "convolutional graph neural network",
                    "crystal graph convolution neural network",
                    "crystal graph convolutional neural network",
                ]
            },
        )
        self.assertEqual(1, len(result.concepts))
        self.assertEqual([], result.ambiguity)
        self.assertEqual("crystal graph convolutional neural network", result.concepts[0].canonical)
        rescued = result.rescued_definitions[0]
        self.assertIn("word_jaccard", rescued.rules_hit)
        pairs = rescued.rules_hit["word_jaccard"]
        self.assertEqual(3, len(pairs))

    def test_07e_同形异义不牵连无关的概念(self) -> None:
        # 同一批里的另一组（缩写只有一个全名）该并还是要并。
        result = merge_concepts(
            [
                {"canonical": "relation extraction", "entity_type": "DOMAIN"},
                {"canonical": "pl marker", "entity_type": "DOMAIN"},
                {"canonical": "RE", "entity_type": "METHOD"},
                {"canonical": "uniform manifold approximation and projection", "entity_type": "METHOD"},
                {"canonical": "UMAP", "entity_type": "METHOD"},
            ],
            {"RE": ["relation extraction", "pl marker"], "UMAP": ["uniform manifold approximation and projection"]},
        )
        canonicals = sorted(item.canonical for item in result.concepts)
        self.assertIn("uniform manifold approximation and projection", canonicals)
        self.assertNotIn("UMAP", canonicals)
        self.assertEqual(1, len(result.ambiguity))

    def test_06c_概念键与extraction归一一致(self) -> None:
        # `concept_keys` 的"分隔符层"就是把 `-` `_` `/` 与空白当同一个分隔符之后的结果，
        # 与 `yanhai.extraction.normalize_name` 是同一个键（`+` 除外，那个键保留加号）。
        samples = [
            "Deep Knowledge Tracing",
            "single-cell RNA",
            "AKT/PKB pathway",
            "graph_neural network",
            "  Spaced   Out  ",
            "Crystal-Graph Convolutional Neural Network",
        ]
        for text in samples:
            self.assertEqual(
                normalize_name(text),
                concept_keys(text)[1],
                f"{text!r} 的归一键与 extraction.normalize_name 不一致",
            )

    def test_06d_最紧的键就是归一键(self) -> None:
        self.assertEqual(
            normalize_concept_key("Graph Neural Networks"),
            concept_keys("graph neural network")[2],
        )


class DuplicateClusterTests(unittest.TestCase):
    """8–9：聚类与传递闭包。"""

    def test_08_传递闭包合成一个簇_直接比不相似(self) -> None:
        spans = [
            span("ev-a", "paper-A", CHAIN_A),
            span("ev-b", "paper-B", CHAIN_B),
            span("ev-c", "paper-C", CHAIN_C),
        ]
        # 先把三条两两直接比一遍：A-C 不是近似重复。
        direct_ac = classify_pair(spans[0], spans[2])
        direct_ab = classify_pair(spans[0], spans[1])
        direct_bc = classify_pair(spans[1], spans[2])
        self.assertEqual(VERDICT_NEAR_DUPLICATE, direct_ab.verdict)
        self.assertEqual(VERDICT_NEAR_DUPLICATE, direct_bc.verdict)
        self.assertEqual(VERDICT_DISTINCT, direct_ac.verdict)
        self.assertLess(direct_ac.jaccard, PARAPHRASE_JACCARD)

        report = detect_duplicate_evidence(spans)
        self.assertEqual(1, len(report.clusters), "传递闭包没把三条并成一个簇")
        cluster = report.clusters[0]
        self.assertEqual(["ev-a", "ev-b", "ev-c"], cluster.member_ids)
        self.assertEqual(["paper-A", "paper-B", "paper-C"], cluster.paper_ids)
        self.assertEqual(3, cluster.independent_papers)
        self.assertEqual(3, cluster.pair_count)
        # 种子是簇内相似度最高的那一对。
        self.assertGreaterEqual(cluster.seed.jaccard, max(direct_ab.jaccard, direct_bc.jaccard))
        self.assertEqual(cluster.max_similarity, cluster.seed.jaccard)
        self.assertLessEqual(cluster.min_similarity, direct_ac.jaccard)

    def test_09_同一篇论文内的近似重复只算一条独立证据(self) -> None:
        spans = [
            span("ev-x", "paper-X", CHAIN_A),
            span("ev-y", "paper-X", CHAIN_A_LONGER),
        ]
        report = detect_duplicate_evidence(spans)
        self.assertEqual(1, len(report.clusters))
        cluster = report.clusters[0]
        self.assertEqual(["paper-X"], cluster.paper_ids)
        self.assertEqual(1, cluster.independent_papers)
        self.assertEqual(1, report.independent_evidence_count)

        hits = {"formation energy prediction": spans}
        records = compare_document_frequency(hits, report)
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual(1, record.raw_papers)
        self.assertEqual(1, record.independent_papers)
        self.assertEqual(2, record.raw_evidence)
        self.assertEqual(1, record.independent_evidence_units)
        self.assertEqual(1, record.absorbed_evidence)
        self.assertEqual(0, record.duplicate_papers)


class DocumentFrequencyTests(unittest.TestCase):
    """C：原始 DF 与独立论文数都要报，差就是被重复算的次数。"""

    def test_跨论文重复时两个DF都报(self) -> None:
        spans = [
            span("ev-1", "paper-1", CHAIN_A),
            span("ev-2", "paper-2", CHAIN_B),
            span("ev-3", "paper-3", INDEPENDENT_SENTENCE),
        ]
        report = detect_duplicate_evidence(spans)
        self.assertEqual(1, len(report.clusters))
        hits = {"formation energy prediction": spans}
        record = compare_document_frequency(hits, report)[0]
        self.assertEqual(3, record.raw_papers)
        self.assertEqual(2, record.independent_papers)
        self.assertEqual(1, record.duplicate_papers)
        self.assertEqual(3, record.raw_evidence)
        self.assertEqual(2, record.independent_evidence_units)
        self.assertEqual(1, record.absorbed_evidence)
        self.assertEqual([["paper-1", "paper-2"], ["paper-3"]], record.independent_paper_groups)

        summary = summarize_document_frequency([record])
        self.assertEqual(3, summary["total_raw_df"])
        self.assertEqual(2, summary["total_independent_df"])
        self.assertEqual(1, summary["total_duplicate_df"])
        self.assertEqual(1, summary["concepts_with_drop"])

    def test_没有重复时两个DF相等(self) -> None:
        spans = [
            span("ev-4", "paper-4", BASE),
            span("ev-5", "paper-5", INDEPENDENT_SENTENCE),
        ]
        report = detect_duplicate_evidence(spans)
        self.assertEqual([], report.clusters)
        record = compare_document_frequency({"x": spans}, report)[0]
        self.assertEqual(record.raw_papers, record.independent_papers)
        self.assertEqual(0, record.duplicate_papers)


class DeterminismTests(unittest.TestCase):
    """同一输入同一结果：哈希用 blake2b（不吃 PYTHONHASHSEED），顺序都排过。"""

    def test_结果可复现(self) -> None:
        spans = [
            span("ev-a", "paper-A", CHAIN_A),
            span("ev-b", "paper-B", CHAIN_B),
            span("ev-c", "paper-C", CHAIN_C),
            span("ev-d", "paper-D", CHAIN_B),
        ]
        first = json.dumps(
            detect_duplicate_evidence(spans).to_dict(), ensure_ascii=False, sort_keys=True
        )
        shuffled = [spans[3], spans[0], spans[2], spans[1]]
        second = json.dumps(
            detect_duplicate_evidence(shuffled).to_dict(), ensure_ascii=False, sort_keys=True
        )
        self.assertEqual(first, second)

    def test_阈值参数写进结果方便复核(self) -> None:
        params = detect_duplicate_evidence([span("ev-1", "p1", BASE)]).parameters
        self.assertEqual(NEAR_DUPLICATE_JACCARD, params["jaccard_threshold"])
        self.assertEqual(ENTITY_NUMBER_JACCARD, params["entity_number_jaccard"])
        self.assertEqual(PARAPHRASE_JACCARD, params["paraphrase_jaccard"])
        self.assertEqual("blake2b-64bit", params["shingle_hash"])

    def test_重复的证据标识要报错(self) -> None:
        with self.assertRaises(ValueError):
            detect_duplicate_evidence(
                [span("dup", "p1", BASE), span("dup", "p2", CHAIN_A)]
            )


if __name__ == "__main__":
    unittest.main()
