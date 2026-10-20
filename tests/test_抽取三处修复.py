"""三处抽取质量修复的开关单测。

三处修复各有一个开关，**默认全关**，不传时与从前逐字一致：

- ``word_boundary="ascii"|"unicode"``：别名词边界。``ascii``（默认）是从前的
  ``(?<![A-Za-z0-9])…(?![A-Za-z0-9])``，PDF 合字 ``ﬁ`` / ``ﬂ`` 与法语重音字母不算
  字的一部分，于是 ``RE`` 命中 ``reﬁning``、``NED`` 命中 ``deﬁned``；``unicode``
  把这些字母也算进边界，词内匹配不再出现。
- ``direction_check=False``：确定性批判者里的方向检查。触发词命中的是前向动词、
  而尾实体在触发词之前、头实体在之后时，往 ``criticisms`` 里写 ``direction_suspect``
  与三处位置，关系降级到 ``needs_review``。
- ``reports_triggers="schema"|"extended"``：``REPORTS`` 的触发词表用本体里那几条
  （默认），还是把 ``extraction.py`` 的 ``REPORTS_TRIGGER_EXTRA`` 也并进来。
  ``data/knowledge/extraction_schema.json`` 一个字节都不改。

跑法：``.venv\\Scripts\\python.exe -m unittest tests.test_抽取三处修复 -v``
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import (  # noqa: E402
    REPORTS_TRIGGER_EXTRA,
    WORD_BOUNDARY_MODES,
    PlainTextParser,
    SchemaGuidedExtractor,
)

SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"


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


build_fulltext = load_script("构建全文知识库", "scripts/抽取/构建全文知识库.py")


def mini_schema() -> dict:
    """最小本体：两个概念（METHOD / DATASET）、USES 与 REPORTS 两种关系。"""
    return {
        "version": "test-mini",
        "entity_types": {"METHOD": {}, "DATASET": {}},
        "relation_types": ["USES", "REPORTS", "RELATED_TO"],
        "concepts": [
            {"canonical": "Alpha", "entity_type": "METHOD", "aliases": ["Alpha"]},
            {"canonical": "Beta", "entity_type": "DATASET", "aliases": ["Beta"]},
            {"canonical": "RE", "entity_type": "METHOD", "aliases": ["RE"]},
        ],
        "relation_constraints": {"USES": {"source": ["METHOD"], "target": ["DATASET"]}},
        "relation_patterns": [
            {"relation_type": "USES", "triggers": ["uses"]},
            {"relation_type": "REPORTS", "triggers": ["report", "reports"]},
        ],
    }


def extract(text: str, **kwargs) -> dict:
    extractor = SchemaGuidedExtractor(mini_schema(), **kwargs)
    document = PlainTextParser().parse_text(text, paper_id="t", fallback_title="t")
    return extractor.extract_documents([document]).to_dict()


def relation_types(payload: dict) -> list[str]:
    return [item["relation_type"] for item in payload["relations"]]


def mentions_of(payload: dict, canonical_name: str) -> list[tuple[int, int]]:
    for entity in payload["entities"]:
        if entity["canonical_name"] == canonical_name:
            return [(item["char_start"], item["char_end"]) for item in entity["mentions"]]
    return []


class DefaultsStayOffTest(unittest.TestCase):
    """三个开关的默认值必须都是"关"：谁把默认值改了都会挂在这里。"""

    def test_defaults_are_ascii_off_schema(self) -> None:
        extractor = SchemaGuidedExtractor.from_path(SCHEMA_PATH)
        self.assertEqual("ascii", extractor.word_boundary)
        self.assertFalse(extractor.direction_check)
        self.assertEqual("schema", extractor.reports_triggers)

    def test_default_alias_pattern_is_the_old_one(self) -> None:
        """默认口径下 pattern 与从前的拼法逐字一致。"""
        self.assertEqual(
            r"(?<![A-Za-z0-9])RE(?![A-Za-z0-9])",
            SchemaGuidedExtractor._alias_pattern("RE").pattern,
        )

    def test_default_trigger_table_is_exactly_the_schema(self) -> None:
        """不开扩展时，编译出来的触发词条数就等于本体里写的条数。"""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        expected = sum(
            len(pattern["triggers"]) for pattern in schema["relation_patterns"]
        )
        extractor = SchemaGuidedExtractor(schema)
        self.assertEqual(expected, len(extractor.compiled_triggers))

    def test_extended_adds_exactly_the_extra_table(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        base = sum(len(pattern["triggers"]) for pattern in schema["relation_patterns"])
        extractor = SchemaGuidedExtractor(
            schema,
            reports_triggers="extended",
        )
        self.assertEqual(base + len(REPORTS_TRIGGER_EXTRA), len(extractor.compiled_triggers))

    def test_unknown_modes_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            SchemaGuidedExtractor(mini_schema(), word_boundary="other")
        with self.assertRaises(ValueError):
            SchemaGuidedExtractor(mini_schema(), reports_triggers="other")
        self.assertEqual(("ascii", "unicode"), WORD_BOUNDARY_MODES)


class WordBoundaryTest(unittest.TestCase):
    """缺陷一：ASCII 词边界把 PDF 合字与重音字母当成词外的分隔符。"""

    LIGATURE_TEXT = "Our system works by reﬁning the encoder, as Rozière and manière note."

    def test_ascii_boundary_hits_inside_words(self) -> None:
        """默认口径：reﬁning / Rozière / manière 里的 re 都被算成 RE 的提及。"""
        payload = extract(self.LIGATURE_TEXT)
        self.assertEqual(3, len(mentions_of(payload, "RE")))

    def test_unicode_boundary_drops_all_three(self) -> None:
        payload = extract(self.LIGATURE_TEXT, word_boundary="unicode")
        self.assertEqual([], mentions_of(payload, "RE"))

    def test_unicode_boundary_keeps_standalone_aliases(self) -> None:
        """该匹配的不能漏掉：独立成词的 RE 两种口径都照样命中。"""
        text = "RE is a system. Also RE works."
        ascii_payload = extract(text)
        unicode_payload = extract(text, word_boundary="unicode")
        self.assertEqual([(0, 2), (5, 7)], mentions_of(ascii_payload, "RE"))
        self.assertEqual([(0, 2), (5, 7)], mentions_of(unicode_payload, "RE"))

    def test_unicode_boundary_still_blocks_ascii_neighbours(self) -> None:
        """ASCII 字母挨着的时候，两种口径都挡住（不是"越改越松"）。"""
        text = "The REsearch and PRE and AREN are not RE."
        for mode in WORD_BOUNDARY_MODES:
            payload = extract(text, word_boundary=mode)
            self.assertEqual(
                [(len(text) - 3, len(text) - 1)],
                mentions_of(payload, "RE"),
                msg=mode,
            )


class DirectionCheckTest(unittest.TestCase):
    """缺陷二：方向写反的关系只降级到待复核，不丢。"""

    REVERSED = "Beta uses Alpha."
    NORMAL = "Alpha uses Beta."

    def test_default_off_accepts_the_reversed_relation(self) -> None:
        """默认关：这条关系照旧接收，批判里一条都不提方向。"""
        payload = extract(self.REVERSED)
        self.assertEqual(["USES"], relation_types(payload))
        relation = payload["relations"][0]
        self.assertEqual("accepted", relation["status"])
        self.assertEqual([], relation["criticisms"])

    def test_switch_flags_it_and_downgrades(self) -> None:
        payload = extract(self.REVERSED, direction_check=True)
        self.assertEqual(1, len(payload["relations"]), msg="只降级，不许丢")
        relation = payload["relations"][0]
        self.assertEqual("needs_review", relation["status"])
        self.assertEqual(1, len(relation["criticisms"]))
        criticism = relation["criticisms"][0]
        self.assertTrue(criticism.startswith("direction_suspect:"))
        # 依据里要举出触发词与两个实体各自的位置：Beta[0,4) uses[5,9) Alpha[10,15)。
        self.assertIn("「uses」", criticism)
        self.assertIn("[5,9)", criticism)
        self.assertIn("「Beta」", criticism)
        self.assertIn("[0,4)", criticism)
        self.assertIn("「Alpha」", criticism)
        self.assertIn("[10,15)", criticism)

    def test_correct_order_is_not_flagged(self) -> None:
        payload = extract(self.NORMAL, direction_check=True)
        relation = payload["relations"][0]
        self.assertEqual("accepted", relation["status"])
        self.assertEqual([], relation["criticisms"])

    def test_non_forward_trigger_is_not_flagged(self) -> None:
        """触发词不在前向动词名单里（BENCHMARKS）时不判方向。"""
        schema = mini_schema()
        schema["relation_patterns"] = [
            {"relation_type": "BENCHMARKS", "triggers": ["benchmarks"]},
        ]
        schema["relation_constraints"] = {}
        extractor = SchemaGuidedExtractor(schema, direction_check=True)
        document = PlainTextParser().parse_text(
            "Beta benchmarks Alpha.", paper_id="t", fallback_title="t"
        )
        payload = extractor.extract_documents([document]).to_dict()
        relation = payload["relations"][0]
        self.assertFalse(
            any("direction_suspect" in item for item in relation["criticisms"])
        )


class ReportsTriggersTest(unittest.TestCase):
    """缺陷三：报数值的说法应当算 REPORTS，不再兜底成 RELATED_TO。"""

    NUMBER_TEXT = "Alpha achieves 95.4% F1 on Beta."

    def test_schema_mode_falls_back_to_related_to(self) -> None:
        payload = extract(self.NUMBER_TEXT)
        self.assertEqual(["RELATED_TO"], relation_types(payload))

    def test_extended_mode_reads_it_as_reports(self) -> None:
        payload = extract(self.NUMBER_TEXT, reports_triggers="extended")
        self.assertEqual(["REPORTS"], relation_types(payload))
        self.assertEqual("accepted", payload["relations"][0]["status"])

    def test_extended_mode_keeps_the_schema_triggers(self) -> None:
        """本体里原有的 report / reports 不能因为扩展而失效。"""
        for mode in ("schema", "extended"):
            payload = extract("Alpha reports 95.4% F1 on Beta.", reports_triggers=mode)
            self.assertEqual(["REPORTS"], relation_types(payload), msg=mode)

    def test_chinese_report_forms_are_covered(self) -> None:
        payload = extract(
            "模型 Alpha 报告 92.3% 的准确率，Beta 到此为止。",
            reports_triggers="extended",
        )
        self.assertEqual(["REPORTS"], relation_types(payload))

    def test_every_extra_trigger_matches_its_sample(self) -> None:
        """扩展表里的每一条都能命中一个它该命中的写法，而且条数对得上。"""
        self.assertEqual(15, len(REPORTS_TRIGGER_EXTRA))
        samples = [
            "reports 95.4%",
            "achieves 95.4%",
            "obtained 3.2 points",
            "reaches 90.0",
            "gains 2.1",
            "attains 88.0",
            "outperforms all baselines",
            "improves 4.2%",
            "shows that the model",
            "报告 92.3%",
            "达到 92.3%",
            "取得 3 个点",
            "提升到 95.0%",
            "降至 12.0%",
            "测得 88.6%",
        ]
        self.assertEqual(len(REPORTS_TRIGGER_EXTRA), len(samples))
        for source, sample in zip(REPORTS_TRIGGER_EXTRA, samples):
            pattern = SchemaGuidedExtractor._extra_trigger_pattern(source)
            self.assertIsNotNone(pattern.search(sample), msg=f"{source} 没命中 {sample}")

    def test_improv_trigger_needs_a_number(self) -> None:
        """``improv(e|es|ed) 后接数值`` 才命中：只说"改进模型"不算报数。"""
        pattern = SchemaGuidedExtractor._extra_trigger_pattern(
            r"improv(e|es|ed)\s+(?:by\s+)?\d+(?:\.\d+)?\s*%?"
        )
        self.assertIsNotNone(pattern.search("improved by 3.5 points"))
        self.assertIsNone(pattern.search("improves the language model"))

    def test_schema_file_is_not_touched(self) -> None:
        """本体的 REPORTS 触发词还是原来那几条，扩展只活在代码里。"""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        reports = next(
            pattern
            for pattern in schema["relation_patterns"]
            if pattern["relation_type"] == "REPORTS"
        )
        self.assertEqual(
            ["report", "reports", "show", "shows", "表明", "发现", "结果显示"],
            reports["triggers"],
        )


class DecisionScriptSwitchesTest(unittest.TestCase):
    """决策脚本那条路上的两处改动：真原文评测集能加载了、触发词扩展只在内存里。

    这两条不是抽取器的开关，但都是这一轮为了让 Track A 跑得起来才改的，一起钉住。
    """

    CASES = PROJECT_ROOT / "data" / "evaluation" / "decision_benchmark_real_v2.json"

    def setUp(self) -> None:
        self.script = load_script("run_decision_experiment", "scripts/run_decision_experiment.py")

    def test_real_paper_set_loads_without_base_confidence(self) -> None:
        """真原文评测集的案例没有 base_confidence（置信度由机制算），不应当被拦下。"""
        payload = self.script.load_benchmark(str(self.CASES))
        self.assertEqual(97, len(payload["cases"]))
        self.assertNotIn("base_confidence", payload["cases"][0])

    def test_old_benchmark_still_requires_base_confidence(self) -> None:
        """24 条旧基准没有 evidence_text，缺 base_confidence 仍然要报错。"""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "cases.json"
            path.write_text(
                json.dumps(
                    {
                        "benchmark_id": "mini",
                        "cases": [
                            {
                                "claim_id": "x",
                                "source": "a",
                                "relation": "uses",
                                "target": "b",
                                "relation_type": "USES",
                                "evidence_ids": [],
                                "gold_supported": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                self.script.load_benchmark(str(path))

    def test_extend_reports_triggers_only_touches_memory(self) -> None:
        """扩展只改传进来的那份 schema，本体文件里 REPORTS 还是原来那七条。"""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        before = next(
            pattern["triggers"]
            for pattern in schema["relation_patterns"]
            if pattern["relation_type"] == "REPORTS"
        )
        fake_kb = types.SimpleNamespace(schema=schema)
        block = self.script.extend_reports_triggers(fake_kb)
        after = next(
            pattern["triggers"]
            for pattern in schema["relation_patterns"]
            if pattern["relation_type"] == "REPORTS"
        )
        known = {str(item).casefold() for item in before}
        expected = [
            form
            for form in self.script.REPORTS_TRIGGER_LITERAL_FORMS
            if form.casefold() not in known
        ]
        self.assertEqual(len(expected), block["added_count"])
        self.assertEqual(len(after), len(before) + len(expected))
        on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            before,
            next(
                pattern["triggers"]
                for pattern in on_disk["relation_patterns"]
                if pattern["relation_type"] == "REPORTS"
            ),
        )


class BuildScriptForwardsSwitchesTest(unittest.TestCase):
    """三个开关要从命令行一路传到抽取器，不能只在报告里写一行。"""
    def test_build_per_domain_extractors_forwards_three_switches(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        extractors, _ = build_fulltext.build_per_domain_extractors(
            schema,
            ["scientific-ie-kg"],
            word_boundary="unicode",
            direction_check=True,
            reports_triggers="extended",
        )
        extractor = extractors["scientific-ie-kg"]
        self.assertEqual("unicode", extractor.word_boundary)
        self.assertTrue(extractor.direction_check)
        self.assertEqual("extended", extractor.reports_triggers)

    def test_build_per_domain_extractors_defaults_are_off(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        extractors, _ = build_fulltext.build_per_domain_extractors(
            schema, ["scientific-ie-kg"]
        )
        extractor = extractors["scientific-ie-kg"]
        self.assertEqual("ascii", extractor.word_boundary)
        self.assertFalse(extractor.direction_check)
        self.assertEqual("schema", extractor.reports_triggers)


if __name__ == "__main__":
    unittest.main()
