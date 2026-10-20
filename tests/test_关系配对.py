"""关系配对收紧（``relation_pairing``）的单测。

只测 ``src/yanhai/extraction.py`` 里 ``SchemaGuidedExtractor`` 这一条开关：

- ``legacy``（默认）：同一段里的实体两两组合，没命中触发词就兜底成 ``RELATED_TO``。
  这是从前的行为，**默认值必须是它**，所以这里也钉一条测试，谁把默认值改了都会挂。
- ``trigger_between``：① 没命中触发词就不生成关系；② 命中的触发词必须落在
  两个实体之间、或者紧邻其中一个（窗口 40 个字符），否则这一对不生成关系。

用一份缩小的 schema（不走 ``data/knowledge/extraction_schema.json``），这样每段文本里
有几个实体、触发词在哪个位置都是写死的，关系数的差别能一条条对上。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import (  # noqa: E402
    PlainTextParser,
    SchemaGuidedExtractor,
)


def mini_schema() -> dict:
    """一份最小的抽取本体：两个概念、一个带触发词的关系、两个没触发词的关系。

    ``RELATED_TO`` 故意不给触发词——它就是 legacy 模式的兜底类型，没有触发词时才会
    出现；``trigger_between`` 模式下的第一条规则（没触发词就不生成关系）把它整个去掉。
    """
    return {
        "version": "test-mini",
        "entity_types": {"METHOD": {}, "DATASET": {}},
        "relation_types": ["USES", "BENCHMARKS", "RELATED_TO"],
        "concepts": [
            {
                "canonical": "Alpha",
                "entity_type": "METHOD",
                "aliases": ["Alpha"],
            },
            {
                "canonical": "Beta",
                "entity_type": "DATASET",
                "aliases": ["Beta"],
            },
        ],
        "relation_constraints": {"USES": {"source": ["METHOD"], "target": ["DATASET"]}},
        "relation_patterns": [
            {"relation_type": "USES", "triggers": ["uses"]},
            {"relation_type": "BENCHMARKS", "triggers": ["benchmarks"]},
        ],
    }


def extract(text: str, *, relation_pairing: str) -> dict:
    """跑一段正文，返回抽取结果的字典。"""
    extractor = SchemaGuidedExtractor(mini_schema(), relation_pairing=relation_pairing)
    document = PlainTextParser().parse_text(
        text, paper_id="t", fallback_title="t"
    )
    return extractor.extract_documents([document]).to_dict()


def relation_types(payload: dict) -> list[str]:
    return [item["relation_type"] for item in payload["relations"]]


class DefaultPairingTest(unittest.TestCase):
    def test_default_is_legacy(self) -> None:
        """默认值必须是 legacy：不传这个参数时行为与从前一致。"""
        extractor = SchemaGuidedExtractor(mini_schema())
        self.assertEqual("legacy", extractor.relation_pairing)

    def test_unknown_mode_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SchemaGuidedExtractor(mini_schema(), relation_pairing="whatever")

    def test_from_path_accepts_the_new_switch(self) -> None:
        extractor = SchemaGuidedExtractor.from_path(
            PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json",
            relation_pairing="trigger_between",
        )
        self.assertEqual("trigger_between", extractor.relation_pairing)
        self.assertEqual(
            "legacy",
            SchemaGuidedExtractor.from_path(
                PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
            ).relation_pairing,
        )


class TriggerBetweenTest(unittest.TestCase):
    def test_no_trigger_means_no_relation(self) -> None:
        """规则①：没有触发词时 legacy 会兜底成 RELATED_TO，trigger_between 一条都不生成。"""
        text = "Alpha and Beta appear together."
        legacy = extract(text, relation_pairing="legacy")
        strict = extract(text, relation_pairing="trigger_between")
        self.assertEqual(["RELATED_TO"], relation_types(legacy))
        self.assertEqual([], strict["relations"])

    def test_trigger_inside_the_pair_is_kept(self) -> None:
        """规则②命中：触发词正好落在两个实体中间，两种模式都生成 USES。"""
        text = "Alpha uses Beta."
        legacy = extract(text, relation_pairing="legacy")
        strict = extract(text, relation_pairing="trigger_between")
        self.assertEqual(["USES"], relation_types(legacy))
        self.assertEqual(["USES"], relation_types(strict))
        self.assertEqual(1, len(strict["relations"]))
        relation = strict["relations"][0]
        # 方向按 relation_constraints 摆正：METHOD 在头、DATASET 在尾。
        names = {
            item["entity_id"]: item["canonical_name"] for item in strict["entities"]
        }
        self.assertEqual("Alpha", names[relation["source_id"]])
        self.assertEqual("Beta", names[relation["target_id"]])

    def test_trigger_adjacent_to_one_entity_is_kept(self) -> None:
        """规则②另一头：触发词紧邻尾实体（在它右边），也算。"""
        text = "Alpha and Beta uses."
        strict = extract(text, relation_pairing="trigger_between")
        self.assertEqual(["USES"], relation_types(strict))

    def test_trigger_far_away_drops_the_pair(self) -> None:
        """规则②漏掉的一半：触发词离两个实体都远，这一对丢掉。"""
        gap = "x" * 80
        text = f"Alpha and Beta {gap} uses."
        legacy = extract(text, relation_pairing="legacy")
        strict = extract(text, relation_pairing="trigger_between")
        self.assertEqual(["USES"], relation_types(legacy))
        self.assertEqual([], strict["relations"])

    def test_trigger_belongs_to_another_entity_pair(self) -> None:
        """一句话里有两对实体：触发词只挨着其中一对，另一对不该跟着生成关系。

        本来是两个概念，这里复制成四个写法（Alpha/Beta 与 Gamma/Delta——用同一份 mini
        schema 的别名字面），触发词 ``benchmarks`` 只紧挨后一对。legacy 会把三对
        全都配出来，trigger_between 只留挨着触发词的那一对。
        """
        schema = mini_schema()
        schema["concepts"] = [
            {"canonical": "Alpha", "entity_type": "METHOD", "aliases": ["Alpha"]},
            {"canonical": "Beta", "entity_type": "DATASET", "aliases": ["Beta"]},
            {"canonical": "Gamma", "entity_type": "METHOD", "aliases": ["Gamma"]},
            {"canonical": "Delta", "entity_type": "DATASET", "aliases": ["Delta"]},
        ]
        schema["relation_patterns"] = [
            {"relation_type": "BENCHMARKS", "triggers": ["benchmarks"]}
        ]

        def run(mode: str) -> list[str]:
            extractor = SchemaGuidedExtractor(schema, relation_pairing=mode)
            document = PlainTextParser().parse_text(
                "Alpha and Beta are separate. Gamma benchmarks Delta.",
                paper_id="t",
                fallback_title="t",
            )
            payload = extractor.extract_documents([document]).to_dict()
            names = {
                item["entity_id"]: item["canonical_name"] for item in payload["entities"]
            }
            return sorted(
                f"{names[item['source_id']]}-{names[item['target_id']]}"
                for item in payload["relations"]
            )

        # 第一句没有触发词、第二句有：legacy 的兜底会把第一句那一对也配上。
        # 关系方向：BENCHMARKS 没在 mini schema 的 relation_constraints 里，_orient_pair
        # 直接按实体的出现顺序摆，所以是 Gamma-Delta。
        self.assertEqual(["Alpha-Beta", "Gamma-Delta"], run("legacy"))
        self.assertEqual(["Gamma-Delta"], run("trigger_between"))

    def test_confidence_of_a_kept_relation_is_the_trigger_value(self) -> None:
        """留得下来的关系都是"命中触发词"那一档（0.78），不是没触发词的 0.62。"""
        strict = extract("Alpha uses Beta.", relation_pairing="trigger_between")
        self.assertEqual(0.78, strict["relations"][0]["confidence"])

    def test_runs_against_the_real_schema(self) -> None:
        """真实本体上跑一段中文正文：两种模式都能跑通，且 strict 不会比 legacy 多。"""
        schema_path = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
        text = "知识图谱 使用 关系抽取。"
        counts = {}
        for mode in ("legacy", "trigger_between"):
            extractor = SchemaGuidedExtractor.from_path(schema_path, relation_pairing=mode)
            document = PlainTextParser().parse_text(text, paper_id="t", fallback_title="t")
            counts[mode] = len(extractor.extract_documents([document]).to_dict()["relations"])
        self.assertLessEqual(counts["trigger_between"], counts["legacy"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
