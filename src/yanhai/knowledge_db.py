"""只读读取「全文知识库」SQLite。

这些库是 `scripts/抽取/构建全文知识库.py` 建出来的，里面是 510 篇本地开放全文的
段落、证据跨度、实体与关系。**在这之前 API 一次都没打开过它们** —— 产品界面上的关系
是从 `data/vertical_kb` 的知识卡现算的，规模比库里少一个数量级（材料领域：接口 26 条关系
对库内 9224 条）。这个模块就是那条"把数据库接进来"的口子。

规矩：
- 一律 `mode=ro` 打开，不写、不改、不建表、不 vacuum。
- 库不存在就返回"没有"，不报错也不伪造空库。
- 关系编号带领域前缀（`<domain>:<relation_id>`），避免两个领域的哈希撞车。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .extraction import looks_like_citation_style

DEFAULT_DB_NAME = "fulltext-knowledge.db"
DOMAIN_DIRNAME = "domains"
DOMAIN_SUFFIX = "-knowledge.db"

_TABLES = ("papers", "sections", "evidence", "entities", "relations", "relation_evidence")


class KnowledgeDatabase:
    """全文知识库的只读视图。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        # 质量评估要扫 5.9 万条证据（约 2.3 秒），按库文件的修改时间缓存一次
        self._quality_cache: dict[str, Any] | None = None
        self._quality_signature: tuple[Any, ...] | None = None

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------

    def path_for(self, domain_id: str) -> Path:
        """默认领域落在 outputs/fulltext-knowledge.db，其余落在 outputs/domains/。"""
        if domain_id in {"", "scientific-ie-kg"}:
            return self.root / DEFAULT_DB_NAME
        return self.root / DOMAIN_DIRNAME / f"{domain_id}{DOMAIN_SUFFIX}"

    def domain_ids(self) -> list[str]:
        """按磁盘上真实存在的库列出领域编号（不猜、不补）。"""
        found: list[str] = []
        if (self.root / DEFAULT_DB_NAME).is_file():
            found.append("scientific-ie-kg")
        domain_dir = self.root / DOMAIN_DIRNAME
        if domain_dir.is_dir():
            for path in sorted(domain_dir.glob(f"*{DOMAIN_SUFFIX}")):
                found.append(path.name[: -len(DOMAIN_SUFFIX)])
        return found

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    # ------------------------------------------------------------------
    # 概况
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """每个库的表行数、体积与修改时间；库不在就标 missing。"""
        entries: list[dict[str, Any]] = []
        totals = {name: 0 for name in _TABLES}
        for domain_id in self.domain_ids():
            path = self.path_for(domain_id)
            entry: dict[str, Any] = {
                "domain_id": domain_id,
                "path": str(path.relative_to(self.root)),
                "exists": path.is_file(),
            }
            if not path.is_file():
                entry["counts"] = None
                entries.append(entry)
                continue
            stat = path.stat()
            entry["bytes"] = stat.st_size
            entry["modified_at"] = stat.st_mtime
            counts: dict[str, int] = {}
            try:
                with self._connect(path) as connection:
                    for name in _TABLES:
                        counts[name] = int(
                            connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                        )
            except sqlite3.Error as exc:
                entry["error"] = str(exc)
                entry["counts"] = None
                entries.append(entry)
                continue
            entry["counts"] = counts
            for name, value in counts.items():
                totals[name] += value
            entries.append(entry)
        return {
            "root": str(self.root),
            "domains": entries,
            "totals": totals,
            "tables": list(_TABLES),
        }

    # ------------------------------------------------------------------
    # 论文与关系
    # ------------------------------------------------------------------

    def papers(self, domain_id: str, limit: int = 2000) -> list[dict[str, Any]]:
        """库里这批论文，连同各自的证据条数与牵涉到的关系条数。

        计数用两次聚合查询算，而不是对每篇论文跑相关子查询——
        后者在主领域上要 1 秒多，界面打开就卡。
        """
        path = self.path_for(domain_id)
        if not path.is_file():
            return []
        cap = max(1, min(5000, limit))
        with self._connect(path) as connection:
            rows = connection.execute(
                "SELECT paper_id, title, source_url FROM papers ORDER BY title LIMIT ?",
                (cap,),
            ).fetchall()
            if not rows:
                return []
            ids = [row["paper_id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            evidence_counts = {
                row[0]: int(row[1])
                for row in connection.execute(
                    f"""
                    SELECT paper_id, count(*) FROM evidence
                    WHERE paper_id IN ({placeholders}) GROUP BY paper_id
                    """,
                    tuple(ids),
                ).fetchall()
            }
            relation_counts = {
                row[0]: int(row[1])
                for row in connection.execute(
                    f"""
                    SELECT e.paper_id, count(DISTINCT re.relation_id)
                    FROM relation_evidence re
                    JOIN evidence e ON e.evidence_id = re.evidence_id
                    WHERE e.paper_id IN ({placeholders})
                    GROUP BY e.paper_id
                    """,
                    tuple(ids),
                ).fetchall()
            }
        return [
            {
                "paper_id": row["paper_id"],
                "title": row["title"],
                "source_url": row["source_url"],
                "evidence_count": evidence_counts.get(row["paper_id"], 0),
                "relation_count": relation_counts.get(row["paper_id"], 0),
            }
            for row in rows
        ]

    def relations_for_papers(
        self,
        domain_id: str,
        paper_ids: Iterable[str],
        limit: int = 4000,
    ) -> list[dict[str, Any]]:
        """取这些论文牵涉到的关系，连同它们的证据跨度。

        一条关系可能由多篇论文共同支撑：这里按关系去重（同一领域内关系编号唯一），
        证据只返回传入这些论文名下的跨度。这样用户审一次就是一条关系，
        而不是同一句话被两篇论文各记一遍。
        """
        wanted = [str(item) for item in paper_ids if str(item).strip()]
        if not wanted:
            return []
        path = self.path_for(domain_id)
        if not path.is_file():
            return []
        placeholders = ",".join("?" for _ in wanted)
        with self._connect(path) as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT r.relation_id, r.relation_type, r.confidence, r.status,
                       s.canonical_name AS source_name, s.entity_type AS source_type,
                       t.canonical_name AS target_name, t.entity_type AS target_type
                FROM relations r
                JOIN relation_evidence re ON re.relation_id = r.relation_id
                JOIN evidence e ON e.evidence_id = re.evidence_id
                LEFT JOIN entities s ON s.entity_id = r.source_id
                LEFT JOIN entities t ON t.entity_id = r.target_id
                WHERE e.paper_id IN ({placeholders})
                ORDER BY r.relation_id
                LIMIT ?
                """,
                (*wanted, max(1, min(20000, limit))),
            ).fetchall()
            if not rows:
                return []
            relation_ids = [row["relation_id"] for row in rows]
            id_placeholders = ",".join("?" for _ in relation_ids)
            evidence_rows = connection.execute(
                f"""
                SELECT re.relation_id, e.evidence_id, e.paper_id, e.section_id,
                       e.text, e.char_start, e.char_end
                FROM relation_evidence re
                JOIN evidence e ON e.evidence_id = re.evidence_id
                WHERE re.relation_id IN ({id_placeholders})
                  AND e.paper_id IN ({placeholders})
                ORDER BY e.paper_id, e.char_start
                """,
                (*relation_ids, *wanted),
            ).fetchall()

        evidence_by_relation: dict[str, list[dict[str, Any]]] = {}
        for row in evidence_rows:
            evidence_by_relation.setdefault(row["relation_id"], []).append(
                {
                    "evidence_id": row["evidence_id"],
                    "paper_id": row["paper_id"],
                    "section_id": row["section_id"],
                    "char_start": int(row["char_start"] or 0),
                    "char_end": int(row["char_end"] or 0),
                    "text": row["text"] or "",
                }
            )

        payload: list[dict[str, Any]] = []
        for row in rows:
            spans = evidence_by_relation.get(row["relation_id"], [])
            payload.append(
                {
                    # 关系编号带领域前缀，避免不同领域的哈希撞车
                    "relation_id": f"{domain_id}:{row['relation_id']}",
                    "source_name": row["source_name"] or "",
                    "target_name": row["target_name"] or "",
                    "relation_type": row["relation_type"] or "",
                    "source_type": row["source_type"] or "",
                    "target_type": row["target_type"] or "",
                    "status": row["status"] or "needs_review",
                    "confidence": float(row["confidence"] or 0),
                    "paper_id": spans[0]["paper_id"] if spans else (wanted[0] if wanted else ""),
                    "evidence": spans,
                }
            )
        return payload

    def domain_for_paper(self, paper_id: str) -> str | None:
        """这张论文在哪个领域的库里；找不到返回 None。"""
        for domain_id in self.domain_ids():
            path = self.path_for(domain_id)
            if not path.is_file():
                continue
            with self._connect(path) as connection:
                row = connection.execute(
                    "SELECT 1 FROM papers WHERE paper_id = ? LIMIT 1", (paper_id,)
                ).fetchone()
            if row is not None:
                return domain_id
        return None

    def corpus_totals(self) -> dict[str, Any]:
        """给界面用的一句话总量：多少篇、多少证据、多少关系。"""
        summary = self.summary()
        totals = summary["totals"]
        return {
            "domains": len([item for item in summary["domains"] if item.get("exists")]),
            "papers": totals["papers"],
            "sections": totals["sections"],
            "evidence": totals["evidence"],
            "entities": totals["entities"],
            "relations": totals["relations"],
            "relation_evidence": totals["relation_evidence"],
            "root": summary["root"],
        }

    # ------------------------------------------------------------------
    # 数据质量：有多少证据其实是参考文献
    # ------------------------------------------------------------------

    def quality(self, domain_id: str) -> dict[str, Any]:
        """量一下这个库里的证据有多少是引文式（参考文献条目）。

        判据直接用抽取器那条 `looks_like_citation_style`，与构建脚本里
        `--drop-reference-spans` 用的是同一套规则——不同一套就会自相矛盾。

        为什么要单独量：这批库是**开着默认参数**建的，参考文献排除关着，
        所以证据层里混着参考文献条目。这个数字让"混了多少"变成可核对的数，
        而不是一句"可能有问题"。
        """
        path = self.path_for(domain_id)
        if not path.is_file():
            return {
                "domain_id": domain_id,
                "exists": False,
                "evidence_total": 0,
                "citation_like": 0,
                "share": 0.0,
                "samples": [],
            }
        with self._connect(path) as connection:
            rows = connection.execute(
                "SELECT evidence_id, paper_id, text FROM evidence"
            ).fetchall()
        total = len(rows)
        flagged = 0
        samples: list[dict[str, Any]] = []
        for row in rows:
            text = row["text"] or ""
            if not looks_like_citation_style(text):
                continue
            flagged += 1
            if len(samples) < 3:
                samples.append(
                    {
                        "evidence_id": row["evidence_id"],
                        "paper_id": row["paper_id"],
                        "text": text[:180],
                    }
                )
        return {
            "domain_id": domain_id,
            "exists": True,
            "evidence_total": total,
            "citation_like": flagged,
            "share": round(flagged / total, 4) if total else 0.0,
            "samples": samples,
        }

    def quality_all(self) -> dict[str, Any]:
        signature = tuple(
            (domain_id, self._mtime(domain_id)) for domain_id in self.domain_ids()
        )
        if self._quality_cache is not None and self._quality_signature == signature:
            return self._quality_cache
        domains = [self.quality(domain_id) for domain_id in self.domain_ids()]
        total = sum(item["evidence_total"] for item in domains)
        flagged = sum(item["citation_like"] for item in domains)
        payload = {
            "domains": domains,
            "evidence_total": total,
            "citation_like": flagged,
            "share": round(flagged / total, 4) if total else 0.0,
            "judged_by": "looks_like_citation_style（与构建脚本 --drop-reference-spans 同一套判据）",
            "note": (
                "这批全文知识库是按默认参数建的，参考文献排除没开，所以证据层里混着引文式条目。"
                "要干净的证据层，得用 --drop-reference-spans 重建库。"
            ),
        }
        self._quality_cache = payload
        self._quality_signature = signature
        return payload

    def _mtime(self, domain_id: str) -> float:
        path = self.path_for(domain_id)
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0


def format_bytes(size: int | None) -> str:
    if not size:
        return "—"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
