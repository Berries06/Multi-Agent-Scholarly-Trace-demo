"""DF 门槛的三条规则：``--min-df``、文件名跟着门槛走、门槛越高集合越小。

覆盖三处：

* ``scripts/抽取/生成抽取词表.py`` 的 ``--min-df`` 与输出文件名
  ``<domain_id>_抽取词表_DF<min_df>.json``；
* ``scripts/抽取/构建全文知识库.py`` 的 ``--vocabulary-min-df`` 怎么把档位拼进词表路径；
* ``scripts/评测/DF门槛对照.py`` 的实体跨论文统计与边际收益（纯函数，不读真库）。

中文文件名的脚本用 ``importlib`` 按路径加载（与 ``tests/test_密度对照.py`` 同一套办法）。
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

ENTITY_TYPES = {"METHOD", "TASK", "DATASET", "METRIC", "FINDING", "LIMITATION", "DOMAIN"}


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
build = load_script("构建全文知识库", "scripts/抽取/构建全文知识库.py")
df_table = load_script("DF门槛对照", "scripts/评测/DF门槛对照.py")


def candidate(canonical: str, df: int, *, guess: str = "METHOD") -> dict:
    return {
        "canonical": canonical,
        "document_frequency": df,
        "guess_type": guess,
        "surface_forms": [canonical, canonical.upper()],
        "source_kind": "后缀短语",
    }


#: 五档门槛各会多放进来一条，用来核对包含关系。
CANDIDATES = [
    candidate("graph neural network", 2),
    candidate("knowledge graph embedding", 3),
    candidate("materials graph network", 5),
    candidate("crystal structure prediction", 10),
    candidate("interatomic potential fitting", 20),
]


class MinDfArgTest(unittest.TestCase):
    """``--min-df`` 与输出文件名。"""

    def _run(self, arguments: list[str]) -> tuple[Path, dict, dict]:
        with tempfile.TemporaryDirectory() as raw:
            vocab_dir = Path(raw)
            source = {
                "domain_id": "示例",
                "status": "candidate_pending_human_review",
                "candidates": CANDIDATES,
                "definitions_found": {},
            }
            (vocab_dir / "示例_候选概念.json").write_text(
                json.dumps(source, ensure_ascii=False), encoding="utf-8"
            )
            buffer = io.StringIO()
            with mock.patch.object(wordlist, "VOCAB_DIR", vocab_dir), mock.patch.object(
                sys, "argv", ["生成抽取词表.py", *arguments]
            ), redirect_stdout(buffer):
                wordlist.main()
            summary = json.loads(buffer.getvalue())
            files = sorted(path.name for path in vocab_dir.glob("示例_抽取词表_DF*.json"))
            self.assertEqual(1, len(files))
            payload = json.loads(
                (vocab_dir / files[0]).read_text(encoding="utf-8")
            )
            return vocab_dir / files[0], payload, summary

    def test_default_is_df3(self) -> None:
        """不给参数时就是 DF3：文件名与筛选都按 3，与改动前的行为一致。"""
        path, payload, summary = self._run([])
        self.assertEqual("示例_抽取词表_DF3.json", path.name)
        self.assertEqual(3, summary["min_df"])
        self.assertEqual(">= 3", payload["filter"]["rule"])
        self.assertEqual(
            ["knowledge graph embedding", "materials graph network",
             "crystal structure prediction", "interatomic potential fitting"],
            [item["canonical"] for item in payload["concepts"]],
        )

    def test_explicit_min_df_goes_into_the_filename(self) -> None:
        for min_df in (2, 5, 10, 20):
            with self.subTest(min_df=min_df):
                path, payload, summary = self._run(["--min-df", str(min_df)])
                self.assertEqual(f"示例_抽取词表_DF{min_df}.json", path.name)
                self.assertEqual(min_df, summary["min_df"])
                self.assertEqual(f">= {min_df}", payload["filter"]["rule"])
                self.assertEqual(
                    [item["canonical"] for item in payload["concepts"]],
                    [
                        item["canonical"]
                        for item in CANDIDATES
                        if item["document_frequency"] >= min_df
                    ],
                )

    def test_default_and_explicit_three_are_identical(self) -> None:
        """``--min-df 3`` 与不给参数必须逐字相同（默认值就是 3）。

        `source` 那一项写的是候选文件路径，两次跑在两个临时目录里，必然不同，
        比的时候把它去掉；其余每一项都要一样。
        """
        default_path, default_payload, _ = self._run([])
        explicit_path, explicit_payload, _ = self._run(["--min-df", "3"])
        self.assertEqual(default_path.name, explicit_path.name)
        strip = lambda payload: {  # noqa: E731 - 一行够用
            key: value for key, value in payload.items() if key != "source"
        }
        self.assertEqual(strip(default_payload), strip(explicit_payload))

    def test_zero_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            vocab_dir = Path(raw)
            (vocab_dir / "示例_候选概念.json").write_text(
                json.dumps({"domain_id": "示例", "candidates": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(wordlist, "VOCAB_DIR", vocab_dir), mock.patch.object(
                sys, "argv", ["生成抽取词表.py", "--min-df", "0"]
            ), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    wordlist.main()

    def test_higher_threshold_is_a_subset(self) -> None:
        """门槛越高，留下来的 canonical 只会更少，不会多出来。"""
        sets: dict[int, set[str]] = {}
        for min_df in (2, 3, 5, 10, 20):
            _, payload, _ = self._run(["--min-df", str(min_df)])
            sets[min_df] = {item["canonical"] for item in payload["concepts"]}
        tiers = sorted(sets)
        for lower, higher in zip(tiers, tiers[1:]):
            with self.subTest(lower=lower, higher=higher):
                self.assertTrue(
                    sets[higher] <= sets[lower],
                    f"DF{higher} 里出现了 DF{lower} 没有的概念：{sets[higher] - sets[lower]}",
                )


class VocabularyMinDfTest(unittest.TestCase):
    """建库脚本按档取词表路径。"""

    def test_default_path_is_df3(self) -> None:
        path = build.domain_vocabulary_path("scientific-ie-kg")
        self.assertEqual(
            "data/knowledge/domain_vocabulary/scientific-ie-kg_抽取词表_DF3.json",
            str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        )

    def test_each_tier_points_at_its_own_file(self) -> None:
        for min_df in (2, 5, 10, 20):
            with self.subTest(min_df=min_df):
                path = build.domain_vocabulary_path("quantum-computing", min_df=min_df)
                self.assertEqual(
                    f"quantum-computing_抽取词表_DF{min_df}.json", path.name
                )

    def test_per_domain_paths_follow_the_tier(self) -> None:
        present, missing = build.per_domain_vocabulary_paths(
            ["scientific-ie-kg", "没有这个领域"], min_df=20
        )
        self.assertEqual(
            "scientific-ie-kg_抽取词表_DF20.json", present["scientific-ie-kg"].name
        )
        self.assertIn("DF20.json", missing["没有这个领域"])

    def test_missing_tier_is_reported_not_guessed(self) -> None:
        """没有的那一档不许悄悄退回 DF3：报"该领域没有词表"才是对的。"""
        _, stats = build.build_per_domain_extractors(
            json.loads(
                (PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json").read_text(
                    encoding="utf-8"
                )
            ),
            ["scientific-ie-kg"],
            vocabulary_min_df=7,
        )
        block = stats["domains"]["scientific-ie-kg"]
        self.assertEqual(7, block["vocabulary_min_df"])
        self.assertEqual(0, block["concepts"])
        self.assertIn("该领域没有词表", block["reason"])


class EntityDocumentFrequencyTest(unittest.TestCase):
    """实体跨论文统计：判据里"有效实体"这一列。"""

    def test_median_mean_and_shares(self) -> None:
        stats = df_table.entity_df_stats(
            {
                "a": {"p1"},
                "b": {"p1", "p2"},
                "c": {"p1", "p2", "p3"},
                "d": {"p1", "p2", "p3", "p4", "p5"},
                "e": set(),
            }
        )
        self.assertEqual(5, stats["entity_count"])
        self.assertEqual(2, stats["median_papers"])
        self.assertEqual(2.2, stats["mean_papers"])
        self.assertEqual(5, stats["max_papers"])
        self.assertEqual(0.6, stats["share_ge2"])
        self.assertEqual(0.4, stats["share_ge3"])
        self.assertEqual(0.2, stats["share_ge5"])
        self.assertEqual(1, stats["count_only_one_paper"])

    def test_empty_is_zero_not_crash(self) -> None:
        stats = df_table.entity_df_stats({})
        self.assertEqual(0, stats["entity_count"])
        self.assertEqual(0, stats["share_ge2"])

    def test_marginal_counts_only_reproduced_entities_as_effective(self) -> None:
        stricter = {
            "arm": "df20",
            "min_df": 20,
            "scale": {"papers": 10},
            "_entity_papers": {"shared": {"p1", "p2"}},
            "_relation_ids": {"r1"},
            "_entity_names": {"shared": "shared"},
        }
        looser = {
            "arm": "df10",
            "min_df": 10,
            "scale": {"papers": 10},
            "_entity_papers": {
                "shared": {"p1", "p2"},
                "new_once": {"p3"},
                "new_twice": {"p4", "p5"},
            },
            "_relation_ids": {"r1", "r2", "r3"},
            "_entity_names": {"new_once": "new once", "new_twice": "new twice"},
        }
        block = df_table.marginal_block(stricter, looser)
        self.assertEqual(2, block["new_entities"])
        self.assertEqual(2, block["new_relations"])
        self.assertEqual(1, block["new_entities_reproduced_ge2"])
        self.assertEqual(0.5, block["new_effective_share"])
        self.assertEqual(0.1, block["new_effective_entities_per_paper"])
        self.assertEqual(
            [{"canonical": "new twice", "papers": 2}], block["examples"]
        )

    def test_arm_table_lists_the_same_tiers(self) -> None:
        """五档的档位名与 min_df 对得上，顺序由严到宽。"""
        self.assertEqual(
            ["df20", "df10", "df5", "df3r", "df2"], list(df_table.DEFAULT_ARMS)
        )
        self.assertEqual(
            [20, 10, 5, 3, 2],
            [df_table.ARM_MIN_DF[arm] for arm in df_table.DEFAULT_ARMS],
        )


if __name__ == "__main__":
    unittest.main()
