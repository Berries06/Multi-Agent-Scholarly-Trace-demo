# -*- coding: utf-8 -*-
"""`src/yanhai/metrics.py` 的单元测试：口径边界、已知答案、样本量判定。

这里的数据全部是测试里当场写出来的构造数据，跟仓库里的评测集无关，也不代表任何
真实测量结果。每条用例盯的是口径本身，不是数字好不好看。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.metrics import (  # noqa: E402
    HALLUCINATION_ZERO_ERROR_SAMPLE_MIN,
    REAL_CASE_MIN,
    adaptation_report,
    build_report,
    case_count_report,
    cohen_kappa,
    coverage_report,
    hallucination_report,
    render_text_summary,
    wilson_interval,
)


def make_sample(case_id: str, label: str, status: str = "accepted", **extra):
    """拼一条被抽查样本：系统状态 + 人工标签（+ 可选第二标注者）。"""
    sample = {"case_id": case_id, "system_status": status, "label_1": label}
    sample.update(extra)
    return sample


def make_real_case(index: int, status: str = "accepted", label: str = "SUPPORTED"):
    """拼一条"真实论文原文用例"：论文标识、页码、字符偏移、逐字原文都齐。"""
    return {
        "case_id": f"case-{index:03d}",
        "source": "real",
        "paper_id": f"paper-{index % 7}",
        "page": 1 + index % 5,
        "char_start": 100 * index,
        "char_end": 100 * index + 40,
        "quote": f"逐字原文片段 {index}",
        "system_status": status,
        "label_1": label,
        "label_2": label,
    }


class WilsonIntervalTests(unittest.TestCase):
    """Wilson 区间：73 这个样本量要求的来源，以及边界与单调性。"""

    def test_zero_error_at_73_passes_the_5_percent_line(self):
        lower, upper = wilson_interval(0, 73)
        self.assertEqual(lower, 0.0)
        self.assertLess(upper, 0.05)
        self.assertAlmostEqual(upper, 0.049992, delta=1e-6)
        self.assertAlmostEqual(upper, 0.05, delta=2e-5)

    def test_zero_error_at_72_misses_the_5_percent_line(self):
        _, upper = wilson_interval(0, 72)
        self.assertGreater(upper, 0.05)
        self.assertAlmostEqual(upper, 0.050651, delta=1e-6)

    def test_the_two_sample_sizes_straddle_the_line(self):
        """73 与 72 只差一条，却是过线与不过线的分界，这条盯住不要把门槛改松。"""
        self.assertLess(wilson_interval(0, 73)[1], 0.05)
        self.assertGreater(wilson_interval(0, 72)[1], 0.05)
        self.assertEqual(HALLUCINATION_ZERO_ERROR_SAMPLE_MIN, 73)

    def test_total_zero_returns_full_range_without_dividing_by_zero(self):
        self.assertEqual(wilson_interval(0, 0), (0.0, 1.0))

    def test_all_successes_bounds(self):
        """全出错时：样本量越大下界越往上走，上界贴住 1.0。"""
        small = wilson_interval(1, 1)
        self.assertAlmostEqual(small[0], 0.206549, delta=1e-6)
        self.assertAlmostEqual(small[1], 1.0, delta=1e-12)
        middle = wilson_interval(10, 10)
        large = wilson_interval(1000, 1000)
        self.assertAlmostEqual(middle[1], 1.0, delta=1e-12)
        self.assertAlmostEqual(large[1], 1.0, delta=1e-12)
        self.assertLess(small[0], middle[0])
        self.assertLess(middle[0], large[0])
        self.assertGreater(large[0], 0.99)

    def test_all_zero_bounds(self):
        """全对时：上界随样本量往下走，下界贴住 0.0。"""
        one = wilson_interval(0, 1)
        ten = wilson_interval(0, 10)
        big = wilson_interval(0, 1000)
        self.assertAlmostEqual(one[1], 0.793451, delta=1e-6)
        self.assertAlmostEqual(one[0], 0.0, delta=1e-12)
        self.assertAlmostEqual(ten[0], 0.0, delta=1e-12)
        self.assertAlmostEqual(big[0], 0.0, delta=1e-12)
        self.assertGreater(one[1], ten[1])
        self.assertGreater(ten[1], big[1])
        self.assertLess(big[1], 0.01)

    def test_monotone_in_successes(self):
        """样本量一样时，出错越多，下界与上界都不下降。"""
        previous = wilson_interval(0, 50)
        for successes in range(1, 51):
            current = wilson_interval(successes, 50)
            self.assertGreaterEqual(current[0], previous[0] - 1e-12)
            self.assertGreaterEqual(current[1], previous[1] - 1e-12)
            previous = current

    def test_bounds_stay_inside_unit_interval(self):
        for successes, total in ((0, 1), (1, 3), (37, 73), (73, 73), (0, 1000)):
            lower, upper = wilson_interval(successes, total)
            self.assertGreaterEqual(lower, 0.0)
            self.assertLessEqual(upper, 1.0)
            self.assertLessEqual(lower, upper)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            wilson_interval(-1, 10)
        with self.assertRaises(ValueError):
            wilson_interval(1, -1)
        with self.assertRaises(ValueError):
            wilson_interval(11, 10)
        with self.assertRaises(ValueError):
            wilson_interval(1, 10, z=0)


class CohenKappaTests(unittest.TestCase):
    """两名标注者的一致性：算得出、没样本时给 None、完全一致时不除零。"""

    def test_perfect_agreement_has_kappa_one(self):
        pairs = [("SUPPORTED", "SUPPORTED"), ("UNSUPPORTED", "UNSUPPORTED")]
        result = cohen_kappa(pairs)
        self.assertEqual(result["kappa"], 1.0)
        self.assertEqual(result["observed_agreement"], 1.0)

    def test_known_kappa_value(self):
        # 3 条一致、1 条不一致：观测一致率 0.75，随机一致率 0.5 → kappa 0.5
        pairs = [
            ("A", "A"),
            ("A", "A"),
            ("A", "B"),
            ("B", "B"),
        ]
        result = cohen_kappa(pairs)
        self.assertAlmostEqual(result["observed_agreement"], 0.75)
        self.assertAlmostEqual(result["expected_agreement"], 0.5)
        self.assertAlmostEqual(result["kappa"], 0.5)

    def test_no_pairs_returns_none(self):
        result = cohen_kappa([])
        self.assertIsNone(result["kappa"])
        self.assertEqual(result["n"], 0)

    def test_pairs_with_one_side_missing_are_skipped(self):
        result = cohen_kappa([("A", ""), ("", "A"), ("A", "A")])
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["kappa"], 1.0)


class HallucinationReportTests(unittest.TestCase):
    """幻觉率：分母只数 accepted，INSUFFICIENT 单列且不进分子分母。"""

    def test_only_accepted_claims_count(self):
        samples = [
            make_sample("a-1", "SUPPORTED"),
            make_sample("a-2", "UNSUPPORTED"),
            make_sample("r-1", "UNSUPPORTED", status="rejected"),
            make_sample("v-1", "SUPPORTED", status="review"),
        ]
        report = hallucination_report(samples)
        self.assertEqual(report["accepted_total"], 2)
        self.assertEqual(report["unsupported_count"], 1)
        self.assertAlmostEqual(report["hallucination_rate"], 0.5)
        self.assertEqual(report["unsupported_cases"], ["a-2"])

    def test_insufficient_is_counted_but_kept_out_of_both_sides(self):
        samples = [
            make_sample("a-1", "SUPPORTED"),
            make_sample("a-2", "SUPPORTED"),
            make_sample("a-3", "INSUFFICIENT"),
            make_sample("a-4", "INSUFFICIENT", status="rejected"),
        ]
        report = hallucination_report(samples)
        # INSUFFICIENT 一条都不进分子分母，哪怕它底下是 accepted。
        self.assertEqual(report["accepted_total"], 2)
        self.assertEqual(report["unsupported_count"], 0)
        self.assertEqual(report["insufficient_count"], 2)
        self.assertEqual(report["total_samples"], 4)
        # 占比的分母是"全部被抽查样本"，不是 accepted 数。
        self.assertAlmostEqual(report["insufficient_ratio"], 0.5)
        self.assertEqual(report["insufficient_cases"], ["a-3", "a-4"])

    def test_insufficient_over_ten_percent_blocks_the_claim(self):
        samples = [make_sample(f"a-{i}", "SUPPORTED") for i in range(73)]
        samples.append(make_sample("a-ins", "INSUFFICIENT"))
        report = hallucination_report(samples)
        # 1/74 = 1.35%，没超 10%，样本量够且零错，可以声明。
        self.assertTrue(report["can_claim_upper_under_5pct"])

        blocked = [make_sample(f"b-{i}", "SUPPORTED") for i in range(73)]
        blocked.extend(make_sample(f"b-ins-{i}", "INSUFFICIENT") for i in range(9))
        report = hallucination_report(blocked)
        # 9/82 = 10.98%，过了 10%，这批结果不能用于声明达标。
        self.assertGreater(report["insufficient_ratio"], 0.10)
        self.assertFalse(report["can_claim_upper_under_5pct"])
        self.assertIn("INSUFFICIENT", report["reason"])

    def test_low_kappa_blocks_the_claim(self):
        samples = [
            make_sample(f"s-{i}", "SUPPORTED", label_2="SUPPORTED" if i % 4 else "UNSUPPORTED")
            for i in range(73)
        ]
        report = hallucination_report(samples)
        self.assertIsNotNone(report["kappa"])
        self.assertLess(report["kappa"], 0.6)
        self.assertFalse(report["can_claim_upper_under_5pct"])
        self.assertIn("作废", report["reason"])

    def test_zero_error_with_enough_samples_can_claim(self):
        samples = [
            make_sample(f"s-{i}", "SUPPORTED", label_2="SUPPORTED")
            for i in range(HALLUCINATION_ZERO_ERROR_SAMPLE_MIN)
        ]
        report = hallucination_report(samples)
        self.assertEqual(report["accepted_total"], 73)
        self.assertEqual(report["unsupported_count"], 0)
        self.assertLess(report["wilson_upper"], 0.05)
        self.assertTrue(report["can_claim_upper_under_5pct"])
        self.assertIn("可以声明", report["claim"])

    def test_short_sample_with_zero_error_says_sample_too_small(self):
        samples = [make_sample(f"s-{i}", "SUPPORTED") for i in range(20)]
        report = hallucination_report(samples)
        self.assertFalse(report["can_claim_upper_under_5pct"])
        self.assertIn("样本量不足", report["reason"])

    def test_empty_input_does_not_crash(self):
        report = hallucination_report([])
        self.assertEqual(report["accepted_total"], 0)
        self.assertEqual(report["hallucination_rate"], 0.0)
        self.assertEqual(report["insufficient_ratio"], 0.0)
        self.assertFalse(report["can_claim_upper_under_5pct"])

    def test_error_flag_forces_the_case_into_the_numerator(self):
        samples = [
            make_sample("a-1", "SUPPORTED", error=True),
            make_sample("a-2", "SUPPORTED"),
        ]
        report = hallucination_report(samples)
        self.assertEqual(report["unsupported_count"], 1)
        self.assertEqual(report["unsupported_cases"], ["a-1"])


class AdaptationReportTests(unittest.TestCase):
    """适配准确率：规则口径三个条件、人工口径三档、两条口径的不一致清单。"""

    @staticmethod
    def record(
        path_id: str,
        *,
        expected: int = 3,
        target: int = 3,
        required=("DKT", "BKT", "AUC"),
        covered=("DKT", "BKT", "AUC"),
        mastered=("GNN",),
        targets=("DKT", "BKT"),
        profile_id: str = "p-1",
    ):
        return {
            "profile_id": profile_id,
            "path_id": path_id,
            "expected_difficulty": expected,
            "target_difficulty": target,
            "required_concepts": list(required),
            "covered_concepts": list(covered),
            "mastered_concepts": list(mastered),
            "target_concepts": list(targets),
        }

    def test_happy_path_record_is_adapted(self):
        report = adaptation_report([self.record("path-1")])
        self.assertEqual(report["adaptation_accuracy"], 1.0)
        self.assertEqual(report["rule_adapted_count"], 1)
        self.assertTrue(report["records"][0]["rule_adapted"])

    def test_difficulty_gap_over_one_fails(self):
        report = adaptation_report([self.record("path-1", expected=1, target=3)])
        self.assertFalse(report["records"][0]["rule_adapted"])
        self.assertEqual(report["rule_condition_failures"]["difficulty_gap_ok"], 1)

    def test_difficulty_gap_exactly_one_passes(self):
        report = adaptation_report([self.record("path-1", expected=2, target=3)])
        self.assertTrue(report["records"][0]["rule_adapted"])
        self.assertEqual(report["records"][0]["difficulty_gap"], 1)

    def test_required_coverage_boundary(self):
        """覆盖 2/3 ≈ 0.667 不够；覆盖 4/5 = 0.8 刚好够。"""
        short = adaptation_report(
            [self.record("path-1", required=("a", "b", "c"), covered=("a", "b"))]
        )
        self.assertFalse(short["records"][0]["rule_adapted"])
        self.assertEqual(short["records"][0]["missing_required_concepts"], ["c"])

        exact = adaptation_report(
            [self.record("path-2", required=("a", "b", "c", "d", "e"), covered=("a", "b", "c", "d"))]
        )
        self.assertAlmostEqual(exact["records"][0]["required_covered_ratio"], 0.8)
        self.assertTrue(exact["records"][0]["rule_adapted"])

    def test_mastered_as_main_target_boundary(self):
        """已掌握的被当主目标 1/5 = 0.2 刚好够；2/5 = 0.4 就超了。"""
        ok = adaptation_report(
            [self.record("path-1", mastered=("x",), targets=("x", "a", "b", "c", "d"))]
        )
        self.assertAlmostEqual(ok["records"][0]["mastered_target_ratio"], 0.2)
        self.assertTrue(ok["records"][0]["rule_adapted"])

        over = adaptation_report(
            [self.record("path-2", mastered=("x", "y"), targets=("x", "y", "a", "b", "c"))]
        )
        self.assertAlmostEqual(over["records"][0]["mastered_target_ratio"], 0.4)
        self.assertFalse(over["records"][0]["rule_adapted"])
        self.assertEqual(
            over["rule_condition_failures"]["mastered_not_main_target_ok"], 1
        )

    def test_rule_accuracy_over_several_records(self):
        report = adaptation_report(
            [
                self.record("path-1"),
                self.record("path-2", expected=1, target=4),
                self.record("path-3"),
                self.record("path-4", required=("a", "b", "c"), covered=("a",)),
            ]
        )
        self.assertEqual(report["total_records"], 4)
        self.assertEqual(report["rule_adapted_count"], 2)
        self.assertAlmostEqual(report["adaptation_accuracy"], 0.5)

    def test_human_labels_list_and_dict_give_the_same_answer(self):
        records = [self.record("path-1"), self.record("path-2", expected=1, target=4)]
        as_list = adaptation_report(
            records,
            [{"path_id": "path-1", "verdict": "合适"}, {"path_id": "path-2", "verdict": "合适"}],
        )
        as_dict = adaptation_report(records, {"path-1": "合适", "path-2": "合适"})
        self.assertEqual(as_list["human"]["suitable_count"], 2)
        self.assertEqual(as_dict["human"]["suitable_count"], 2)
        self.assertAlmostEqual(as_list["human"]["adaptation_accuracy"], 1.0)
        self.assertAlmostEqual(as_dict["human"]["adaptation_accuracy"], 1.0)

    def test_human_verdict_synonyms(self):
        records = [self.record("path-1")]
        report = adaptation_report(records, [{"path_id": "path-1", "verdict": "suitable"}])
        self.assertEqual(report["human"]["suitable_count"], 1)
        english = adaptation_report(records, [{"path_id": "path-1", "verdict": "too_hard"}])
        self.assertEqual(english["human"]["suitable_count"], 0)
        self.assertEqual(english["human"]["records"][0]["human_verdict"], "too_hard")

    def test_mismatches_are_listed_one_by_one(self):
        records = [
            self.record("path-1"),  # 规则=适配
            self.record("path-2", expected=1, target=4),  # 规则=不适配
        ]
        report = adaptation_report(
            records,
            [{"path_id": "path-1", "verdict": "偏难"}, {"path_id": "path-2", "verdict": "合适"}],
        )
        mismatches = report["agreement"]["mismatches"]
        self.assertEqual(len(mismatches), 2)
        self.assertEqual(mismatches[0]["path_id"], "path-1")
        self.assertTrue(mismatches[0]["rule_value"])
        self.assertFalse(mismatches[0]["human_value"])
        self.assertEqual(mismatches[0]["human_verdict"], "too_hard")
        self.assertEqual(report["agreement"]["agreement_rate"], 0.0)

    def test_agreement_rate_when_two_of_three_match(self):
        records = [self.record("path-1"), self.record("path-2"), self.record("path-3", expected=1, target=4)]
        report = adaptation_report(
            records,
            [
                {"path_id": "path-1", "verdict": "合适"},
                {"path_id": "path-2", "verdict": "合适"},
                {"path_id": "path-3", "verdict": "合适"},
            ],
        )
        self.assertEqual(report["agreement"]["comparable_total"], 3)
        self.assertEqual(report["agreement"]["agree_total"], 2)
        self.assertAlmostEqual(report["agreement"]["agreement_rate"], 2 / 3, delta=1e-6)

    def test_missing_human_labels_blocks_the_claim(self):
        report = adaptation_report([self.record("path-1")])
        self.assertEqual(report["human"]["labeled_total"], 0)
        self.assertFalse(report["can_claim"])
        self.assertIn("人工", report["reason"])

    def test_high_accuracy_but_small_sample_is_still_blocked(self):
        records = [self.record(f"path-{i}") for i in range(20)]
        labels = [{"path_id": f"path-{i}", "verdict": "合适"} for i in range(20)]
        report = adaptation_report(records, labels)
        self.assertAlmostEqual(report["human"]["adaptation_accuracy"], 1.0)
        self.assertFalse(report["can_claim"])
        self.assertIn("样本量不足", report["reason"])

    def test_enough_samples_and_accuracy_can_claim(self):
        total = 100
        suitable = 90
        records = [self.record(f"path-{i}") for i in range(total)]
        labels = [
            {"path_id": f"path-{i}", "verdict": "合适" if i < suitable else "偏难"}
            for i in range(total)
        ]
        report = adaptation_report(records, labels)
        self.assertEqual(report["human"]["labeled_total"], 100)
        self.assertEqual(report["human"]["suitable_count"], 90)
        self.assertGreaterEqual(report["human"]["wilson_lower"], 0.80)
        self.assertTrue(report["can_claim"])

    def test_low_accuracy_with_enough_samples_is_not_claimed(self):
        total = 100
        records = [self.record(f"path-{i}") for i in range(total)]
        labels = [
            {"path_id": f"path-{i}", "verdict": "合适" if i < 60 else "偏易"}
            for i in range(total)
        ]
        report = adaptation_report(records, labels)
        self.assertFalse(report["can_claim"])
        self.assertIn("未达到 85%", report["reason"])

    def test_empty_records_do_not_crash(self):
        report = adaptation_report([])
        self.assertEqual(report["total_records"], 0)
        self.assertEqual(report["adaptation_accuracy"], 0.0)
        self.assertFalse(report["can_claim"])


class CoverageReportTests(unittest.TestCase):
    """覆盖率：严格档在任何数据下都不高于宽松档；未覆盖清单要列出来。"""

    POINTS = [
        {
            "knowledge_point_id": "kp-a",
            "canonical": "Deep Knowledge Tracing",
            "aliases": ["DKT"],
            "entity_type": "method",
            "domain_id": "d-1",
        },
        {
            "knowledge_point_id": "kp-b",
            "canonical": "Bayesian Knowledge Tracing",
            "aliases": ["BKT"],
            "entity_type": "method",
            "domain_id": "d-1",
        },
        {
            "knowledge_point_id": "kp-c",
            "canonical": "Knowledge Tracing Dataset",
            "aliases": [],
            "entity_type": "dataset",
            "domain_id": "d-2",
        },
    ]

    @staticmethod
    def hit(kp_id: str, paper_id: str, surface: str, status: str = "accepted", index: int = 0):
        return {
            "knowledge_point_id": kp_id,
            "paper_id": paper_id,
            "page": 1 + index,
            "char_start": 10 * index,
            "char_end": 10 * index + len(surface),
            "matched_text": surface,
            "status": status,
        }

    def test_strict_is_never_higher_than_loose(self):
        hits = [
            self.hit("kp-a", "p-1", "DKT", index=1),  # 只有一篇 → 只算宽松
            self.hit("kp-b", "p-1", "BKT", index=2),  # 两篇 → 两档都算
            self.hit("kp-b", "p-2", "Bayesian Knowledge Tracing", index=3),
        ]
        report = coverage_report(self.POINTS, hits)
        self.assertEqual(report["total_points"], 3)
        self.assertEqual(report["overall_loose"]["covered"], 2)
        self.assertEqual(report["overall_strict"]["covered"], 1)
        self.assertLessEqual(
            report["overall_strict"]["coverage"], report["overall_loose"]["coverage"]
        )
        self.assertLess(report["overall_strict"]["coverage"], 0.90)
        self.assertFalse(report["can_claim"])

    def test_alias_matches_the_same_way_as_canonical(self):
        hits = [self.hit("kp-a", "p-1", "dkt", index=1)]
        report = coverage_report(self.POINTS, hits)
        point = {row["knowledge_point_id"]: row for row in report["knowledge_points"]}["kp-a"]
        self.assertTrue(point["loose_supported"])
        self.assertEqual(point["papers_loose"], ["p-1"])

    def test_matched_text_also_matches_when_point_id_is_absent(self):
        hits = [
            {
                "paper_id": "p-1",
                "page": 2,
                "char_start": 30,
                "char_end": 41,
                "matched_text": "DKT",
                "status": "accepted",
            },
            {
                "paper_id": "p-2",
                "page": 3,
                "char_start": 40,
                "char_end": 51,
                "matched_text": "DKT",
                "status": "accepted",
            },
        ]
        report = coverage_report(self.POINTS, hits)
        point = {row["knowledge_point_id"]: row for row in report["knowledge_points"]}["kp-a"]
        self.assertTrue(point["strict_supported"])

    def test_non_accepted_or_incomplete_hits_do_not_count(self):
        hits = [
            self.hit("kp-a", "p-1", "DKT", status="review", index=1),
            {  # 缺页码
                "knowledge_point_id": "kp-a",
                "paper_id": "p-2",
                "char_start": 0,
                "char_end": 3,
                "status": "accepted",
            },
            {  # 字符偏移反了
                "knowledge_point_id": "kp-a",
                "paper_id": "p-3",
                "page": 1,
                "char_start": 9,
                "char_end": 3,
                "status": "accepted",
            },
        ]
        report = coverage_report(self.POINTS, hits)
        point = {row["knowledge_point_id"]: row for row in report["knowledge_points"]}["kp-a"]
        self.assertFalse(point["loose_supported"])
        self.assertEqual(report["total_usable_hits"], 0)

    def test_uncovered_list_names_the_points_without_any_hit(self):
        hits = [self.hit("kp-a", "p-1", "DKT", index=1)]
        report = coverage_report(self.POINTS, hits)
        uncovered = {row["knowledge_point_id"] for row in report["uncovered"]}
        self.assertEqual(uncovered, {"kp-b", "kp-c"})
        # 领域那一块要写明未覆盖几条、只有单篇证据几条。
        self.assertIn("未覆盖 1 条", report["domains"]["d-1"]["reason"])
        self.assertIn("只有单篇证据的 1 条", report["domains"]["d-1"]["reason"])

    def test_loose_only_list_names_the_points_with_one_paper(self):
        hits = [self.hit("kp-a", "p-1", "DKT", index=1)]
        report = coverage_report(self.POINTS, hits)
        loose_only = {row["knowledge_point_id"] for row in report["loose_only"]}
        self.assertEqual(loose_only, {"kp-a"})

    def test_same_paper_twice_is_not_two_papers(self):
        hits = [
            self.hit("kp-a", "p-1", "DKT", index=1),
            self.hit("kp-a", "p-1", "Deep Knowledge Tracing", index=2),
        ]
        report = coverage_report(self.POINTS, hits)
        point = {row["knowledge_point_id"]: row for row in report["knowledge_points"]}["kp-a"]
        self.assertTrue(point["loose_supported"])
        self.assertFalse(point["strict_supported"])

    def test_domain_at_90_percent_can_claim(self):
        points = [
            {
                "knowledge_point_id": f"kp-{i}",
                "canonical": f"概念{i}",
                "aliases": [],
                "entity_type": "method",
                "domain_id": "d-1",
            }
            for i in range(10)
        ]
        hits = []
        for i in range(9):
            hits.append(self.hit(f"kp-{i}", "p-1", f"概念{i}", index=i))
            hits.append(self.hit(f"kp-{i}", "p-2", f"概念{i}", index=i))
        report = coverage_report(points, hits)
        self.assertEqual(report["overall_strict"]["covered"], 9)
        self.assertAlmostEqual(report["overall_strict"]["coverage"], 0.9)
        self.assertTrue(report["domains"]["d-1"]["can_claim_strict"])
        self.assertTrue(report["can_claim"])

    def test_missing_domain_field_goes_to_a_placeholder_group(self):
        points = [{"knowledge_point_id": "kp-x", "canonical": "概念", "aliases": []}]
        report = coverage_report(points, [])
        self.assertIn("(未标领域)", report["domains"])

    def test_empty_knowledge_points_do_not_crash(self):
        report = coverage_report([], [])
        self.assertEqual(report["total_points"], 0)
        self.assertEqual(report["overall_strict"]["coverage"], 0.0)
        self.assertFalse(report["can_claim"])


class CaseCountReportTests(unittest.TestCase):
    """用例计数：真实论文原文用例与开发池用例分开数。"""

    def test_real_cases_need_all_four_fields(self):
        cases = [
            make_real_case(1),
            make_real_case(2),
            {"case_id": "pool-1", "source": "synthetic"},
            {"case_id": "pool-2", "paper_id": "p-1"},  # 缺页码、偏移、原文
        ]
        report = case_count_report(cases)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["real_paper_count"], 2)
        self.assertEqual(report["development_pool_count"], 2)
        missing = {
            item["case_id"]: item["missing_fields"] for item in report["development_pool_examples"]
        }
        self.assertIn("page", missing["pool-2"])
        self.assertIn("quote", missing["pool-2"])

    def test_synthetic_never_counts_even_with_all_fields(self):
        case = make_real_case(3)
        case["source"] = "synthetic"
        report = case_count_report([case])
        self.assertEqual(report["real_paper_count"], 0)
        self.assertEqual(report["development_pool_count"], 1)

    def test_threshold_uses_the_real_paper_count(self):
        report = case_count_report([make_real_case(i) for i in range(REAL_CASE_MIN)])
        self.assertTrue(report["can_claim_at_least_50"])
        short = case_count_report([make_real_case(i) for i in range(REAL_CASE_MIN - 1)])
        self.assertFalse(short["can_claim_at_least_50"])
        self.assertIn("不能声明达标", short["claim"])

    def test_broken_offsets_do_not_count_as_real(self):
        case = make_real_case(4)
        case["char_end"] = case["char_start"]
        report = case_count_report([case])
        self.assertEqual(report["real_paper_count"], 0)

    def test_accepts_the_shape_our_benchmark_files_actually_use(self):
        """项目里真原文评测集（`data/evaluation/decision_benchmark_real_v*.json`）的写法：

        页码是全文库的段落标识 `page-001`（不是整数），原文放在 `evidence_text` 里。
        这两种写法都要认，否则我们自己造的真原文用例会被判成开发池。
        """
        case = {
            "claim_id": "RP-001",
            "paper_id": "2022.emnlp-main.46",
            "page": "page-001",
            "char_start": 1209,
            "char_end": 1413,
            "evidence_text": "For the low-level selection stage, RESEL designs a cross-modal entity correlation graph.",
            "gold_supported": True,
        }
        report = case_count_report([case])
        self.assertEqual(report["real_paper_count"], 1)
        self.assertEqual(report["development_pool_count"], 0)

        # 段落名也是位置标识：真原文评测集里有 4 条题目的证据取自论文标题那一段（`title`）。
        # 以前只认能抠出数字的页码，这 4 条被误判成开发池用例。
        case["page"] = "title"
        self.assertEqual(case_count_report([case])["real_paper_count"], 1)

        # 位置标识为空或干脆没有，仍然不算真实用例。
        case["page"] = "   "
        self.assertEqual(case_count_report([case])["real_paper_count"], 0)
        case.pop("page")
        self.assertEqual(case_count_report([case])["real_paper_count"], 0)

    def test_empty_input_does_not_crash(self):
        report = case_count_report([])
        self.assertEqual(report["total"], 0)
        self.assertFalse(report["can_claim_at_least_50"])


class BuildReportTests(unittest.TestCase):
    """总报告：拼装、数据版本、以及"不能声明达标"的判定。"""

    def test_small_sample_is_not_claimed_as_meeting_the_bar(self):
        report = build_report(
            cases=[make_real_case(i) for i in range(30)],
            knowledge_points=CoverageReportTests.POINTS,
            evidence_hits=[],
            data_version="hash-test",
        )
        self.assertEqual(report["verdict"]["status"], "不能声明达标")
        self.assertFalse(report["verdict"]["can_claim_all"])
        self.assertFalse(report["hallucination"]["can_claim_upper_under_5pct"])
        self.assertIn("样本量不足", report["hallucination"]["reason"])
        self.assertIn("不能声明达标", report["verdict"]["summary"])

    def test_example_data_never_claims_anything(self):
        cases = [
            make_real_case(i, label="SUPPORTED")
            for i in range(HALLUCINATION_ZERO_ERROR_SAMPLE_MIN)
        ]
        report = build_report(
            cases=cases,
            knowledge_points=CoverageReportTests.POINTS,
            evidence_hits=[],
            is_example_data=True,
            data_version="hash-example",
        )
        # 幻觉率那一块本身算得过（73 条零错），但示例数据必须压住总体判定。
        self.assertTrue(report["hallucination"]["can_claim_upper_under_5pct"])
        self.assertEqual(report["verdict"]["status"], "不能声明达标")
        self.assertFalse(report["verdict"]["can_claim_all"])
        self.assertIn("示例", report["verdict"]["reason"])

    def test_data_version_is_carried_through(self):
        report = build_report(data_version="abc123")
        self.assertEqual(report["data_version"], "abc123")
        self.assertFalse(report["verdict"]["can_claim_all"])

    def test_every_item_has_claim_and_reason_text(self):
        report = build_report(
            cases=[make_real_case(i) for i in range(5)],
            knowledge_points=CoverageReportTests.POINTS,
            adaptation_records=[
                {
                    "profile_id": "p-1",
                    "path_id": "path-1",
                    "expected_difficulty": 3,
                    "target_difficulty": 3,
                    "required_concepts": ["DKT"],
                    "covered_concepts": ["DKT"],
                    "mastered_concepts": [],
                    "target_concepts": ["DKT"],
                }
            ],
            data_version="hash-text",
        )
        self.assertEqual(len(report["verdict"]["items"]), 4)
        for item in report["verdict"]["items"]:
            self.assertTrue(item["claim"])
            self.assertTrue(item["reason"])
        self.assertTrue(report["adaptation"]["reason"])

    def test_report_is_json_serialisable(self):
        import json

        report = build_report(
            cases=[make_real_case(1)],
            knowledge_points=CoverageReportTests.POINTS,
            evidence_hits=[],
            adaptation_records=[],
            data_version="hash-json",
        )
        text = json.dumps(report, ensure_ascii=False)
        self.assertIn("hallucination", text)

    def test_text_summary_renders_and_marks_example_data(self):
        report = build_report(
            cases=[make_real_case(1)],
            knowledge_points=CoverageReportTests.POINTS,
            is_example_data=True,
            data_version="hash-summary",
        )
        text = render_text_summary(report)
        self.assertIn("幻觉率", text)
        self.assertIn("画像-难度适配准确率", text)
        self.assertIn("核心知识点覆盖率", text)
        self.assertIn("测试用例数", text)
        self.assertIn("不能声明达标", text)
        self.assertIn("示例", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
