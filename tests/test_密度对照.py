"""密度对照与证据偏移抽查的两份评测脚本，加上词表合并规则。

这三样都不碰 src/：``scripts/抽取/生成抽取词表.py``（候选词表拼成抽取器认的形状）、
``scripts/评测/密度对照.py``（两份库逐领域比密度）、
``scripts/评测/证据忠实性抽查.py``（证据偏移能不能切回原文）。
脚本文件名是中文，import 不走 ``import`` 语句，用 ``importlib`` 按路径加载。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def load_script(module_name: str, relative_path: str):
    """按文件路径加载中文文件名的脚本，不走 import 语句。"""
    spec = importlib.util.spec_from_file_location(
        module_name, PROJECT_ROOT / relative_path
    )
    if spec is None or spec.loader is None:  # pragma: no cover - 路径写错才会发生
        raise RuntimeError(f"加载不了 {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wordlist = load_script("生成抽取词表", "scripts/抽取/生成抽取词表.py")
density = load_script("密度对照", "scripts/评测/密度对照.py")
faithfulness = load_script("证据忠实性抽查", "scripts/评测/证据忠实性抽查.py")

ENTITY_TYPES = {"METHOD", "TASK", "DATASET", "METRIC", "FINDING", "LIMITATION", "DOMAIN"}


class AliasMergeTest(unittest.TestCase):
    def test_alias_cap_keeps_the_most_frequent_writes(self) -> None:
        """surface_forms 落盘时已按出现次数排序，取前 cap 个就是取最高频的几个。"""
        aliases = wordlist.merge_aliases(
            ["Knowledge Tracing", "knowledge tracing model", "KT model", "kt"],
            "knowledge tracing",
            cap=2,
        )
        self.assertEqual(["Knowledge Tracing", "knowledge tracing model"], aliases)

    def test_alias_identical_to_canonical_is_dropped(self) -> None:
        aliases = wordlist.merge_aliases(
            ["relation extraction", "Relation Extraction", "relation extraction"],
            "relation extraction",
            cap=6,
        )
        self.assertEqual(["Relation Extraction"], aliases)

    def test_alias_forms_are_whitespace_normalized(self) -> None:
        self.assertEqual(
            ["the neural network"],
            wordlist.merge_aliases(["  the\nneural   network  "], "neural network", cap=6),
        )


class VocabularyPayloadTest(unittest.TestCase):
    def _payload(
        self,
        candidates: list[dict],
        *,
        definitions_found: dict | None = None,
        min_df: int = 3,
        alias_cap: int = 6,
    ) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            source: dict = {"domain_id": "示例", "candidates": candidates}
            if definitions_found is not None:
                source["definitions_found"] = definitions_found
            path.write_text(
                json.dumps(source, ensure_ascii=False),
                encoding="utf-8",
            )
            payload, _ = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=min_df, alias_cap=alias_cap
            )
        return payload

    def test_document_frequency_below_the_filter_is_dropped(self) -> None:
        payload = self._payload(
            [
                {"canonical": "keep me", "document_frequency": 3, "guess_type": "TASK"},
                {"canonical": "drop me", "document_frequency": 2, "guess_type": "TASK"},
            ]
        )
        self.assertEqual(1, payload["concept_count"])
        self.assertEqual(["keep me"], [item["canonical"] for item in payload["concepts"]])

    def test_type_outside_the_seven_falls_back_to_method(self) -> None:
        payload = self._payload(
            [
                {"canonical": "other type", "document_frequency": 4, "guess_type": "OTHER"},
                {"canonical": "no type", "document_frequency": 4},
                {"canonical": "task type", "document_frequency": 4, "guess_type": "TASK"},
            ]
        )
        types = {item["canonical"]: item["entity_type"] for item in payload["concepts"]}
        self.assertEqual("METHOD", types["other type"])
        self.assertEqual("METHOD", types["no type"])
        self.assertEqual("TASK", types["task type"])
        self.assertEqual("METHOD", payload["type_mapping"]["fallback"])

    def test_same_canonical_is_merged_once_with_the_first_type(self) -> None:
        payload = self._payload(
            [
                {
                    "canonical": "atomistic line graph neural",
                    "document_frequency": 7,
                    "guess_type": "METHOD",
                    "surface_forms": ["atomistic line graph neural"],
                },
                {
                    "canonical": "atomistic line graph neural",
                    "document_frequency": 5,
                    "guess_type": "DOMAIN",
                    "surface_forms": ["Atomistic Line Graph Neural"],
                },
            ]
        )
        self.assertEqual(1, payload["concept_count"])
        self.assertEqual(1, payload["duplicates_merged"])
        self.assertEqual("METHOD", payload["concepts"][0]["entity_type"])
        self.assertEqual(
            ["Atomistic Line Graph Neural"], payload["concepts"][0]["aliases"]
        )

    def test_payload_keeps_the_candidate_status_and_scale(self) -> None:
        payload = self._payload(
            [
                {
                    "canonical": "knowledge tracing",
                    "document_frequency": 6,
                    "guess_type": "DOMAIN",
                    "surface_forms": ["Knowledge Tracing", "knowledge tracing"],
                }
            ]
        )
        self.assertEqual("candidate_pending_human_review", payload["status"])
        self.assertEqual(1, payload["concept_count"])
        self.assertEqual(1, payload["alias_count"])
        self.assertEqual(">= 3", payload["filter"]["rule"])


class AliasFilterTest(unittest.TestCase):
    """别名的三道过滤：长度 <2、常见英文功能词、短全大写缩略语没有定义。"""

    def _rejections(self, surface_forms: list[str]) -> tuple[dict[str, str], list[str]]:
        """过一遍 filter_aliases，返回 ({被丢掉的写法: 原因}, 留下来的写法)。"""
        kept, rejected = wordlist.filter_aliases(
            surface_forms, "knowledge tracing", cap=6, defined=set()
        )
        return {form: wordlist.alias_rejection_reason(form, defined=set()) for form in rejected}, kept

    def test_single_letter_alias_is_dropped(self) -> None:
        rejected, kept = self._rejections(["X", "knowledge tracing model"])
        self.assertEqual({"X": "too_short"}, rejected)
        self.assertEqual(["knowledge tracing model"], kept)

    def test_common_english_word_alias_is_dropped(self) -> None:
        rejected, kept = self._rejections(["OF", "of", "In", "it", "IS"])
        self.assertEqual(
            {
                "OF": "common_english_word",
                "of": "common_english_word",
                "In": "common_english_word",
                "it": "common_english_word",
                "IS": "common_english_word",
            },
            rejected,
        )
        self.assertEqual([], kept)

    def test_short_uppercase_alias_without_definition_is_dropped(self) -> None:
        rejected, kept = self._rejections(["NA", "GNN"])
        self.assertEqual(
            {
                "NA": "short_acronym_without_definition",
                "GNN": "short_acronym_without_definition",
            },
            rejected,
        )
        self.assertEqual([], kept)

    def test_common_english_word_wins_over_the_acronym_rule(self) -> None:
        """``OR`` 两条都符合（全大写 2 位、也是功能词），记前面那条。"""
        rejected, _ = self._rejections(["OR"])
        self.assertEqual({"OR": "common_english_word"}, rejected)

    def test_short_uppercase_alias_with_a_definition_is_kept(self) -> None:
        kept, rejected = wordlist.filter_aliases(
            ["GNN", "KT"],
            "graph neural network",
            cap=6,
            defined=wordlist.defined_acronyms(
                {"definitions_found": {"GNN": ["graph neural network"]}}
            ),
        )
        # GNN 有定义：留；KT 没有定义也没有数字：丢。
        self.assertEqual(["GNN"], kept)
        self.assertEqual(["KT"], rejected)

    def test_short_uppercase_alias_with_a_digit_is_kept(self) -> None:
        kept, rejected = wordlist.filter_aliases(
            ["GPT-4", "H2O"], "water model", cap=6, defined=set()
        )
        # 带连字符和数字的写法不是"全大写 2–3 位"那一类，直接留。
        self.assertEqual(["GPT-4", "H2O"], kept)
        self.assertEqual([], rejected)

    def test_filtering_happens_before_the_alias_cap(self) -> None:
        """被丢掉的名额不该占掉 cap：cap=2 时留下的应该是两个真别名。"""
        kept, rejected = wordlist.filter_aliases(
            ["OF", "IN", "knowledge tracing model", "bayesian knowledge tracing"],
            "knowledge tracing",
            cap=2,
            defined=set(),
        )
        self.assertEqual(["knowledge tracing model", "bayesian knowledge tracing"], kept)
        self.assertEqual(["OF", "IN"], rejected)

    def test_function_word_list_is_plain_general_english(self) -> None:
        """这份表是通用英语功能词，人名、领域缩写不该在里面。"""
        for word in ("of", "in", "by", "or", "it", "the", "which", "would"):
            self.assertIn(word, wordlist.COMMON_ENGLISH_FUNCTION_WORDS)
        for word in ("gnn", "cgcnn", "scierc"):
            self.assertNotIn(word, wordlist.COMMON_ENGLISH_FUNCTION_WORDS)

    def test_rejections_are_written_into_the_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            path.write_text(
                json.dumps(
                    {
                        "domain_id": "示例",
                        "candidates": [
                            {
                                "canonical": "knowledge tracing",
                                "document_frequency": 6,
                                "guess_type": "DOMAIN",
                                "surface_forms": ["OF", "in", "X", "Knowledge Tracing"],
                            }
                        ],
                        "definitions_found": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload, stats = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=3, alias_cap=6
            )
        self.assertEqual(3, payload["rejected_alias_total"])
        self.assertEqual(
            {
                "common_english_word": 2,
                "short_acronym_without_definition": 0,
                "generic_structural_term": 0,
                "too_short": 1,
            },
            payload["rejected_reasons"],
        )
        self.assertEqual(
            {"OF", "in", "X"},
            {item["alias"] for item in payload["rejected_aliases"]},
        )
        for item in payload["rejected_aliases"]:
            self.assertIn(item["reason"], wordlist.ALIAS_REJECTION_REASONS)
        self.assertEqual(3, stats["rejected_alias_total"])
        self.assertEqual(["Knowledge Tracing"], payload["concepts"][0]["aliases"])

    def test_short_uppercase_canonicals_are_rejected_and_recorded(self) -> None:
        """第三轮：canonical 也过判据；OF 进不了概念表，但要留在 rejected_canonicals 里。"""
        payload = self._payload_short_canonical()
        self.assertEqual(0, payload["concept_count"])
        self.assertEqual(1, payload["rejected_canonical_total"])
        self.assertEqual(
            {
                "common_english_word": 1,
                "short_acronym_without_definition": 0,
                "generic_structural_term": 0,
            },
            payload["rejected_canonical_reasons"],
        )
        self.assertEqual(
            [
                {
                    "canonical": "OF",
                    "reason": "common_english_word",
                    "domain_id": "示例",
                    "document_frequency": 9,
                    "entity_type": "METHOD",
                }
            ],
            payload["rejected_canonicals"],
        )
        kept = payload["kept_short_uppercase"]
        self.assertEqual(0, kept["canonical_count"])
        self.assertEqual(0, kept["alias_count"])
        self.assertEqual([], kept["items"])

    def _payload_short_canonical(self) -> dict:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            path.write_text(
                json.dumps(
                    {
                        "domain_id": "示例",
                        "candidates": [
                            {
                                "canonical": "OF",
                                "document_frequency": 9,
                                "guess_type": "METHOD",
                                "surface_forms": ["OF", "of"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload, _ = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=3, alias_cap=6
            )
        return payload


class CanonicalFilterTest(unittest.TestCase):
    """canonical 这一层的判据：功能词、短全大写没定义、长度 ≥4 一律留。"""

    def _reason(self, canonical: str, *, defined: set[str] | None = None) -> str:
        return wordlist.canonical_rejection_reason(
            canonical, defined=defined if defined is not None else set()
        )

    def test_common_english_function_words_are_rejected(self) -> None:
        for canonical in ("OF", "IN", "BY", "OR", "IT", "AT", "HE", "HER", "ONLY", "WOULD"):
            self.assertEqual(
                "common_english_word", self._reason(canonical), f"{canonical} 该丢"
            )

    def test_a_multi_word_name_of_only_function_words_is_rejected(self) -> None:
        self.assertEqual("common_english_word", self._reason("in by"))
        self.assertEqual("common_english_word", self._reason("OF THE"))

    def test_short_uppercase_without_definition_is_rejected(self) -> None:
        self.assertEqual(
            "short_acronym_without_definition", self._reason("NA")
        )
        self.assertEqual(
            "short_acronym_without_definition", self._reason("DKT")
        )

    def test_short_uppercase_with_a_definition_is_kept(self) -> None:
        self.assertEqual("", self._reason("DKT", defined={"DKT", "deep knowledge tracing"}))
        self.assertEqual("", self._reason("AKT", defined={"AKT"}))

    def test_short_uppercase_with_a_digit_is_kept(self) -> None:
        self.assertEqual("", self._reason("3DG"))

    def test_long_uppercase_is_kept_regardless(self) -> None:
        for canonical in ("CGCNN", "MEGNet", "SciERC", "GNoME"):
            self.assertEqual("", self._reason(canonical), f"{canonical} 该留")

    def test_function_word_wins_over_the_acronym_rule(self) -> None:
        """``OR`` 两条都符合（全大写 2 位、也是功能词），记前面那条。"""
        self.assertEqual("common_english_word", self._reason("OR"))

    def test_a_long_lowercase_phrase_survives_the_function_word_check(self) -> None:
        """功能词按整条名字查：`case study figure` 这种版式短语不归这条管。"""
        self.assertEqual("", self._reason("case study figure"))
        self.assertEqual("", self._reason("knowledge graph"))

    def test_rejections_are_written_into_the_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            path.write_text(
                json.dumps(
                    {
                        "domain_id": "示例",
                        "candidates": [
                            {
                                "canonical": "OF",
                                "document_frequency": 9,
                                "guess_type": "METHOD",
                                "surface_forms": ["OF"],
                            },
                            {
                                "canonical": "XQ",
                                "document_frequency": 4,
                                "guess_type": "METRIC",
                                "surface_forms": ["XQ"],
                            },
                            {
                                "canonical": "NA",
                                "document_frequency": 5,
                                "guess_type": "METRIC",
                                "surface_forms": ["NA"],
                            },
                            {
                                "canonical": "CGCNN",
                                "document_frequency": 6,
                                "guess_type": "METHOD",
                                "surface_forms": ["CGCNN"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload, stats = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=3, alias_cap=6
            )
        # NA 的 DF 到门槛（≥5）：按第四轮的放宽留下；XQ 的 DF 是 4：丢。
        self.assertEqual(2, payload["concept_count"])
        self.assertEqual(
            ["NA", "CGCNN"], [item["canonical"] for item in payload["concepts"]]
        )
        self.assertEqual(2, payload["rejected_canonical_total"])
        self.assertEqual(2, stats["rejected_canonical_total"])
        self.assertEqual(
            {
                "common_english_word": 1,
                "short_acronym_without_definition": 1,
                "generic_structural_term": 0,
            },
            payload["rejected_canonical_reasons"],
        )
        self.assertEqual(
            {("OF", "common_english_word"), ("XQ", "short_acronym_without_definition")},
            {
                (item["canonical"], item["reason"])
                for item in payload["rejected_canonicals"]
            },
        )
        self.assertEqual(
            [4],
            [
                item["document_frequency"]
                for item in payload["rejected_canonicals"]
                if item["canonical"] == "XQ"
            ],
        )
        # 类型分布只数留下来的两条，被判据丢掉的不该算进去。
        self.assertEqual({"METHOD": 1, "METRIC": 1}, payload["type_mapping"]["observed"])


class GenericStructuralTermTest(unittest.TestCase):
    """第四轮加的通用/结构性词判据：names 描述文档结构或泛泛类别，不指向具体技术。"""

    def _reason(
        self,
        canonical: str,
        *,
        defined: set[str] | None = None,
        document_frequency: int | None = None,
    ) -> str:
        return wordlist.canonical_rejection_reason(
            canonical,
            defined=defined if defined is not None else set(),
            document_frequency=document_frequency,
        )

    def test_generic_structural_terms_are_rejected(self) -> None:
        for canonical in ("ENTITY", "TASK", "CONTEXT", "CLAIM", "QUESTION", "OUTPUT"):
            self.assertEqual(
                "generic_structural_term", self._reason(canonical), f"{canonical} 该丢"
            )

    def test_variants_are_rejected_after_normalization(self) -> None:
        self.assertEqual("generic_structural_term", self._reason("entities"))
        self.assertEqual("generic_structural_term", self._reason("Entity"))
        self.assertEqual("generic_structural_term", self._reason("  results "))
        self.assertEqual("generic_structural_term", self._reason("RESULTS"))

    def test_entity_like_words_that_are_legal_types_are_kept(self) -> None:
        """model / method / dataset / annotation / metric 不在表里，不能误伤。"""
        for canonical in ("MODEL", "METHOD", "DATASET", "ANNOTATION", "METRIC"):
            self.assertEqual("", self._reason(canonical), f"{canonical} 该留")
        for canonical in ("language model", "method of moments", "ImageNet dataset"):
            self.assertEqual("", self._reason(canonical), f"{canonical} 该留")

    def test_generic_term_that_is_a_defined_acronym_is_kept(self) -> None:
        """通用词那一条也看 definitions_found：有定义的不算通用词。"""
        self.assertEqual("", self._reason("DATA", defined={"DATA"}))
        self.assertEqual("", self._reason("data", defined={"DATA"}))
        self.assertEqual("generic_structural_term", self._reason("DATA"))
        # AI 不在通用词表里（它是两句缩写，靠有定义/DF 那两条留），这里顺手钉住。
        self.assertNotIn("ai", wordlist.GENERIC_STRUCTURAL_TERMS)
        self.assertEqual(
            "short_acronym_without_definition", self._reason("AI")
        )
        self.assertEqual("", self._reason("AI", defined={"AI"}))

    def test_multi_word_names_are_not_judged_here(self) -> None:
        """这一条只管单 token：`case study figure` 要人签核，不归它管。"""
        self.assertEqual("", self._reason("case study figure"))
        for name in ("case study", "system design", "the results"):
            self.assertEqual("", self._reason(name), f"{name} 不该被这一条丢")
        # 整条名字是一个通用词 + 一个功能词时，也不归这一条（多 token）。
        self.assertEqual("", self._reason("entity of"))

    def test_the_term_table_is_plain_english_not_domain_terms(self) -> None:
        for word in ("entity", "task", "context", "claim", "information", "data"):
            self.assertIn(word, wordlist.GENERIC_STRUCTURAL_TERMS)
        for word in ("model", "method", "dataset", "annotation", "metric", "gnn", "cgcnn"):
            self.assertNotIn(word, wordlist.GENERIC_STRUCTURAL_TERMS)

    def test_generic_term_wins_over_the_short_acronym_rule(self) -> None:
        """``DATA``（4 位）本来不受短缩写那一条管，就记通用词这个原因。"""
        self.assertEqual("generic_structural_term", self._reason("DATA"))

    def test_short_acronym_rule_wins_over_the_generic_term_rule(self) -> None:
        """``ONE`` 两条都符合（3 位全大写、又在通用词表里），记前面那条。"""
        self.assertIn("ones", wordlist.GENERIC_STRUCTURAL_TERMS)
        self.assertEqual(
            "short_acronym_without_definition",
            self._reason("ONE", document_frequency=3),
        )
        self.assertEqual(
            "short_acronym_without_definition",
            self._reason("ONE", document_frequency=4),
        )
        # DF 到了门槛，短缩写那一条不再丢它，才轮到通用词这一条。
        self.assertEqual(
            "generic_structural_term", self._reason("ONES", document_frequency=5)
        )
        self.assertEqual(
            "generic_structural_term", self._reason("Results", document_frequency=9)
        )

    def test_rejections_are_written_into_the_payload_with_the_df(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            path.write_text(
                json.dumps(
                    {
                        "domain_id": "示例",
                        "candidates": [
                            {
                                "canonical": "ENTITY",
                                "document_frequency": 12,
                                "guess_type": "METHOD",
                                "surface_forms": ["ENTITY", "entity"],
                            },
                            {
                                "canonical": "RESULTS",
                                "document_frequency": 9,
                                "guess_type": "METHOD",
                                "surface_forms": ["RESULTS"],
                            },
                            {
                                "canonical": "AI",
                                "document_frequency": 18,
                                "guess_type": "METHOD",
                                "surface_forms": ["AI"],
                            },
                        ],
                        "definitions_found": {"AI": ["artificial intelligence"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload, _ = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=3, alias_cap=6
            )
        self.assertEqual(["AI"], [item["canonical"] for item in payload["concepts"]])
        self.assertEqual(2, payload["rejected_canonical_total"])
        self.assertEqual(
            {"common_english_word": 0, "short_acronym_without_definition": 0, "generic_structural_term": 2},
            payload["rejected_canonical_reasons"],
        )
        self.assertEqual(
            {("ENTITY", "generic_structural_term"), ("RESULTS", "generic_structural_term")},
            {
                (item["canonical"], item["reason"])
                for item in payload["rejected_canonicals"]
            },
        )
        self.assertEqual(
            [12, 9],
            [
                item["document_frequency"]
                for item in payload["rejected_canonicals"]
                if item["reason"] == "generic_structural_term"
            ],
        )
        self.assertIn(
            "generic_structural_term", payload["canonical_filters"]["reasons"]
        )
        self.assertEqual(
            sorted(wordlist.GENERIC_STRUCTURAL_TERMS),
            payload["canonical_filters"]["generic_structural_terms"],
        )
        # 别名这一层只报数不当场丢：ENTITY 那一条候选整条被丢，所以这里没有别名记录。
        self.assertEqual(0, payload["generic_alias_candidates"]["total"])

    def test_generic_aliases_are_counted_not_dropped(self) -> None:
        """判据落在 canonical 上：别名里的通用词只报数，行为与第三轮一致。"""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            path.write_text(
                json.dumps(
                    {
                        "domain_id": "示例",
                        "candidates": [
                            {
                                "canonical": "named entity recognition",
                                "document_frequency": 8,
                                "guess_type": "TASK",
                                "surface_forms": ["named entity recognition", "entity"],
                            }
                        ],
                        "definitions_found": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload, _ = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=3, alias_cap=6
            )
        self.assertEqual(["entity"], payload["concepts"][0]["aliases"])
        self.assertEqual(1, payload["generic_alias_candidates"]["total"])
        self.assertEqual(
            "entity", payload["generic_alias_candidates"]["items"][0]["alias"]
        )
        self.assertEqual(0, payload["rejected_alias_total"])


class ShortAcronymDocumentFrequencyTest(unittest.TestCase):
    """第四轮放宽：长度 ≤3 的全大写术语，跨 MIN_SHORT_ACRONYM_DF 篇论文就留下。"""

    def _reason(self, canonical: str, df: int, *, defined: set[str] | None = None) -> str:
        return wordlist.canonical_rejection_reason(
            canonical, defined=defined if defined is not None else set(), document_frequency=df
        )

    def test_threshold_is_five(self) -> None:
        self.assertEqual(5, wordlist.MIN_SHORT_ACRONYM_DF)

    def test_the_df_threshold_is_the_boundary(self) -> None:
        self.assertEqual("short_acronym_without_definition", self._reason("KG", 4))
        self.assertEqual("", self._reason("KG", 5))
        self.assertEqual("", self._reason("KG", 24))

    def test_function_words_are_not_rescued_by_a_high_df(self) -> None:
        """OF/IN/BY 排在功能词那一条，门槛再高也救不回来。"""
        for canonical in ("OF", "IN", "BY", "OR", "IT"):
            self.assertEqual("common_english_word", self._reason(canonical, 99))

    def test_a_definition_still_keeps_a_low_df_acronym(self) -> None:
        self.assertEqual("", self._reason("DKT", 3, defined={"DKT"}))
        self.assertEqual(
            "short_acronym_without_definition", self._reason("DKT", 3)
        )
        # 含数字的写法不受这一条影响（GPT-4 不是"全大写 2–3 位"那一类）。
        self.assertEqual("", self._reason("GPT-4", 2))

    def test_alias_side_uses_the_same_threshold(self) -> None:
        defined = wordlist.defined_acronyms({})
        kept, rejected = wordlist.filter_aliases(
            ["KG", "GCN", "XRD"], "knowledge graph", cap=6, defined=defined, document_frequency=5
        )
        self.assertEqual(["KG", "GCN", "XRD"], kept)
        self.assertEqual([], rejected)
        kept, rejected = wordlist.filter_aliases(
            ["KG", "GCN", "XRD"], "knowledge graph", cap=6, defined=defined, document_frequency=4
        )
        self.assertEqual([], kept)
        self.assertEqual(["KG", "GCN", "XRD"], rejected)

    def test_alias_rejection_reason_without_a_df_keeps_the_third_round_rule(self) -> None:
        """不传 document_frequency 时回到第三轮的判据（老调用点照原样跑）。"""
        self.assertEqual(
            "short_acronym_without_definition",
            wordlist.alias_rejection_reason("KG", defined=set()),
        )
        self.assertEqual(
            "", wordlist.alias_rejection_reason("KG", defined=set(), document_frequency=5)
        )

    def test_payload_keeps_a_cross_paper_acronym_and_records_why(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "示例_候选概念.json"
            path.write_text(
                json.dumps(
                    {
                        "domain_id": "示例",
                        "candidates": [
                            {
                                "canonical": "KG",
                                "document_frequency": 24,
                                "guess_type": "METHOD",
                                "surface_forms": ["KG"],
                            },
                            {
                                "canonical": "SNE",
                                "document_frequency": 3,
                                "guess_type": "METHOD",
                                "surface_forms": ["SNE"],
                            },
                        ],
                        "definitions_found": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload, _ = wordlist.build_payload(
                path, entity_types=ENTITY_TYPES, min_df=3, alias_cap=6
            )
        self.assertEqual(["KG"], [item["canonical"] for item in payload["concepts"]])
        kept = payload["kept_short_uppercase"]
        self.assertEqual(1, kept["canonical_count"])
        self.assertEqual(0, kept["canonical_by_definition"])
        self.assertEqual(1, kept["canonical_by_document_frequency"])
        self.assertEqual("document_frequency", kept["items"][0]["kept_by"])
        self.assertEqual(
            ["SNE"],
            [item["canonical"] for item in payload["rejected_canonicals"]],
        )
        self.assertEqual("KG", payload["concepts"][0]["canonical"])
        self.assertEqual(5, payload["canonical_filters"]["min_short_acronym_df"])


class PerDomainVocabularyTest(unittest.TestCase):
    """建库脚本的 --vocabulary-per-domain：按领域找各自那份词表。"""

    build = load_script("构建全文知识库", "scripts/抽取/构建全文知识库.py")

    def test_path_template_matches_the_generator_output(self) -> None:
        path = self.build.domain_vocabulary_path("scientific-ie-kg")
        self.assertEqual(
            "data/knowledge/domain_vocabulary/scientific-ie-kg_抽取词表_DF3.json",
            str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        )

    def test_existing_and_missing_domains_are_separated(self) -> None:
        present, missing = self.build.per_domain_vocabulary_paths(
            ["scientific-ie-kg", "没有这个领域"]
        )
        self.assertIn("scientific-ie-kg", present)
        self.assertIn("没有这个领域", missing)
        self.assertIn("该领域没有词表", missing["没有这个领域"])

    def test_each_domain_gets_its_own_concepts(self) -> None:
        schema = json.loads(
            (PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json").read_text(
                encoding="utf-8"
            )
        )
        base = len(schema["concepts"])
        extractors, stats = self.build.build_per_domain_extractors(
            schema, ["scientific-ie-kg", "没有词表这个领域"]
        )
        self.assertEqual("per-domain", stats["mode"])
        # 有词表的那个领域：概念数 = 本体 + 它自己那份；没有的那个：只剩本体。
        self.assertGreater(stats["domains"]["scientific-ie-kg"]["concepts"], 0)
        self.assertEqual(
            0, stats["domains"]["没有词表这个领域"]["concepts"]
        )
        self.assertIn("该领域没有词表", stats["domains"]["没有词表这个领域"]["reason"])
        self.assertGreater(len(extractors["scientific-ie-kg"].alias_entries), base)
        # 没词表的那个领域：别名条目数与只用本体的抽取器一模一样（550 是本体的实测值）。
        self.assertEqual(
            len(extractors["没有词表这个领域"].alias_entries),
            sum(
                len({item["canonical"], *item["aliases"]})
                for item in schema["concepts"]
            ),
        )

    def test_relation_pairing_is_forwarded(self) -> None:
        schema = json.loads(
            (PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json").read_text(
                encoding="utf-8"
            )
        )
        extractors, _ = self.build.build_per_domain_extractors(
            schema,
            ["scientific-ie-kg"],
            relation_pairing="trigger_between",
        )
        self.assertEqual(
            "trigger_between", extractors["scientific-ie-kg"].relation_pairing
        )

    def test_vocabulary_bad_type_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            self.build.check_vocabulary_payload(
                {"concepts": [{"canonical": "x", "entity_type": "OTHER", "aliases": []}]},
                "示例词表.json",
            )

    def test_manifest_root_finds_the_same_layout(self) -> None:
        """--manifest-root 按同一套布局找清单：根下是主领域，domains/<领域>/ 是其余。"""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "manifest.json").write_text("{}", encoding="utf-8")
            domain_dir = root / "domains" / "示例领域"
            domain_dir.mkdir(parents=True)
            (domain_dir / "manifest.json").write_text("{}", encoding="utf-8")
            manifests = self.build.domain_manifests(root)
            self.assertEqual(2, len(manifests))
            self.assertEqual(
                ["scientific-ie-kg", "示例领域"],
                [
                    self.build.domain_id_of(path, manifest_root=root)
                    for path in manifests
                ],
            )

    def test_default_manifest_root_is_the_repository_one(self) -> None:
        root = self.build.resolve_manifest_root("")
        self.assertEqual(
            "data/vertical_kb", str(root.relative_to(PROJECT_ROOT)).replace("\\", "/")
        )
        manifests = self.build.domain_manifests(root)
        self.assertEqual(
            ["scientific-ie-kg"],
            [self.build.domain_id_of(path) for path in manifests[:1]],
        )
        self.assertEqual(5, len(manifests))


class DensityArmsTest(unittest.TestCase):
    """三个臂一起比：每个臂各自一块，第一轮那种两参数调用法照样能用。"""

    def _report(self, domain_id: str, entities: int, relations: int, *, digest: str = "") -> dict:
        domain = {
            "domain_id": domain_id,
            "domain_name": "示例",
            "papers": 10,
            "sections": 20,
            "evidence_spans": 30,
            "entities": entities,
            "relations": relations,
            "relations_by_status": {"accepted": 1},
        }
        if digest:
            domain["manifest_sha256"] = digest
        return {
            "schema_version": "0.1.0",
            "arguments": {},
            "extractor": {},
            "domains": [domain],
        }

    def _write(self, directory: Path, name: str, payload: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_three_arms_each_get_a_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            baseline = self._write(directory, "基线.json", self._report("示例", 5, 4))
            arm_b = self._write(directory, "臂B.json", self._report("示例", 15, 12))
            arm_c = self._write(directory, "臂C.json", self._report("示例", 14, 8))
            result = density.build_result(baseline, [arm_b, arm_c])
        self.assertEqual(2, len(result["arms"]))
        block = result["domains"][0]
        self.assertEqual(["臂 B", "臂 C"], [item["arm"] for item in block["arms"]])
        self.assertEqual(
            [15, 14],
            [item["metrics"]["entities"]["treatment"] for item in block["arms"]],
        )
        # 第一轮那个 treatment 键照旧指第一个臂。
        self.assertEqual(15, block["metrics"]["entities"]["treatment"])
        self.assertEqual(2, len(result["totals"]["arms"]))

    def test_a_single_path_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            baseline = self._write(directory, "基线.json", self._report("示例", 5, 4))
            arm_b = self._write(directory, "臂B.json", self._report("示例", 15, 12))
            result = density.build_result(baseline, arm_b)
        self.assertEqual(1, len(result["arms"]))
        self.assertEqual(1, len(result["domains"][0]["arms"]))

    def test_treatment_paths_are_flattened(self) -> None:
        paths = density.parse_treatments(["outputs/a.json,outputs/b.json", "outputs/c.json"])
        self.assertEqual(3, len(paths))
        self.assertEqual("c.json", paths[-1].name)

    def test_arm_mismatch_is_refused_for_every_arm(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            baseline = self._write(directory, "基线.json", self._report("甲", 5, 4))
            good = self._write(directory, "好.json", self._report("甲", 15, 12))
            bad = self._write(directory, "坏.json", self._report("乙", 15, 12))
            with self.assertRaises(SystemExit):
                density.build_result(baseline, [good, bad])

    def test_strict_frozen_refuses_a_changed_manifest(self) -> None:
        """清单 sha256 对不上时报错：语料在跑的当中被改过，这样的对照不能当准数。"""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            baseline = self._write(
                directory, "基线.json", self._report("甲", 5, 4, digest="a" * 64)
            )
            same = self._write(
                directory, "同.json", self._report("甲", 15, 12, digest="a" * 64)
            )
            changed = self._write(
                directory, "变.json", self._report("甲", 15, 12, digest="b" * 64)
            )
            # 不加开关时照旧出结果（只是数字对不上时看不出来）。
            density.build_result(baseline, same, strict_frozen=True)
            with self.assertRaises(SystemExit):
                density.build_result(baseline, changed, strict_frozen=True)

    def test_strict_frozen_allows_reports_without_the_digest(self) -> None:
        """没有 sha256 的老报告不该被 --strict-frozen 拦下（第一轮的报告就没有）。"""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            baseline = self._write(directory, "基线.json", self._report("甲", 5, 4))
            arm = self._write(directory, "臂.json", self._report("甲", 15, 12))
            result = density.build_result(baseline, arm, strict_frozen=True)
        self.assertEqual(1, len(result["arms"]))


class DensityMathTest(unittest.TestCase):
    def test_per_paper_returns_none_without_papers(self) -> None:
        self.assertIsNone(density.per_paper(10, 0))
        self.assertEqual(0.5, density.per_paper(5, 10))

    def test_change_reports_delta_when_baseline_is_zero(self) -> None:
        result = density.compare(0.0, 0.5)
        self.assertEqual(0.5, result["delta"])
        self.assertIsNone(result["ratio"])
        self.assertIn("基线为 0", result["ratio_text"])

    def test_change_without_a_comparable_side(self) -> None:
        result = density.compare(1.0, None)
        self.assertIsNone(result["delta"])
        self.assertIn("无可比", result["ratio_text"])

    def test_domain_block_and_totals_use_the_input_numbers(self) -> None:
        baseline = {
            "domain_name": "示例领域",
            "papers": 10,
            "sections": 20,
            "evidence_spans": 30,
            "entities": 5,
            "relations": 4,
            "accepted_relations": 2,
        }
        treatment = {
            "domain_name": "示例领域",
            "papers": 10,
            "sections": 20,
            "evidence_spans": 60,
            "entities": 15,
            "relations": 12,
            "accepted_relations": 9,
        }
        block = density.domain_block("示例", baseline, treatment)
        self.assertEqual(0.5, block["density"]["entities_per_paper"]["baseline"])
        self.assertEqual(1.5, block["density"]["entities_per_paper"]["treatment"])
        self.assertEqual(1.0, block["density"]["entities_per_paper"]["delta"])
        self.assertEqual("+200.0%", block["density"]["entities_per_paper"]["ratio_text"])
        totals = density.totals_block([block])
        self.assertEqual(60, totals["metrics"]["evidence_spans"]["treatment"])
        self.assertEqual(30, totals["metrics"]["evidence_spans"]["baseline"])
        self.assertEqual(2, totals["metrics"]["accepted_relations"]["baseline"])
        self.assertEqual(9, totals["metrics"]["accepted_relations"]["treatment"])

    def test_report_and_database_read_the_same_counts(self) -> None:
        """报告那条路与查库那条路必须给出同一组数。"""
        from yanhai.store import KnowledgeGraphStore

        payload = {
            "papers": [
                {"paper_id": "p1", "title": "标题", "source_url": "https://example.invalid"}
            ],
            "sections": [
                {
                    "paper_id": "p1",
                    "section_id": "title",
                    "parser": "plain-text",
                    "char_count": 2,
                    "text_sha256": "0" * 64,
                }
            ],
            "evidence": [
                {
                    "evidence_id": "evidence:p1:title:0",
                    "paper_id": "p1",
                    "section_id": "title",
                    "sentence_index": 0,
                    "text": "标题",
                    "char_start": 0,
                    "char_end": 2,
                }
            ],
            "entities": [
                {
                    "entity_id": "entity:1",
                    "canonical_name": "知识图谱",
                    "entity_type": "DOMAIN",
                    "aliases": [],
                    "mentions": [],
                    "confidence": 0.8,
                }
            ],
            "relations": [
                {
                    "relation_id": "relation:1",
                    "source_id": "entity:1",
                    "target_id": "entity:1",
                    "relation_type": "RELATED_TO",
                    "evidence_ids": ["evidence:p1:title:0"],
                    "confidence": 0.5,
                    "status": "accepted",
                    "criticisms": [],
                    "extraction_method": "schema-guided-pattern",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as raw:
            db_path = Path(raw) / "示例.db"
            KnowledgeGraphStore(db_path).rebuild(payload)
            counted = density.db_counts(db_path)
        self.assertEqual(
            {
                "papers": 1,
                "sections": 1,
                "evidence_spans": 1,
                "entities": 1,
                "relations": 1,
                "accepted_relations": 1,
            },
            counted,
        )

    def test_domain_mismatch_is_refused(self) -> None:
        def report(domain_id: str) -> dict:
            return {
                "domains": [
                    {
                        "domain_id": domain_id,
                        "papers": 1,
                        "sections": 1,
                        "evidence_spans": 1,
                        "entities": 1,
                        "relations": 1,
                        "relations_by_status": {"accepted": 1},
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as raw:
            paths = []
            for index, domain_id in enumerate(("甲", "乙")):
                path = Path(raw) / f"报告{index}.json"
                path.write_text(
                    json.dumps(report(domain_id), ensure_ascii=False), encoding="utf-8"
                )
                paths.append(path)
            with self.assertRaises(SystemExit):
                density.build_result(paths[0], paths[1])


class FaithfulnessTest(unittest.TestCase):
    def _library(self, section_text: str, stored_text: str, start: int, end: int) -> tuple:
        graph = {
            "papers": [{"paper_id": "p1", "title": "标题", "source_url": ""}],
            "entities": [
                {"entity_id": "e1", "canonical_name": "甲", "entity_type": "METHOD"},
                {"entity_id": "e2", "canonical_name": "乙", "entity_type": "TASK"},
            ],
            "evidence": [
                {
                    "evidence_id": "evidence:p1:page-001:0",
                    "paper_id": "p1",
                    "section_id": "page-001",
                    "sentence_index": 0,
                    "text": stored_text,
                    "char_start": start,
                    "char_end": end,
                }
            ],
            "relations": [
                {
                    "relation_id": "relation:1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "relation_type": "USES",
                    "evidence_ids": ["evidence:p1:page-001:0"],
                    "confidence": 0.78,
                    "status": "accepted",
                }
            ],
        }
        cache = {
            "p1": {
                "paper": {"paper_id": "p1", "title": "标题", "source_url": ""},
                "sections": {"page-001": section_text},
            }
        }
        return graph, cache

    def test_offsets_slice_back_to_the_stored_text(self) -> None:
        section = "甲 用 乙 做实验。"
        graph, cache = self._library(section, "乙 做实验", 4, 9)
        report = faithfulness.build_rows(graph, cache, seed=1, count=1)
        self.assertTrue(report["primary_checks"][0]["_primary_matched"])
        self.assertEqual([], report["failures"])
        self.assertEqual(1, report["sampled_count"])
        self.assertEqual("甲", report["primary_checks"][0]["头实体"])
        self.assertEqual("乙", report["primary_checks"][0]["尾实体"])

    def test_a_wrong_offset_is_reported_not_swallowed(self) -> None:
        section = "甲 用 乙 做实验。"
        graph, cache = self._library(section, "甲 用 乙 做实验", 1, 5)
        report = faithfulness.build_rows(graph, cache, seed=1, count=1)
        self.assertFalse(report["primary_checks"][0]["_primary_matched"])
        self.assertEqual(1, len(report["failures"]))
        self.assertIn("不一致", report["failures"][0]["reason"])

    def test_out_of_range_offset_is_reported(self) -> None:
        section = "甲 用 乙 做实验。"
        graph, cache = self._library(section, "甲 用 乙 做实验", 1, 999)
        report = faithfulness.build_rows(graph, cache, seed=1, count=1)
        self.assertIn("越界", report["failures"][0]["reason"])

    def test_title_section_is_checked_against_the_cached_title(self) -> None:
        graph, cache = self._library("正文", "标题", 0, 2)
        graph["evidence"][0]["section_id"] = "title"
        report = faithfulness.build_rows(graph, cache, seed=1, count=1)
        self.assertTrue(report["primary_checks"][0]["_primary_matched"])

    def test_sampling_is_reproducible_for_a_fixed_seed(self) -> None:
        graph, _ = self._library("甲 用 乙 做实验。", "乙 做实验", 4, 9)
        graph["relations"] = [
            {**graph["relations"][0], "relation_id": f"relation:{index}"}
            for index in range(10)
        ]
        first = faithfulness.sample_relations(graph["relations"], seed=7, count=4)
        second = faithfulness.sample_relations(graph["relations"], seed=7, count=4)
        self.assertEqual(
            [item["relation_id"] for item in first],
            [item["relation_id"] for item in second],
        )
        self.assertEqual(4, len(first))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
