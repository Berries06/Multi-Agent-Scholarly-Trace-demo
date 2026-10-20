"""把项目里用户自己导入的论文，接成一次研究运行可以用的证据。

为什么要有这一层：工作台原来的研究运行只读"领域公共语料"，
用户导入的论文只进了项目和候选关系，跑研究时完全用不上——
那这套东西就永远只是演示。这个模块负责把项目里已有的论文、证据片段、
候选关系和实体整理成一份**运行期证据包**，交给编排器叠在领域知识库上。

边界：

- 只取这个项目自己的行（`project_papers` / `project_relations` /
  `project_relation_evidence`），不跨项目、不读 `data/evaluation/`；
- 证据片段就是导入时落下来的那些字符跨度，不含整篇正文；
- 用户的审阅决定（include / defer / exclude）不改机器状态，这里只读不改。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import Paper


def _as_paper(record: dict[str, Any], fallback_paper_id: str) -> Paper:
    """用项目里记的题录拼一个 Paper；缺的字段给空的，不要编。"""
    paper_id = str(record.get("paper_id") or fallback_paper_id)
    return Paper(
        paper_id=paper_id,
        title=str(record.get("title") or paper_id),
        authors=tuple(record.get("authors") or ()),
        year=int(record.get("year") or 0),
        published=str(record.get("published") or ""),
        categories=tuple(record.get("categories") or ("user-import",)),
        summary=str(record.get("summary") or ""),
        concepts=tuple(record.get("concepts") or ()),
        source_url=str(record.get("source_url") or ""),
        source_type=str(record.get("source_type") or "user-import"),
    )


@dataclass(slots=True)
class ProjectEvidence:
    """一次运行要用的"我自己导入的论文"证据包。"""

    project_id: str
    papers: list[Paper] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    # 项目里一共有多少篇论文、这次按问题选中了哪几篇：
    # 界面上要写清"从 1000 篇里挑了 12 篇"，不能让人以为 1000 篇都分析了。
    library_paper_count: int = 0
    selection_reason: str = "newest"

    @property
    def paper_ids(self) -> set[str]:
        return {paper.paper_id for paper in self.papers}

    @property
    def evidence_ids(self) -> set[str]:
        return {str(item.get("evidence_id")) for item in self.evidence if item.get("evidence_id")}

    def is_empty(self) -> bool:
        """没有任何可用证据的包等于没给。"""
        return not self.papers or not self.evidence

    def evidence_index(self) -> dict[str, dict[str, Any]]:
        return {
            str(item["evidence_id"]): item
            for item in self.evidence
            if item.get("evidence_id")
        }

    def entity_alias_overlay(self) -> dict[str, tuple[str, set[str]]]:
        """项目里抽出来的实体名 → (类型, 写法集合)。

        叠在领域 schema 之上：这些名字是用户自己论文里的写法，schema 里多半没有。
        """
        overlay: dict[str, tuple[str, set[str]]] = {}
        for entity in self.entities:
            name = str(entity.get("canonical_name") or "").strip()
            if not name:
                continue
            entity_type = str(entity.get("entity_type") or "")
            spellings = {name.casefold()}
            spellings.update(
                str(alias).casefold()
                for alias in entity.get("aliases") or []
                if isinstance(alias, str) and alias.strip()
            )
            overlay[name.casefold()] = (entity_type, spellings)
        return overlay

    def graph_payload(self) -> dict[str, Any]:
        """按 `extracted_paper_graph()` 的形状给出这份证据自带的图。

        "只用我自己的论文"跑的时候，页面上的知识图谱就取这一份，
        免得把公共语料的关系混进来冒充自己的结果。

        关系两端的实体必须都能在 `entities` 里查到：导入记录里没留下实体类型时，
        这里按关系上记的名字补一个实体，`source_id` 也补上。少了这一步，
        下游按 id 取实体就会取空（实测过：KeyError ''）。
        """
        entities: list[dict[str, Any]] = [dict(item) for item in self.entities if isinstance(item, dict)]
        by_name = {
            str(item.get("canonical_name") or "").casefold(): str(item.get("entity_id") or "")
            for item in entities
            if item.get("canonical_name")
        }

        def ensure_entity(name: str, entity_type: str) -> str:
            key = name.casefold()
            if key in by_name and by_name[key]:
                return by_name[key]
            slug = "".join(ch if ch.isalnum() else "-" for ch in key).strip("-")[:48] or "entity"
            entity_id = f"entity:project:{slug}"
            entities.append(
                {
                    "entity_id": entity_id,
                    "canonical_name": name,
                    "entity_type": entity_type or "UNKNOWN",
                    "aliases": [],
                    "confidence": 1.0,
                    "mentions": [],
                }
            )
            by_name[key] = entity_id
            return entity_id

        relations = []
        for index, relation in enumerate(self.relations, start=1):
            source = str(relation.get("source") or "")
            target = str(relation.get("target") or "")
            source_id = str(relation.get("source_id") or "") or ensure_entity(source, str(relation.get("source_type") or ""))
            target_id = str(relation.get("target_id") or "") or ensure_entity(target, str(relation.get("target_type") or ""))
            relations.append(
                {
                    "relation_id": str(relation.get("relation_id") or f"project-{index}"),
                    "source_id": source_id,
                    "target_id": target_id,
                    "relation_type": str(relation.get("relation_type") or ""),
                    "evidence_ids": list(relation.get("evidence_ids") or []),
                    "confidence": float(relation.get("confidence") or 0),
                    "status": str(relation.get("machine_status") or "needs_review"),
                    "extraction_method": str(relation.get("extraction_method") or "user-import"),
                }
            )
        return {
            "domain": {
                "domain_id": f"project:{self.project_id}",
                "domain_name": "我导入的论文",
                "version": "project",
                "paper_count": len(self.papers),
                "evidence_paper_count": len(self.papers),
                "metadata_only_paper_count": 0,
            },
            "papers": [paper.to_dict() for paper in self.papers],
            "sections": [],
            "entities": entities,
            "evidence": self.evidence,
            "relations": relations,
            "communities": [],
            "audit": {},
        }


_TITLE_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "into", "using", "based", "towards",
        "toward", "study", "analysis", "review", "approach", "method", "methods",
        "a", "an", "of", "in", "on", "to", "by", "via", "is", "are",
    }
)


def _title_terms(text: str) -> set[str]:
    """把标题/问题切成可比的小词：英文按词、中文按 2–4 字滑窗。

    只用于"从几百上千篇里挑出跟这次问题相关的那几篇"，不追求分词准确：
    挑错一两篇的代价是少一条候选关系，挑不到的代价才是功能失效。
    """
    lowered = str(text or "").casefold()
    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9\-]+", lowered)
        if len(token) > 2 and token not in _TITLE_STOPWORDS
    }
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        for width in (2, 3, 4):
            terms.update(
                run[index : index + width]
                for index in range(max(0, len(run) - width + 1))
            )
    return terms


def select_papers_for_query(
    rows: list[dict[str, Any]],
    query: str | None,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    """从项目的全部论文里挑出这次要分析的那几篇。

    有研究问题时按标题与问题的重合度排序（越相关越靠前），重合度全是 0 就退回
    "最近加入的"。**命中的不足上限时有几篇算几篇**——宁可用一篇对的，
    也不拿 11 篇无关的凑满 12 篇，凑进来的关系会挤掉真正相关那条。
    结果用 (选中的行, 选中理由) 返回，界面据此写清"从 N 篇里挑了 K 篇"。
    """
    if not rows:
        return [], "empty"
    if limit >= len(rows):
        return list(rows), "all"

    query_terms = _title_terms(query or "")
    if not query_terms:
        return list(rows[:limit]), "newest"

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        title_terms = _title_terms(str(row.get("title") or ""))
        overlap = len(query_terms & title_terms)
        scored.append((float(overlap), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored[0][0] <= 0:
        return list(rows[:limit]), "newest"
    selected = [row for score, row in scored[:limit] if score > 0]
    return selected or list(rows[:limit]), "query"


def load_project_evidence(
    repository: Any,
    *,
    user_id: str,
    project_id: str,
    query: str | None = None,
    max_papers: int = 12,
) -> ProjectEvidence:
    """从项目里读出证据包。

    **只读这次要分析的那几篇。** 声明一下这里的规模口径：用户文献库可以到上千篇，
    但一次研究不可能对着一千篇同时分析——真正做的是按研究问题从库里挑出最相关的
    若干篇（默认 12 篇），只把这些论文的关系与证据读进内存，其余的一个字节都不读。
    实测 1000 篇 / 3 万条关系的库，整库读一遍要 1.4 秒、18 MB；只读 12 篇是毫秒级。

    关系与证据以 `project_relations` / `project_relation_evidence` 为准（那是项目自己的
    一份账）；实体与题录从导入记录里补，因为只有那里留着实体类型与写法。
    读不到导入记录时只丢实体（证据照样能用），不抛异常。
    """
    bundle = ProjectEvidence(project_id=project_id)
    all_rows = repository.project_papers(user_id=user_id, project_id=project_id)
    bundle.library_paper_count = len(all_rows)
    rows, reason = select_papers_for_query(all_rows, query, limit=max_papers)
    bundle.selection_reason = reason
    if not rows:
        return bundle
    selected_ids = [str(row["paper_id"]) for row in rows]

    titles = {str(row["paper_id"]): str(row.get("title") or "") for row in rows}
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        ingestion_id = row.get("ingestion_id")
        if not ingestion_id:
            continue
        try:
            ingestion = repository.get_ingestion(user_id=user_id, ingestion_id=str(ingestion_id))
        except Exception:  # noqa: BLE001 - 导入记录读不到不该让整次运行失败
            continue
        try:
            payload = json.loads(ingestion.get("result_json") or "{}")
        except json.JSONDecodeError:
            continue
        extraction = payload.get("extraction") or {}
        for item in extraction.get("papers") or []:
            if isinstance(item, dict) and item.get("paper_id"):
                records[str(item["paper_id"])] = {**item, "title": titles.get(str(item["paper_id"])) or item.get("title") or ""}
        for entity in extraction.get("entities") or []:
            if isinstance(entity, dict):
                bundle.entities.append(entity)

    seen_papers: set[str] = set()
    for row in rows:
        paper_id = str(row["paper_id"])
        if paper_id in seen_papers:
            continue
        seen_papers.add(paper_id)
        bundle.papers.append(_as_paper(records.get(paper_id, {}), paper_id))

    # 证据片段：只取选中那几篇的，按关系分组
    spans_by_relation: dict[str, list[dict[str, Any]]] = {}
    for span in repository.project_evidence_spans(
        user_id=user_id, project_id=project_id, paper_ids=selected_ids
    ):
        spans_by_relation.setdefault(str(span["relation_id"]), []).append(
            {
                "evidence_id": str(span["evidence_id"]),
                "paper_id": str(span["paper_id"]),
                "section_id": str(span.get("section_id") or ""),
                "text": str(span.get("text") or ""),
                "char_start": int(span.get("char_start") or 0),
                "char_end": int(span.get("char_end") or 0),
            }
        )

    entity_ids: dict[str, str] = {}
    for entity in bundle.entities:
        name = str(entity.get("canonical_name") or "").casefold()
        if name:
            entity_ids[name] = str(entity.get("entity_id") or "")

    for relation in repository.project_relations(
        user_id=user_id, project_id=project_id, paper_ids=selected_ids
    ):
        relation_id = str(relation["relation_id"])
        spans = spans_by_relation.get(relation_id) or []
        if not spans:
            continue
        source = str(relation["source_name"])
        target = str(relation["target_name"])
        bundle.evidence.extend(spans)
        bundle.relations.append(
            {
                "relation_id": relation_id,
                "source": source,
                "source_type": str(relation.get("source_type") or ""),
                "relation": str(relation.get("relation_type") or "").lower(),
                "relation_type": str(relation.get("relation_type") or ""),
                "target": target,
                "target_type": str(relation.get("target_type") or ""),
                "confidence": float(relation.get("confidence") or 0),
                "evidence_ids": [span["evidence_id"] for span in spans],
                "machine_status": str(relation.get("machine_status") or "needs_review"),
                "extraction_method": "user-import",
                "source_id": entity_ids.get(source.casefold(), ""),
                "target_id": entity_ids.get(target.casefold(), ""),
            }
        )
    return bundle
