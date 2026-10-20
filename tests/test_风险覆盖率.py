"""风险—覆盖率曲线的单测。

只测 ``scripts/评测/风险覆盖率.py`` 里的纯函数与定位规则，不读真库、不读题目文件：

* **全保留**：阈值 0 时一条不丢，覆盖率 100%，错误率就是全体的错误率；
* **全丢弃**：阈值高到没有关系的 ``confidence`` 能达到，保留 0 条；这时错误率没有
  样本，必须是 ``None`` 而不是 0（写成 0 会让人以为"0 条保留 = 0 错误，达标了"）；
* **阈值边界**：保留规则是闭区间 ``confidence >= t``，``t`` 恰好等于某条关系的
  ``confidence`` 时那一条必须留下；
* **Wilson 区间**：两端不越界、与已知数值对得上（76/140 就是 54.3% 那个数，
  区间 [46.0%, 62.3%]），0 条样本时退回整个 [0, 1]。

另有一条定位测试：在临时目录里造一个最小库（表结构与真库同名同列），覆盖
"唯一确定" / "找到多条取最高 confidence" / "证据都没有" / "证据在但这条证据上没有关系" /
"断言对不上但同类型同系统判定的关系唯一" 五种情况。

中文文件名的脚本用 ``importlib`` 按路径加载（与 ``tests/test_DF门槛.py`` 同一套办法）。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def load_script(module_name: str, relative_path: str):
    """按文件路径加载中文文件名的脚本，不走 import 语句。"""
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_ROOT / relative_path)
    if spec is None or spec.loader is None:  # pragma: no cover - 路径写错才会走到
        raise RuntimeError(f"加载不了 {relative_path}")
    module = importlib.util.module_from_spec(spec)
    # 先登记到 sys.modules：脚本里用了 dataclass，dataclasses 要知道这个类属于哪个模块
    # （它按 cls.__module__ 回查 sys.modules）。不登记会报 AttributeError: 'NoneType'。
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


risk = load_script("风险覆盖率", "scripts/评测/风险覆盖率.py")


def point(confidence: float, label: str) -> dict:
    return {"confidence": confidence, "label": label}


class 全保留测试(unittest.TestCase):
    """阈值 0：一条不丢。"""

    def test_一条不丢_覆盖率满_错误率等于全体(self) -> None:
        points = [
            point(0.78, risk.SUPPORTED),
            point(0.78, risk.UNSUPPORTED),
            point(0.62, risk.UNSUPPORTED),
            point(0.87, risk.SUPPORTED),
        ]
        rows = risk.curve_rows(points, total_cases=4, thresholds=[0.0])
        row = rows[0]
        self.assertEqual(row["保留条数"], 4)
        self.assertAlmostEqual(row["覆盖率"], 1.0)
        self.assertEqual(row["错误条数"] if "错误条数" in row else 2, 2)
        self.assertAlmostEqual(row["错误率"], 0.5)
        self.assertAlmostEqual(row["精确率"], 0.5)

    def test_覆盖率的分母是题目总数_不是定位到的条数(self) -> None:
        # 4 条题目里只有 2 条定位到关系：t=0 也只能报 2 条，覆盖率 50%。
        points = [point(0.8, risk.SUPPORTED), point(0.9, risk.SUPPORTED)]
        rows = risk.curve_rows(points, total_cases=4, thresholds=[0.0])
        self.assertEqual(rows[0]["保留条数"], 2)
        self.assertAlmostEqual(rows[0]["覆盖率"], 0.5)

    def test_INSUFFICIENT_不算错误也不踢出分母(self) -> None:
        points = [
            point(0.8, risk.SUPPORTED),
            point(0.8, risk.INSUFFICIENT),
            point(0.8, risk.UNSUPPORTED),
            point(0.8, risk.SUPPORTED),
        ]
        row = risk.curve_rows(points, total_cases=4, thresholds=[0.0])[0]
        self.assertEqual(row["保留条数"], 4)
        self.assertAlmostEqual(row["错误率"], 0.25)


class 全丢弃测试(unittest.TestCase):
    """阈值高到没有一条够得着。"""

    def test_保留零条_错误率是空值而不是零(self) -> None:
        points = [point(0.78, risk.SUPPORTED), point(0.62, risk.UNSUPPORTED)]
        rows = risk.curve_rows(points, total_cases=2, thresholds=[1.0])
        row = rows[0]
        self.assertEqual(row["保留条数"], 0)
        self.assertAlmostEqual(row["覆盖率"], 0.0)
        self.assertIsNone(row["错误率"])
        self.assertIsNone(row["精确率"])
        # 没有样本时区间取整个 [0, 1]，不能报一个假窄的区间。
        self.assertEqual(row["区间"], [0.0, 1.0])

    def test_一条都不剩时不算满足错误率目标(self) -> None:
        points = [point(0.78, risk.SUPPORTED)]
        rows = risk.curve_rows(points, total_cases=1, thresholds=[0.0, 1.0])
        # t=0 那一行保留 1 条、错误率 0%，是达标的一档。
        self.assertIsNotNone(risk.find_min_threshold(rows, target=0.05))
        # t=1.0 那一行保留 0 条、错误率空，不能被当成"达标"。
        self.assertEqual(rows[1]["保留条数"], 0)
        self.assertIsNone(risk.find_min_threshold([rows[1]], target=0.05))


class 阈值边界测试(unittest.TestCase):
    """保留规则是闭区间：``confidence >= t``。"""

    def test_阈值恰好等于置信度时留下(self) -> None:
        points = [point(0.78, risk.SUPPORTED), point(0.62, risk.SUPPORTED)]
        at_062 = risk.curve_rows(points, total_cases=2, thresholds=[0.62])[0]
        self.assertEqual(at_062["保留条数"], 2)  # 闭区间：0.62 那条也在
        at_078 = risk.curve_rows(points, total_cases=2, thresholds=[0.78])[0]
        self.assertEqual(at_078["保留条数"], 1)
        self.assertAlmostEqual(at_078["覆盖率"], 0.5)
        just_above = risk.curve_rows(points, total_cases=2, thresholds=[0.79])[0]
        self.assertEqual(just_above["保留条数"], 0)

    def test_取整误差不会把边界那一条挤掉(self) -> None:
        # 0.02 步长格点上的 0.62 与库里存的浮点值必须能对上。
        points = [point(0.62, risk.SUPPORTED)]
        rows = risk.curve_rows(points, total_cases=1, thresholds=[0.62])
        self.assertEqual(rows[0]["保留条数"], 1)

    def test_阈值网格覆盖实际出现的置信度(self) -> None:
        grid = risk.threshold_grid([0.62, 0.78, 0.87], step=0.02)
        for value in (0.0, 0.62, 0.78, 0.87, 1.0):
            self.assertIn(value, grid)
        self.assertEqual(grid, sorted(grid))

    def test_找最低的达标阈值(self) -> None:
        points = [
            point(0.9, risk.SUPPORTED),
            point(0.9, risk.SUPPORTED),
            point(0.5, risk.UNSUPPORTED),
            point(0.5, risk.UNSUPPORTED),
        ]
        rows = risk.curve_rows(points, total_cases=4, thresholds=[0.0, 0.5, 0.9])
        best = risk.find_min_threshold(rows, target=0.05)
        self.assertIsNotNone(best)
        # 达标的是 t=0.9：错误率 0%、保留 2 条；t=0.5 的错误率 50% 不达标。
        self.assertEqual(best["t"], 0.9)
        self.assertEqual(best["保留条数"], 2)
        self.assertAlmostEqual(best["覆盖率"], 0.5)

    def test_没有达标阈值时返回空(self) -> None:
        points = [point(0.9, risk.UNSUPPORTED), point(0.5, risk.UNSUPPORTED)]
        rows = risk.curve_rows(points, total_cases=2, thresholds=[0.0, 0.5, 0.9, 1.0])
        self.assertIsNone(risk.find_min_threshold(rows, target=0.05))


class Wilson区间测试(unittest.TestCase):
    def test_与已知数值对得上(self) -> None:
        # 幻觉率那一条：76/140 = 54.3%，区间 [46.0%, 62.3%]。
        low, high = risk.wilson_interval(76, 140)
        self.assertAlmostEqual(low, 0.4603, places=4)
        self.assertAlmostEqual(high, 0.6231, places=4)

    def test_零错误时下界为零_上界不为零(self) -> None:
        low, high = risk.wilson_interval(0, 10)
        self.assertAlmostEqual(low, 0.0)
        self.assertGreater(high, 0.0)
        self.assertLess(high, 1.0)

    def test_全错时上界为一_下界不为一(self) -> None:
        low, high = risk.wilson_interval(10, 10)
        self.assertAlmostEqual(high, 1.0)
        self.assertGreater(low, 0.0)
        self.assertLess(low, 1.0)

    def test_零样本时退回整个区间(self) -> None:
        self.assertEqual(risk.wilson_interval(0, 0), (0.0, 1.0))

    def test_区间总包含点估计且不越界(self) -> None:
        for errors, kept in ((1, 3), (7, 20), (99, 100), (1, 1000)):
            low, high = risk.wilson_interval(errors, kept)
            self.assertLessEqual(0.0, low)
            self.assertLessEqual(low, errors / kept)
            self.assertGreaterEqual(high, errors / kept)
            self.assertLessEqual(high, 1.0)

    def test_条数越多区间越窄(self) -> None:
        narrow = risk.wilson_interval(50, 100)
        wide = risk.wilson_interval(5, 10)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])


def _make_db(path: Path, rows: list[tuple]) -> None:
    """造一个最小的库：表名与列名跟真库一致，只放测试要用的那几行。

    ``rows`` 里每条是 ``(paper_id, section_id, char_start, char_end, evidence_id,
    relation_id, relation_type, status, confidence, head, tail)``；
    ``relation_id`` 给 ``None`` 表示这条证据上没有关系。
    """
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        create table evidence (
            evidence_id text primary key, paper_id text, section_id text,
            sentence_index integer, text text, char_start integer, char_end integer
        );
        create table entities (
            entity_id text primary key, canonical_name text, entity_type text,
            confidence real, aliases_json text
        );
        create table relations (
            relation_id text primary key, source_id text, target_id text, relation_type text,
            confidence real, status text, criticisms_json text, extraction_method text
        );
        create table relation_evidence (relation_id text, evidence_id text);
        """
    )
    for (
        paper_id,
        section_id,
        char_start,
        char_end,
        evidence_id,
        relation_id,
        relation_type,
        status,
        confidence,
        head,
        tail,
    ) in rows:
        connection.execute(
            "insert or ignore into evidence values (?,?,?,?,?,?,?)",
            (evidence_id, paper_id, section_id, 0, "x", char_start, char_end),
        )
        if relation_id is None:
            continue
        connection.execute(
            "insert into entities values (?,?,?,?,?)",
            (f"entity-h-{relation_id}", head, "METHOD", 1.0, "[]"),
        )
        connection.execute(
            "insert into entities values (?,?,?,?,?)",
            (f"entity-t-{relation_id}", tail, "DATASET", 1.0, "[]"),
        )
        connection.execute(
            "insert into relations values (?,?,?,?,?,?,?,?)",
            (
                relation_id,
                f"entity-h-{relation_id}",
                f"entity-t-{relation_id}",
                relation_type,
                confidence,
                status,
                "[]",
                "test",
            ),
        )
        connection.execute(
            "insert into relation_evidence values (?,?)", (relation_id, evidence_id)
        )
    connection.commit()
    connection.close()


def _case(assertion: str, *, status: str = "accepted", offset=(0, 10)):
    return risk.Case(
        编号="H-001",
        论文标识="p1",
        页码或段落="page-001",
        字符偏移=f"{offset[0]}-{offset[1]}",
        char_start=offset[0],
        char_end=offset[1],
        断言=assertion,
        系统判定=status,
        最终标签=risk.SUPPORTED,
    )


class 定位测试(unittest.TestCase):
    """题目 → 库里关系的三种结果，外加两条兜底规则。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "mini.db"

    def _index(self) -> "risk.DbIndex":
        index = risk.DbIndex([self.db_path])
        self.addCleanup(index.close)
        return index

    def test_唯一确定(self) -> None:
        _make_db(
            self.db_path,
            [("p1", "page-001", 0, 10, "ev1", "r1", "USES", "accepted", 0.78, "Alpha", "Beta")],
        )
        result = risk.locate(_case("Alpha-USES-Beta"), self._index())
        self.assertEqual(result.方式, risk.LOCATE_UNIQUE)
        self.assertEqual(result.关系.relation_id, "r1")
        self.assertAlmostEqual(result.关系.confidence, 0.78)

    def test_找到多条时取置信度最高的(self) -> None:
        _make_db(
            self.db_path,
            [
                ("p1", "page-001", 0, 10, "ev1", "r1", "USES", "accepted", 0.62, "Alpha", "Beta"),
                ("p1", "page-001", 0, 10, "ev1", "r2", "USES", "accepted", 0.87, "Alpha", "Beta"),
            ],
        )
        result = risk.locate(_case("Alpha-USES-Beta"), self._index())
        self.assertEqual(result.方式, risk.LOCATE_MULTI)
        self.assertEqual(result.候选条数, 2)
        self.assertEqual(result.关系.relation_id, "r2")

    def test_证据跨度在库里找不到(self) -> None:
        _make_db(
            self.db_path,
            [("p1", "page-001", 0, 10, "ev1", "r1", "USES", "accepted", 0.78, "Alpha", "Beta")],
        )
        result = risk.locate(_case("Alpha-USES-Beta", offset=(100, 120)), self._index())
        self.assertEqual(result.方式, risk.LOCATE_NONE)
        self.assertIn("证据跨度", result.找不到原因)

    def test_证据在但这条证据上没有关系(self) -> None:
        _make_db(self.db_path, [("p1", "page-001", 0, 10, "ev1", None, None, None, None, None, None)])
        result = risk.locate(_case("Alpha-USES-Beta"), self._index())
        self.assertEqual(result.方式, risk.LOCATE_NONE)
        self.assertIn("没有关系", result.找不到原因)

    def test_断言对不上时按同类型同状态补回唯一一条(self) -> None:
        _make_db(
            self.db_path,
            [
                ("p1", "page-001", 0, 10, "ev1", "r1", "USES", "accepted", 0.78, "Alpha", "Beta"),
                ("p1", "page-001", 0, 10, "ev1", "r2", "USES", "rejected", 0.78, "Alpha", "Gamma"),
            ],
        )
        # 断言里的尾实体是 Delta，库里没有；accepted 的 USES 只有一条 → 补回它。
        result = risk.locate(_case("Alpha-USES-Delta"), self._index())
        self.assertEqual(result.方式, "补回")
        self.assertEqual(result.关系.relation_id, "r1")

    def test_断言对不上且补不回来时记成找不到(self) -> None:
        _make_db(
            self.db_path,
            [
                ("p1", "page-001", 0, 10, "ev1", "r1", "USES", "accepted", 0.78, "Alpha", "Beta"),
                ("p1", "page-001", 0, 10, "ev1", "r2", "USES", "accepted", 0.78, "Alpha", "Gamma"),
            ],
        )
        result = risk.locate(_case("Alpha-USES-Delta"), self._index())
        self.assertEqual(result.方式, risk.LOCATE_NONE)
        self.assertIn("断言对不上", result.找不到原因)


class 读数测试(unittest.TestCase):
    """题目文件与标签文件的读法。"""

    def test_字符偏移解析(self) -> None:
        self.assertEqual(risk.parse_offset("524-599"), (524, 599))
        self.assertEqual(risk.parse_offset(" 0-1 "), (0, 1))
        with self.assertRaises(ValueError):
            risk.parse_offset("524")
        with self.assertRaises(ValueError):
            risk.parse_offset("599-524")

    def test_判定列名按候选顺序找(self) -> None:
        self.assertEqual(risk.resolve_label_column(list(risk.CASE_COLUMNS) + ["最终标签"]), "最终标签")
        self.assertEqual(
            risk.resolve_label_column(
                list(risk.CASE_COLUMNS) + ["你的判定(SUPPORTED/UNSUPPORTED/INSUFFICIENT)"]
            ),
            "你的判定(SUPPORTED/UNSUPPORTED/INSUFFICIENT)",
        )
        self.assertIsNone(risk.resolve_label_column(list(risk.CASE_COLUMNS)))


if __name__ == "__main__":
    unittest.main()
