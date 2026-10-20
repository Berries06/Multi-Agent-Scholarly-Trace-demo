"""测试用的语料清单读取工具：把"语料里有多少篇"从清单现场读出来。

为什么要有这个文件
------------------
扩语料是常态（`scripts/语料/收集开放全文.py` 会持续往五个 `manifest.json` 追加论文），
所以测试里不该再出现"总数 333""主领域 49 篇""metadata_only 41 条"这类写死的数字。
数字一写死，每扩一次语料都要手改一遍，改到最后没人知道哪个数字是对的。

这里只做三件事：
1. 按 `data/vertical_kb/registry.json` 把五个领域的 `manifest.json` 读出来；
2. 把 `display/data.json`（导出给网页看的文件）读出来；
3. 提供"清单与导出文件逐条对齐"的公用检查。

真正的判断（哪条记录该不该进关系图、档位怎么分）仍留在各个测试里。
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERTICAL_KB_ROOT = PROJECT_ROOT / "data" / "vertical_kb"
REGISTRY_PATH = VERTICAL_KB_ROOT / "registry.json"
DISPLAY_DATA_PATH = PROJECT_ROOT / "display" / "data.json"

_MANIFEST_CACHE: dict[str, dict[str, Any]] = {}
_MANIFEST_BYTES: dict[str, bytes] = {}
_DISPLAY_CACHE: dict[str, Any] | None = None


def load_registry() -> dict[str, Any]:
    """读领域注册表：领域的 id、目录与显示名都在这里，别在测试里另抄一份。"""
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def domain_ids() -> list[str]:
    return [str(item["domain_id"]) for item in load_registry()["domains"]]


def manifest_path(domain_id: str) -> Path:
    """主领域清单在 `data/vertical_kb/manifest.json`，其余四个在 `domains/<id>/` 下。

    路径以注册表的 `path` 字段为准（与 `KnowledgeBase` 的解析方式一致），
    免得测试自己拼目录。
    """
    for item in load_registry()["domains"]:
        if str(item["domain_id"]) == domain_id:
            return VERTICAL_KB_ROOT / str(item.get("path", ".")) / "manifest.json"
    raise KeyError(f"注册表里没有领域 {domain_id}")


def load_manifest(domain_id: str) -> dict[str, Any]:
    """读某个领域的清单（每个测试进程只读一次），并核对清单自报的 `domain_id`。"""
    if domain_id not in _MANIFEST_CACHE:
        path = manifest_path(domain_id)
        raw = path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
        declared = manifest.get("domain_id")
        if declared != domain_id:
            raise AssertionError(
                f"{path} 里的 domain_id={declared!r} 与注册表里的 {domain_id!r} 不一致"
            )
        manifest["_manifest_path"] = str(path)
        _MANIFEST_CACHE[domain_id] = manifest
        _MANIFEST_BYTES[domain_id] = raw
    return _MANIFEST_CACHE[domain_id]


def load_all() -> dict[str, dict[str, Any]]:
    """一次把五个领域的清单读进缓存，作为这一轮测试的固定快照。

    `scripts/语料/收集开放全文.py` 正在往这些文件追加论文，所以每个测试进程
    只在开头读一遍：分几次读会拿到不同时间的数字，断言之间会自相矛盾。
    """
    return {domain_id: load_manifest(domain_id) for domain_id in domain_ids()}


def manifest_bytes(domain_id: str) -> bytes:
    """这份快照的原始字节，用来让语料对象读到与断言完全相同的一份清单。"""
    load_manifest(domain_id)
    return _MANIFEST_BYTES[domain_id]


@contextlib.contextmanager
def frozen_manifests(domain_ids: list[str]) -> Iterator[None]:
    """在块内让语料对象读到缓存里的那份清单字节。

    采集脚本是另一个进程，正在改磁盘上的 `manifest.json`。测试如果先读清单做断言、
    再让 `KnowledgeBase` 自己读一遍文件，两次之间被追加了几篇，就会出现
    "清单 159 条、语料 160 条"这种自相矛盾的失败。这块把磁盘读取换成同一份快照，
    比较的两边就是同一批数据；块外的读取不受影响。
    """
    frozen = {
        manifest_path(domain_id).resolve(): manifest_bytes(domain_id)
        for domain_id in domain_ids
    }
    original = Path.read_bytes

    def read_bytes(self: Path) -> bytes:  # type: ignore[override]
        data = frozen.get(self.resolve())
        return data if data is not None else original(self)

    Path.read_bytes = read_bytes  # type: ignore[method-assign]
    try:
        yield
    finally:
        Path.read_bytes = original  # type: ignore[method-assign]


def records(domain_id: str) -> list[dict[str, Any]]:
    """某个领域的全部题录记录（清单 `papers` 数组），保持清单里的顺序。"""
    return list(load_manifest(domain_id).get("papers", []))


def record_ids(domain_id: str) -> list[str]:
    return [str(record["paper_id"]) for record in records(domain_id)]


def tier_counts(domain_id: str) -> dict[str, int]:
    """按 `evidence_tier` 数一遍：evidence_card / full_text / metadata_only 各多少条。"""
    counts: dict[str, int] = {}
    for record in records(domain_id):
        tier = str(record.get("evidence_tier", ""))
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def evidence_layer_count(domain_id: str) -> int:
    """进关系图（证据层）的篇数。

    **判据是 `exclude_from_evidence_graph` 为假**，不是"档位不等于 metadata_only"——
    这两件事在 2026-10-17 之后不一样了：
    - `evidence_card`：按题录写了知识卡（有 `document_path`），进由知识卡建的关系图；
    - `full_text`：拿到了开放许可全文，进 `outputs/fulltext-knowledge.db` 那条路，
      没有知识卡之前**不**进由知识卡建的关系图，所以这一位是 True。

    `src/yanhai/corpus.py` 与 `scripts/export_display_data.py` 用的就是这个判据，
    测试必须跟它们一致，否则会出现"清单 150 条、导出 6 条"这种假失败。
    """
    return sum(
        1
        for record in records(domain_id)
        if not record.get("exclude_from_evidence_graph", False)
    )


def load_display() -> dict[str, Any]:
    global _DISPLAY_CACHE
    if _DISPLAY_CACHE is None:
        _DISPLAY_CACHE = json.loads(DISPLAY_DATA_PATH.read_text(encoding="utf-8"))
    return _DISPLAY_CACHE


def display_domains() -> dict[str, dict[str, Any]]:
    return {str(item["domain_id"]): item for item in load_display()["domains"]}


def paper_ids(items: list[dict[str, Any]]) -> set[str]:
    return {str(item["paper_id"]) for item in items}


def short(values: set[str], limit: int = 5) -> str:
    """报错信息里只列几个例子，全列出来刷屏。"""
    ordered = sorted(values)
    head = ordered[:limit]
    tail = "" if len(ordered) <= limit else f" 等共 {len(ordered)} 条"
    return "、".join(head) + tail


def assert_display_matches_manifest(
    case: Any,
    domain_id: str,
    display: dict[str, Any] | None = None,
) -> None:
    """核对"导出文件与清单一致"：这条才是这几个测试真正要保的东西。

    两边不一致时必须报错并指出差在哪里——领域、少了几条、多出来的例子。
    """
    display = display if display is not None else display_domains().get(domain_id)
    case.assertIsNotNone(
        display,
        f"display/data.json 里没有领域 {domain_id}，导出文件与清单对不上",
    )
    manifest_ids = set(record_ids(domain_id))
    exported_ids = paper_ids(display.get("papers", []))
    missing = manifest_ids - exported_ids
    extra = exported_ids - manifest_ids
    case.assertFalse(
        missing,
        f"{domain_id}：清单里有 {len(missing)} 条记录没有出现在 display/data.json 里，"
        f"例如 {short(missing)}",
    )
    case.assertFalse(
        extra,
        f"{domain_id}：display/data.json 里有 {len(extra)} 条记录在清单里找不到，"
        f"例如 {short(extra)}",
    )
