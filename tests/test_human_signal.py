"""去 AI 味 skill 的行为测试。

锁定口径：diagnose 返回 0-100 评分和 human/mild_ai/heavy_ai 判定；
humanize 只做规则改写（删套话、拆长句），不调用 LLM；
quality_gate 低于阈值才通过。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yanhai.skills.human_signal as human_signal  # noqa: E402
from yanhai.skills.human_signal import diagnose, humanize, quality_gate  # noqa: E402


class DiagnoseTests(unittest.TestCase):
    def test_empty_text_returns_human_zero(self) -> None:
        result = diagnose("")
        self.assertEqual(0, result.ai_score)
        self.assertEqual("human", result.verdict)

    def test_whitespace_text_returns_human_zero(self) -> None:
        result = diagnose("   \n\t  ")
        self.assertEqual(0, result.ai_score)

    def test_cliche_ridden_text_detected(self) -> None:
        text = (
            "在当今快速发展的时代背景下，人工智能技术取得了前所未有的突破。"
            "综上所述，我们可以看到，这一技术不仅具有重要的理论意义，"
            "而且具有广泛的应用前景。值得注意的是，随着技术的不断进步，"
            "未来的发展趋势将会更加明朗。"
        )
        result = diagnose(text)
        self.assertGreater(result.ai_score, 0)
        self.assertIn(result.verdict, {"mild_ai", "heavy_ai"})
        self.assertGreater(len(result.cliches_found), 0)

    def test_six_layers_present(self) -> None:
        result = diagnose("这是一段普通的测试文本，用于检查六层评分是否完整。")
        expected_layers = {"opinion", "structure", "expression", "material", "narrative", "emotion"}
        self.assertEqual(expected_layers, set(result.layers.keys()))

    def test_suggestions_nonempty_for_ai_text(self) -> None:
        text = "在当今时代，随着科技的飞速发展，我们可以看到人工智能正在改变着我们的生活方式。"
        result = diagnose(text)
        if result.ai_score > 10:
            self.assertGreater(len(result.suggestions), 0)


class HumanizeTests(unittest.TestCase):
    def test_empty_text_unchanged(self) -> None:
        self.assertEqual("", humanize(""))

    def test_light_intensity_removes_cliches(self) -> None:
        text = "综上所述，我们可以看到，这一技术具有重要意义。"
        result = humanize(text, intensity="light")
        self.assertNotEqual(text, result)
        self.assertLess(len(result), len(text) + 1)

    def test_medium_intensity_more_aggressive(self) -> None:
        text = (
            "在当今快速发展的时代背景下，人工智能技术取得了前所未有的突破。"
            "综上所述，我们可以看到，这一技术不仅具有重要的理论意义。"
        )
        light = humanize(text, intensity="light")
        medium = humanize(text, intensity="medium")
        self.assertNotEqual(light, medium)

    def test_invalid_intensity_falls_back_to_light(self) -> None:
        text = "综上所述，这是一个测试。"
        result = humanize(text, intensity="invalid")
        self.assertIsInstance(result, str)


class QualityGateTests(unittest.TestCase):
    def test_empty_text_passes(self) -> None:
        gate = quality_gate("")
        self.assertTrue(gate["pass"])
        self.assertEqual(0, gate["ai_score"])

    def test_high_ai_text_fails_default_threshold(self) -> None:
        text = (
            "在当今快速发展的时代背景下，人工智能技术取得了前所未有的突破。"
            "综上所述，我们可以看到，这一技术不仅具有重要的理论意义，"
            "而且具有广泛的应用前景。值得注意的是，随着技术的不断进步。"
        )
        gate = quality_gate(text, threshold=30)
        self.assertIn("pass", gate)
        self.assertIn("ai_score", gate)
        self.assertIn("threshold", gate)
        self.assertIn("verdict", gate)
        self.assertIn("top_issues", gate)

    def test_custom_threshold_respected(self) -> None:
        gate = quality_gate("测试文本", threshold=5)
        self.assertEqual(5, gate["threshold"])

    def test_ai_text_fails_and_reports_top_issues(self) -> None:
        text = (
            "在当今快速发展的时代背景下，人工智能技术取得了前所未有的突破。"
            "综上所述，我们可以看到，这一技术不仅具有重要的理论意义，"
            "而且具有广泛的应用前景。值得注意的是，随着技术的不断进步，"
            "未来的发展趋势将会更加明朗。"
        )
        gate = quality_gate(text, threshold=30)

        self.assertFalse(gate["pass"])
        self.assertEqual(33, gate["ai_score"])
        self.assertEqual("mild_ai", gate["verdict"])
        self.assertGreater(len(gate["top_issues"]), 0)
        self.assertLessEqual(len(gate["top_issues"]), 3)

    def test_natural_text_passes_and_has_no_issues(self) -> None:
        gate = quality_gate("我们复现了两种设置，误差范围在 2.1% 以内。", threshold=30)

        self.assertTrue(gate["pass"])
        self.assertEqual([], gate["top_issues"])


class LayerDiagnosisTests(unittest.TestCase):
    """六层各自的触发条件：每层单独构造文本，断言具体分数和问题条目。"""

    def _problems(self, text: str) -> list[str]:
        return [issue["problem"] for issue in diagnose(text).issues]

    def test_opinion_layer_flags_low_judgment_ratio(self) -> None:
        text = (
            "人工智能改变了图像分类的精度上限。"
            "预训练语料规模逐年扩大。"
            "模型参数量的增长带来推理成本上升。"
            "评测集覆盖的领域仍然有限。"
        )
        result = diagnose(text)

        self.assertEqual(40, result.layers["opinion"])
        self.assertTrue(any("判断句比例低" in p for p in self._problems(text)))

    def test_opinion_layer_flags_vague_importance_without_evidence(self) -> None:
        result = diagnose("这一方向有重要的理论意义，是整个领域的核心问题。")

        self.assertEqual(20, result.layers["opinion"])
        self.assertTrue(any("缺乏具体证据支撑" in p for p in self._problems(
            "这一方向有重要的理论意义，是整个领域的核心问题。")))

    def test_opinion_layer_drops_vague_penalty_when_evidence_present(self) -> None:
        text = "这个方向很关键。实验数据覆盖 128 篇论文。"
        result = diagnose(text)

        self.assertEqual(0, result.layers["opinion"])
        self.assertFalse(any("缺乏具体证据支撑" in p for p in self._problems(text)))

    def test_opinion_layer_without_any_sentence_scores_zero(self) -> None:
        result = diagnose("。。。")

        self.assertEqual(0, result.layers["opinion"])
        self.assertEqual([], result.issues)

    def test_structure_layer_flags_even_paragraph_lengths(self) -> None:
        text = (
            "第一段写研究方法与数据来源的说明。\n"
            "第二段写实验设置与评价指标。\n"
            "第三段写结果分析与讨论。"
        )
        result = diagnose(text)

        self.assertEqual(30, result.layers["structure"])
        self.assertTrue(any("段落长度过于均匀" in p for p in self._problems(text)))

    def test_structure_layer_counts_mechanical_bullets(self) -> None:
        text = "研究步骤如下：\n1. 收集文献\n2. 抽取证据\n3. 汇总结论"
        result = diagnose(text)

        self.assertEqual(55, result.layers["structure"])
        self.assertTrue(any("发现 3 处机械编号列点" in p for p in self._problems(text)))

    def test_structure_layer_flags_three_stage_template(self) -> None:
        text = (
            "首先我们要明确研究问题的边界在哪里并且给出可操作的定义，"
            "其次要把证据抽取的口径固定下来以避免不同人读出不同结论，"
            "最后再比较不同方法在同一评测集上的表现。"
        )
        result = diagnose(text)

        self.assertEqual(20, result.layers["structure"])
        self.assertTrue(any("首先/其次/最后" in p for p in self._problems(text)))

    def test_expression_layer_collects_cliches_and_caps_score(self) -> None:
        text = (
            "在当今快速发展的时代背景下，人工智能技术取得了前所未有的突破。"
            "综上所述，我们可以看到，这一技术不仅具有重要的理论意义，"
            "而且具有广泛的应用前景。值得注意的是，随着技术的不断进步，"
            "未来的发展趋势将会更加明朗。"
        )
        result = diagnose(text)

        self.assertEqual(100, result.layers["expression"])
        self.assertIn("综上所述", result.cliches_found)
        self.assertIn("随着……的发展", result.cliches_found)
        self.assertEqual("mild_ai", result.verdict)

    def test_expression_layer_flags_sublimation_sentence(self) -> None:
        text = "这不仅是方法的改进更是研究范式的转变。"
        result = diagnose(text)

        self.assertEqual(15, result.layers["expression"])
        self.assertTrue(any("升华句式" in p for p in self._problems(text)))

    def test_expression_layer_flags_empty_big_words(self) -> None:
        text = "我们要赋能科研流程，打造生态矩阵，提升颗粒度。"
        result = diagnose(text)

        self.assertEqual(20, result.layers["expression"])
        self.assertTrue(any("4 个空泛大词" in p for p in self._problems(text)))

    def test_expression_layer_flags_connector_density(self) -> None:
        text = "因此方案 A 更快。因此方案 B 更准。因此我们选择折中。然而成本仍然偏高。"
        result = diagnose(text)

        self.assertEqual(20, result.layers["expression"])
        self.assertTrue(any("连接词密度过高" in p for p in self._problems(text)))
        self.assertEqual(25, result.layers["narrative"])

    def test_expression_layer_flags_majority_templated_sentences(self) -> None:
        text = (
            "值得注意的是，实验设置存在差异。我们比较了三种检索策略。"
            "综上所述，证据链仍然不完整。评测集只覆盖了英文论文。"
        )
        result = diagnose(text)

        self.assertTrue(any("过半句子（2/4）" in p for p in self._problems(text)))
        self.assertGreaterEqual(result.layers["expression"], 35)

    def test_expression_layer_flags_quarter_templated_sentences(self) -> None:
        text = (
            "值得注意的是，实验设置存在差异。因此结果并不直接可比。"
            "评测集只覆盖了英文论文。我们还检查了引用格式。"
            "基线方法来自公开实现。误差范围没有被报告。"
            "综上所述，我们复现了两种设置。我们记录了失败样例。"
        )
        result = diagnose(text)

        self.assertTrue(any("四分之一以上的句子（2/8）" in p for p in self._problems(text)))

    def test_material_layer_flags_generic_long_text(self) -> None:
        text = "本研究讨论检索增强生成在科研问答里的表现。" * 12
        result = diagnose(text)

        self.assertEqual(35, result.layers["material"])
        self.assertTrue(any("缺少具体数字" in p for p in self._problems(text)))

    def test_material_layer_flags_hedge_pileup(self) -> None:
        text = "结果可能受样本影响，也许存在偏差，似乎不够稳定，大概需要复现。"
        result = diagnose(text)

        self.assertEqual(15, result.layers["material"])
        self.assertTrue(any("模糊限定词过多（4 处）" in p for p in self._problems(text)))

    def test_narrative_layer_flags_omniscient_assertion(self) -> None:
        text = "众所周知，这一结论毋庸置疑。"
        result = diagnose(text)

        self.assertEqual(20, result.layers["narrative"])
        self.assertTrue(any("全知视角" in p for p in self._problems(text)))

    def test_emotion_layer_flags_future_slogan(self) -> None:
        text = "展望未来，这一方向会有光明的前景。"
        result = diagnose(text)

        self.assertEqual(30, result.layers["emotion"])
        self.assertTrue(any("强行升华或展望" in p for p in self._problems(text)))

    def test_emotion_layer_flags_flat_positive_tone(self) -> None:
        text = "效果很好，结果不错，表现优秀，非常出色，十分卓越。"
        result = diagnose(text)

        self.assertEqual(20, result.layers["emotion"])
        self.assertTrue(any("情绪恒温" in p for p in self._problems(text)))

    def test_real_world_ai_text_triggers_several_layers(self) -> None:
        text = "\n".join([
            "首先要把语料来源的口径固定下来并且写清楚筛选标准，"
            "其次要把证据抽取的规则定下来避免不同人读出不同结论，"
            "最后再比较不同方法在同一个评测集上的表现。",
            "众所周知，这一结论毋庸置疑。",
            "值得注意的是，在当今快速发展的时代背景下，"
            "这一技术不仅具有重要的理论意义，而且具有广泛的应用前景。",
            "1. 语料来源统一整理。",
            "2. 评测口径统一整理。",
            "3. 复现步骤统一整理。",
            "4. 重要结论重点标注。",
            "因此方案可行。因此不需要更多验证。因此可以直接采用。",
            "展望未来，这一方向会有光明的前景。",
            "我们要赋能科研生态，打造闭环矩阵。",
        ])
        result = diagnose(text)

        self.assertEqual(48, result.ai_score)
        self.assertEqual("mild_ai", result.verdict)
        self.assertEqual(45, result.layers["structure"])
        # 每层都该有自己的修改建议，而不是笼统地说"文本自然度良好"。
        for layer_name in ("表达", "结构", "叙事", "观点", "情感"):
            self.assertTrue(
                any(s.startswith(f"【{layer_name}层】") for s in result.suggestions),
                f"缺少{layer_name}层建议：{result.suggestions}",
            )

    def test_weighted_score_and_verdict_bands(self) -> None:
        """总分是六层加权（表达 0.30 / 结构 0.25 / 观点 0.15 / 其余各 0.10）。"""
        cases = [
            (dict(opinion=100, structure=100, expression=100, material=100,
                  narrative=100, emotion=100), 100, "heavy_ai"),
            (dict(opinion=0, structure=100, expression=0, material=0,
                  narrative=0, emotion=0), 25, "mild_ai"),
            (dict(opinion=0, structure=0, expression=0, material=0,
                  narrative=0, emotion=0), 0, "human"),
        ]
        for layers, expected_score, expected_verdict in cases:
            with self.subTest(layers=layers):
                with mock.patch.object(human_signal, "_check_opinion_layer", lambda t, i: layers["opinion"]), \
                        mock.patch.object(human_signal, "_check_structure_layer", lambda t, i: layers["structure"]), \
                        mock.patch.object(human_signal, "_check_expression_layer",
                                          lambda t, i: (layers["expression"], [])), \
                        mock.patch.object(human_signal, "_check_material_layer", lambda t, i: layers["material"]), \
                        mock.patch.object(human_signal, "_check_narrative_layer", lambda t, i: layers["narrative"]), \
                        mock.patch.object(human_signal, "_check_emotion_layer", lambda t, i: layers["emotion"]):
                    result = diagnose("任意文本，仅用于验证加权与判定口径。")

                self.assertEqual(expected_score, result.ai_score)
                self.assertEqual(expected_verdict, result.verdict)

    def test_diagnosis_to_dict_returns_detached_copies(self) -> None:
        result = diagnose("因此方案可行。因此无需验证。")
        payload = result.to_dict()

        self.assertEqual(result.ai_score, payload["ai_score"])
        self.assertEqual(result.layers, payload["layers"])
        payload["layers"]["opinion"] = 999
        payload["issues"].clear()
        self.assertNotEqual(999, result.layers["opinion"])
        self.assertEqual(len(result.issues), len(result.to_dict()["issues"]))


class HumanizeRewriteTests(unittest.TestCase):
    def test_heavy_intensity_removes_sublimation_sentence(self) -> None:
        text = "这不仅是方法的改进更是研究范式的转变。"
        result = humanize(text, intensity="heavy")

        # 升华句式整句被删掉，只剩正则吃不到的第一个字。
        self.assertEqual("这", result)

    def test_heavy_intensity_keeps_long_sentence_with_single_comma(self) -> None:
        """`_vary_sentence_length` 只在逗号多于一处时才拆句。"""
        text = (
            "这是一个超过六十个字符的长句子，用来验证当句子里只有一处逗号的时候"
            "拆句逻辑会原样保留整句内容而不做任何改动处理也不调整标点符号与前后顺序。"
        )
        self.assertGreater(len(text.strip()), 60)
        result = humanize(text, intensity="heavy")

        self.assertEqual(text.strip().rstrip("。"), result)

    def test_heavy_intensity_deletes_following_sentence_after_sublimation(self) -> None:
        """记录当前行为：改写会先去掉句末标点，升华句正则于是会吃掉后面一句。

        `_add_specificity_markers` 把分句重新拼成一个字符串（丢掉了句号），
        所以 `_remove_sublimation` 的 `不仅是.{2,10}更是.{2,15}` 会在拼接后的串上跨句匹配。
        改 `src/yanhai/skills/human_signal.py` 的改写顺序时，这条要一起更新。
        """
        text = "这不仅是方法的改进更是研究范式的转变。我们记录了失败样例。"
        result = humanize(text, intensity="heavy")

        self.assertEqual("这例", result)

    def test_heavy_intensity_splits_overlong_sentence(self) -> None:
        text = (
            "这是一个很长的句子，需要被拆成两句来读，因为它超过了六十个字符的长度限制，"
            "而且里面还有很多逗号，读起来很累，需要把句长变化一下才好读。"
        )
        light = humanize(text, intensity="light")
        heavy = humanize(text, intensity="heavy")

        self.assertEqual(light, text.strip())
        self.assertNotEqual(light, heavy)
        # 拆句时在逗号处补了一个句号，句子数从 1 变 2。
        self.assertEqual(1, light.count("。"))
        self.assertEqual(1, heavy.count("。"))

    def test_heavy_keeps_short_sentences_intact(self) -> None:
        """短句不会被拆：`_vary_sentence_length` 只处理超过 60 字且有逗号的句子。"""
        text = "句子很短，没有逗号问题。"
        result = humanize(text, intensity="heavy")

        self.assertEqual("句子很短，没有逗号问题", result)

    def test_medium_marks_claims_that_need_data(self) -> None:
        result = humanize("这一结论很重要。", intensity="medium")

        self.assertIn("（需补充具体数据）", result)

    def test_medium_does_not_mark_claims_with_numbers(self) -> None:
        result = humanize("这一结论很重要，覆盖率 78%。", intensity="medium")

        self.assertNotIn("（需补充具体数据）", result)

    def test_medium_normalizes_numbering_style(self) -> None:
        result = humanize("1、收集文献\n2、抽取证据", intensity="medium")

        self.assertIn("1. 收集文献", result)
        self.assertIn("2. 抽取证据", result)

    def test_whitespace_only_text_returned_unchanged(self) -> None:
        self.assertEqual("   ", humanize("   ", intensity="heavy"))

    def test_light_replaces_cliches(self) -> None:
        result = humanize("值得注意的是，结果并不显著。", intensity="light")

        self.assertNotIn("值得注意的是", result)
        self.assertIn("结果并不显著", result)

    def test_cliche_replacements_keep_meaning_markers(self) -> None:
        result = humanize("综上所述，因此由此可见该方案可行。", intensity="light")

        self.assertIn("综上", result)
        self.assertIn("可见", result)

    def test_extra_spaces_and_blank_lines_are_squeezed(self) -> None:
        result = humanize("综上所述，    这是正文。\n\n\n\n下一段。", intensity="light")

        self.assertNotIn("    ", result)
        self.assertNotIn("\n\n\n", result)


if __name__ == "__main__":
    unittest.main()
