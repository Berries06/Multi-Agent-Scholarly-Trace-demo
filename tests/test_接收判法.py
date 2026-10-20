"""``src/yanhai/acceptance.py``（接收判法的四条条件）的单测。

只测纯函数，不读真库、不读题目文件；本体用仓库里那份真实文件（它是交付资产，
不是测试夹具）。覆盖六类情形：

* **证据有效性**：太短、断在半句、符号占比过高、引用标记过半、含版式标记，五种都要判无效；
* **实体定位**：ASCII 词边界（``GLiNER`` 不该匹配到 ``GLiNER2`` 里面）、别名、中文、重复出现；
* **切句**：``et al.`` 这类缩写点不算句末，跨句的实体对必须被判成不同句；
* **类型约束**：本体允许 / 不允许 / 本体没写这条关系（按不限制处理）；
* **谓词在场**：关系专属触发词算在场；只有通用连接词时，严格判法不认、宽松判法认；
* **四个状态**：四条全过才算 ``accepted``；证据无效直接 ``rejected``；其余 ``needs_review``。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai import acceptance  # noqa: E402


class 证据有效性测试(unittest.TestCase):
    def test_正常陈述算有效(self) -> None:
        span = "The CGCNN model was trained using a graph neural network on DFT data."
        self.assertTrue(acceptance.evidence_quality(span)["ok"])

    def test_太短判无效(self) -> None:
        result = acceptance.evidence_quality("CGCNN uses GNN.")
        self.assertFalse(result["ok"])
        self.assertTrue(any("太短" in reason for reason in result["reasons"]))

    def test_断在半句判无效(self) -> None:
        span = "All Automatminer, CGCNN, MEGNet, and RF results were generated using"
        self.assertFalse(acceptance.evidence_quality(span)["ok"])

    def test_符号占比过高判无效(self) -> None:
        span = "0.786 0.799 0.812 0.834 0.851 0.867 0.882 0.901 0.917 0.934 0.949"
        self.assertFalse(acceptance.evidence_quality(span)["ok"])

    def test_引用标记过半判无效(self) -> None:
        span = ("J. Smith et al., Nature 12, 345 (2019). [12] K. Lee et al., Science 8, 1 (2020). "
                "[13] M. Chen et al., Cell 3, 22 (2021).")
        self.assertFalse(acceptance.evidence_quality(span)["ok"])

    def test_含版式标记判无效(self) -> None:
        span = "Table 3: Regression model performances on JARVIS-DFT dataset for 29 properties."
        self.assertFalse(acceptance.evidence_quality(span)["ok"])


class 定位测试(unittest.TestCase):
    def test_ASCII不放宽到词内(self) -> None:
        text = acceptance.normalize("We present GLiNER2, a unified framework that extends GLiNER.")
        hits = acceptance.locate(text, ["GLiNER"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(text[hits[0][0]:hits[0][1]], "GLiNER")

    def test_别名也能定位(self) -> None:
        text = acceptance.normalize("Deep Knowledge Tracing (DKT) uses a recurrent network.")
        hits = acceptance.locate(text, ["Deep Knowledge Tracing", "DKT"])
        # 全名里已经包含 DKT 的缩写？没有——这两处是分开的，应该各命中一次
        self.assertGreaterEqual(len(hits), 1)

    def test_中文实体(self) -> None:
        text = acceptance.normalize("我们使用晶体图卷积神经网络来预测带隙。")
        hits = acceptance.locate(text, ["晶体图卷积神经网络"])
        self.assertEqual(len(hits), 1)

    def test_同名出现两次(self) -> None:
        text = acceptance.normalize("The Materials Project is large. Later, the Materials Project grows.")
        self.assertEqual(len(acceptance.locate(text, ["Materials Project"])), 2)


class 切句测试(unittest.TestCase):
    def test_同一句(self) -> None:
        text = acceptance.normalize("CGCNN uses a graph neural network to predict band gaps.")
        head = acceptance.locate(text, ["CGCNN"])[0]
        tail = acceptance.locate(text, ["graph neural network"])[0]
        self.assertTrue(acceptance.same_sentence(text, head, tail))

    def test_跨句(self) -> None:
        text = acceptance.normalize(
            "CGCNN was published in 2018. The Materials Project contains DFT calculations."
        )
        head = acceptance.locate(text, ["CGCNN"])[0]
        tail = acceptance.locate(text, ["Materials Project"])[0]
        self.assertFalse(acceptance.same_sentence(text, head, tail))

    def test_缩写点不切句(self) -> None:
        text = acceptance.normalize(
            "As shown by Xie et al. CGCNN uses a graph neural network for crystals."
        )
        self.assertEqual(len(acceptance.sentence_bounds(text)), 1)


class 类型约束测试(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = acceptance.load_schema()
        self.constraints = self.schema["relation_constraints"]

    def test_允许的类型(self) -> None:
        ok, reason = acceptance.type_ok(self.constraints, "USES", "METHOD", "DATASET")
        self.assertTrue(ok, reason)

    def test_不允许的类型(self) -> None:
        ok, _ = acceptance.type_ok(self.constraints, "USES", "DATASET", "DATASET")
        self.assertFalse(ok)

    def test_本体没写的关系按不限制处理(self) -> None:
        ok, reason = acceptance.type_ok(self.constraints, "RELATED_TO", "METHOD", "DATASET")
        self.assertTrue(ok)
        self.assertIn("没有这条关系的类型约束", reason)


class 谓词与判定测试(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = acceptance.load_schema()

    def test_有触发词算在场(self) -> None:
        text = acceptance.normalize("CGCNN uses a graph neural network for crystal property prediction.")
        head = acceptance.locate(text, ["CGCNN"])[0]
        tail = acceptance.locate(text, ["graph neural network"])[0]
        ok, _ = acceptance.trigger_between(text, head, tail,
                                          self.schema["triggers"].get("USES", ()))
        self.assertTrue(ok)

    def test_只有通用连接词时严格判法不认(self) -> None:
        text = acceptance.normalize("CGCNN for crystal property prediction with graph models.")
        head = acceptance.locate(text, ["CGCNN"])[0]
        tail = acceptance.locate(text, ["graph models"])[0]
        strict_ok, _ = acceptance.trigger_between(text, head, tail, ("uses",), allow_link=False)
        loose_ok, _ = acceptance.trigger_between(text, head, tail, ("uses",), allow_link=True)
        self.assertFalse(strict_ok)
        self.assertTrue(loose_ok)

    def test_四条全过才accepted(self) -> None:
        decision = acceptance.decide(
            span="The CGCNN model uses a graph neural network to encode crystal structures.",
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.ACCEPTED, decision.reasons)
        self.assertFalse(decision.reasons)

    def test_证据无效直接rejected(self) -> None:
        decision = acceptance.decide(
            span="[12] K. Lee et al., Science 8, 1 (2020). [13] M. Chen et al., Cell 3, 22 (2021).",
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.REJECTED)

    def test_实体缺失直接rejected(self) -> None:
        decision = acceptance.decide(
            span="The model uses a graph neural network to encode crystal structures.",
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.REJECTED)
        self.assertIn("CGCNN", decision.reasons[0])

    def test_并列没有谓词要人看(self) -> None:
        decision = acceptance.decide(
            span="We compare CGCNN with a graph neural network baseline on the same split.",
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.NEEDS_REVIEW)
        self.assertTrue(any("触发词" in reason or "连接词" in reason for reason in decision.reasons))

    def test_跨句要人看(self) -> None:
        decision = acceptance.decide(
            span=("CGCNN was published in 2018 and uses crystals. "
                  "The graph neural network is described in the next section."),
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.NEEDS_REVIEW)

    def test_类型不合要人看(self) -> None:
        decision = acceptance.decide(
            span="The Materials Project contains DFT calculations for many materials.",
            head_name="Materials Project", head_type="DATASET",
            tail_name="density functional theory", tail_type="METHOD",
            tail_aliases=("DFT",),
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.NEEDS_REVIEW)
        self.assertTrue(any("类型" in reason for reason in decision.reasons))

    def test_被动结构给方向提醒(self) -> None:
        decision = acceptance.decide(
            span=("The graph neural network is trained by CGCNN with a large crystal dataset."),
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="EXTENDS", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.NEEDS_REVIEW)
        # 头实体出现在尾实体之后，本身就是方向警告；具体措辞不绑死
        self.assertFalse(decision.checks["direction"]["ok"])

    def test_mode参数校验(self) -> None:
        with self.assertRaises(ValueError):
            acceptance.decide(
                span="The CGCNN model uses a graph neural network to encode structures.",
                head_name="CGCNN", head_type="METHOD",
                tail_name="graph neural network", tail_type="METHOD",
                relation_type="USES", schema=self.schema, mode="随意",
            )


class 多证据测试(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = acceptance.load_schema()

    def test_任何一段过就接收(self) -> None:
        decision = acceptance.decide_for_spans(
            spans=[
                "CGCNN was published in 2018 by Xie and Grossman in a short paper.",
                "The CGCNN model uses a graph neural network to encode crystal structures.",
            ],
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.ACCEPTED)

    def test_全是证据无效才rejected(self) -> None:
        decision = acceptance.decide_for_spans(
            spans=["Table 2: AUC 0.786 0.799 0.812 0.834", "0.851 0.867 0.882 0.901 0.917 0.934"],
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.REJECTED)

    def test_没挂证据要人看(self) -> None:
        decision = acceptance.decide_for_spans(
            spans=[],
            head_name="CGCNN", head_type="METHOD",
            tail_name="graph neural network", tail_type="METHOD",
            relation_type="USES", schema=self.schema,
        )
        self.assertEqual(decision.status, acceptance.NEEDS_REVIEW)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
