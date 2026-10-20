"""``scripts/标注/修复题目证据.py`` 的单测。

只测"按偏移把原文切回来、对不上才改"这条逻辑，不读真库：段落缓存与证据索引都在
测试里现造。覆盖六种情形：

* **切得回来**：切片与表里一致 → 一个字不改，记"一致"；
* **同长度被换过字符**：只改证据列，其它列（尤其人判那两列）一格不动；
* **长度不同**：同样只改证据列，理由要与"同长度"分开记，便于人看出是错位还是被吃掉字符；
* **源库里没有这条证据**：**不修**，报出来交人确认——脚本不许替人编原文；
* **`title` 段**：标题不在段落缓存的 ``sections`` 里，要从 ``paper.title`` 取；
* **段落 sha256 对不上／偏移越界／缓存里没这篇**：切不回来，计进"修不了"，退出码非 0。

中文文件名的脚本用 ``importlib`` 按路径加载（与 ``tests/test_风险覆盖率.py`` 同一套办法）。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def load_script(module_name: str, relative_path: str):
    """按文件路径加载中文文件名的脚本，不走 import 语句。"""
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_ROOT / relative_path)
    if spec is None or spec.loader is None:  # pragma: no cover - 路径写错才会走到
        raise RuntimeError(f"加载不了 {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


gen = load_script("生成打分包", "scripts/标注/生成打分包.py")
repair = load_script("修复题目证据", "scripts/标注/修复题目证据.py")

PAPER = "2024.test-1.1"
SECTION = "page-002"
TEXT = "We train the model on DFT data. The ﬁt is good • and stable."
WHERE = (PAPER, SECTION, 0, 20)


def caches_of(text: str = TEXT, *, sha_ok: bool = True) -> tuple[dict, dict]:
    """造一份最小段落缓存与 sha 索引；sha_ok=False 时故意让指纹对不上。"""
    cache = {
        "scientific-ie-kg": {
            PAPER: {"paper": {"title": "A Test Title"}, "sections": {SECTION: text}}
        }
    }
    digest = gen.sha256_of_text(text)
    sha_index = {"scientific-ie-kg": {(PAPER, SECTION): digest if sha_ok else "0" * 64}}
    return cache, sha_index


def write_table(path: Path, rows: list[list[str]]) -> list[str]:
    header = [
        "题目编号",
        "论文标识",
        "页码或段落",
        "字符偏移",
        "证据原文(逐字,勿改)",
        "断言(头实体-关系-尾实体)",
        "系统判定",
        "你的判定(SUPPORTED/UNSUPPORTED/INSUFFICIENT)",
        "证据是否可用(YES/NO)",
    ]
    gen.write_csv(path, header, rows)
    return header


def row_of(case_id: str, evidence: str, offsets: str = "0-20",
           section: str = SECTION, paper: str = PAPER) -> list[str]:
    return [case_id, paper, section, offsets, evidence, "A-USES-B", "accepted",
            "UNSUPPORTED", "YES"]


class 切片测试(unittest.TestCase):
    def test_切得回来(self) -> None:
        cache, sha = caches_of()
        text, reason = repair.slice_row(gen, cache, sha, PAPER, SECTION, 0, 20)
        self.assertEqual(text, TEXT[0:20])
        self.assertIsNone(reason)

    def test_缓存里没有这篇(self) -> None:
        cache, sha = caches_of()
        self.assertEqual(repair.slice_row(gen, cache, sha, "nope", SECTION, 0, 20),
                         (None, repair.REASON_NO_CACHE))

    def test_缓存里没有这一段(self) -> None:
        cache, sha = caches_of()
        self.assertEqual(repair.slice_row(gen, cache, sha, PAPER, "page-999", 0, 20),
                         (None, repair.REASON_NO_SECTION))

    def test_段落指纹对不上(self) -> None:
        cache, sha = caches_of(sha_ok=False)
        self.assertEqual(repair.slice_row(gen, cache, sha, PAPER, SECTION, 0, 20),
                         (None, repair.REASON_SHA))

    def test_偏移越界与空区间(self) -> None:
        cache, sha = caches_of()
        self.assertEqual(repair.slice_row(gen, cache, sha, PAPER, SECTION, 0, 9999)[1],
                         repair.REASON_RANGE)
        self.assertEqual(repair.slice_row(gen, cache, sha, PAPER, SECTION, 5, 5)[1],
                         repair.REASON_RANGE)

    def test_title段从paper里取(self) -> None:
        # title 这种虚拟段落库里没有 sections 行，也就没有 sha 行；不许因此拒修
        cache, sha = caches_of()
        text, reason = repair.slice_row(gen, cache, sha, PAPER, "title", 0, 5)
        self.assertEqual((text, reason), ("A Tes", None))


class 修表测试(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.backup = self.dir / "备份"
        patcher = mock.patch.object(repair, "BACKUP_DIR", self.backup)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def run_repair(self, path: Path, cache: dict, sha: dict, by_offset: dict, apply: bool):
        return repair.repair_file(gen, path, cache, sha, by_offset, apply)

    def test_一致的行一个字不改(self) -> None:
        path = self.dir / "表.csv"
        write_table(path, [row_of("H-001", TEXT[0:20])])
        before = path.read_bytes()
        cache, sha = caches_of()
        report = self.run_repair(path, cache, sha, {WHERE: [TEXT[0:20]]}, apply=True)
        self.assertEqual(report["分类"], {"一致": 1})
        self.assertEqual(report["已修条数"], 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.backup.exists())

    def test_同长度被换过字符只改证据列(self) -> None:
        path = self.dir / "表.csv"
        broken = TEXT[0:20].replace(" ", "?", 1)  # 同长度，字符被换过
        write_table(path, [row_of("H-001", broken)])
        cache, sha = caches_of()
        report = self.run_repair(path, cache, sha, {WHERE: [TEXT[0:20]]}, apply=True)
        self.assertEqual(report["分类"], {repair.REASON_TEXT_DIFFERS: 1})
        self.assertEqual(report["已修条数"], 1)
        header, rows = gen._read_csv_rows(path)
        self.assertEqual(rows[0][header.index("证据原文(逐字,勿改)")], TEXT[0:20])
        # 人判的两列、断言、偏移一格不动
        self.assertEqual(rows[0][header.index("你的判定(SUPPORTED/UNSUPPORTED/INSUFFICIENT)")],
                         "UNSUPPORTED")
        self.assertEqual(rows[0][header.index("证据是否可用(YES/NO)")], "YES")
        self.assertEqual(rows[0][header.index("断言(头实体-关系-尾实体)")], "A-USES-B")
        self.assertEqual(rows[0][header.index("字符偏移")], "0-20")
        # 改之前留了备份
        self.assertTrue((self.backup / "表.csv").exists())

    def test_长度不同按另一类记(self) -> None:
        path = self.dir / "表.csv"
        write_table(path, [row_of("H-002", TEXT[0:15])])
        cache, sha = caches_of()
        report = self.run_repair(path, cache, sha, {WHERE: [TEXT[0:20]]}, apply=False)
        self.assertEqual(report["分类"], {repair.REASON_LENGTH_DIFFERS: 1})
        self.assertEqual(report["已修条数"], 0)  # 没加 apply 就不许写
        _, rows = gen._read_csv_rows(path)
        self.assertEqual(rows[0][4], TEXT[0:15])

    def test_源库没有这条证据就不修(self) -> None:
        path = self.dir / "表.csv"
        broken = TEXT[0:20].replace("model", "mod?l")
        write_table(path, [row_of("H-003", broken)])
        cache, sha = caches_of()
        report = self.run_repair(path, cache, sha, {} , apply=True)
        self.assertEqual(report["修不了条数"], 1)
        self.assertEqual(report["已修条数"], 0)
        self.assertIn(repair.REASON_NOT_IN_DB, report["明细"][0]["原因"])
        _, rows = gen._read_csv_rows(path)
        self.assertEqual(rows[0][4], broken)  # 一个字都不许动

    def test_切不回来的行计进修不了(self) -> None:
        path = self.dir / "表.csv"
        write_table(path, [row_of("H-004", "whatever", offsets="0-9999")])
        cache, sha = caches_of()
        report = self.run_repair(path, cache, sha, {WHERE: [TEXT[0:20]]}, apply=True)
        self.assertEqual(report["修不了条数"], 1)
        self.assertEqual(report["明细"][0]["原因"], repair.REASON_RANGE)

    def test_偏移读不出来(self) -> None:
        path = self.dir / "表.csv"
        write_table(path, [row_of("H-005", "whatever", offsets="不是数字")])
        cache, sha = caches_of()
        report = self.run_repair(path, cache, sha, {}, apply=False)
        self.assertEqual(report["修不了条数"], 1)
        self.assertEqual(report["分类"], {"偏移读不出来": 1})

    def test_没有证据列就报错(self) -> None:
        path = self.dir / "表.csv"
        gen.write_csv(path, ["题目编号", "论文标识"], [["H-006", PAPER]])
        cache, sha = caches_of()
        with self.assertRaises(SystemExit):
            self.run_repair(path, cache, sha, {}, apply=False)


class 命令行测试(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.object(repair, "BACKUP_DIR", self.dir / "备份")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, argv: list[str], sources: tuple[dict, dict, dict]) -> tuple[int, str]:
        """跑一次命令行，把它的打印收进字符串——免得搅乱整套检查的日志。"""
        buffer = io.StringIO()
        with mock.patch.object(repair, "load_sources", return_value=sources):
            with contextlib.redirect_stdout(buffer):
                try:
                    code = repair.main(argv)
                except SystemExit as exit_:
                    self.fail(f"不该退出：{exit_.code}")
        return code, buffer.getvalue()

    def test_全部修好退出码零并写报告(self) -> None:
        out = self.dir / "包"
        write_table(out / repair.CASE_FILES[0], [row_of("H-001", TEXT[0:20].replace("model", "mod?l"))])
        cache, sha = caches_of()
        report_path = self.dir / "报告.json"
        code, printed = self.run_main(
            ["--out", str(out), "--apply", "--report", str(report_path)],
            (cache, sha, {WHERE: [TEXT[0:20]]}),
        )
        self.assertEqual(code, 0)
        self.assertIn("已修   1", printed)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["是否写入"])
        self.assertEqual(payload["文件"][0]["已修条数"], 1)

    def test_有修不了的行退出码一(self) -> None:
        out = self.dir / "包"
        write_table(out / repair.CASE_FILES[0], [row_of("H-001", "x", offsets="0-9999")])
        cache, sha = caches_of()
        code, printed = self.run_main(["--out", str(out)], (cache, sha, {}))
        self.assertEqual(code, 1)
        self.assertIn("修不了 1 条", printed)

    def test_目录里没有题目表就报错(self) -> None:
        out = self.dir / "空目录"
        out.mkdir()
        with self.assertRaises(SystemExit):
            repair.main(["--out", str(out)])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
