from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .corpus import VerticalCorpus
from .models import LearnerProfile, Paper


QUERY_ALIASES = {
    "多智能体": ("multi-agent", "agent", "debate", "collaboration"),
    "科研": ("scientific", "research", "scholarly"),
    "幻觉": ("hallucination", "factuality", "grounding"),
    "知识图谱": ("knowledge graph", "graph rag", "graphrag"),
    "争议": ("debate", "critique", "conflict"),
    "蓝海": ("discovery", "gap", "uncertainty"),
    "溯源": ("traceability", "citation", "evidence"),
    "材料": ("materials", "crystal", "property prediction"),
    "晶体": ("crystal", "crystal graph", "stable materials"),
    "知识追踪": ("knowledge tracing", "student performance", "mastery"),
    "学习者": ("learner", "student", "personalized learning"),
}


def _status_from_relation(relation: dict[str, Any]) -> str:
    """没有 upstream_status 时退回 machine_status，让排序口径一致。"""
    return str(relation.get("machine_status") or "")


class KnowledgeBase:
    def __init__(
        self,
        root: Path,
        domain_id: str | None = None,
        *,
        custom_domain: dict[str, Any] | None = None,
    ) -> None:
        """`custom_domain` 给了就按"用户自己起的领域"来建知识库。

        自定义领域不在 `registry.json` 里，也没有语料目录：这里给它一份零篇论文的
        清单，`papers` 为空、证据与关系为空。抽取用的 schema 仍是共享的那一份，
        所以用户导入自己的论文时走的还是同一套字段与判据。
        """
        self.root = root
        self.legacy_papers = self._load_papers(root / "papers.json")
        vertical_base = root.parent / "vertical_kb"
        registry_path = vertical_base / "registry.json"
        if registry_path.exists():
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        else:
            registry = {
                "default_domain_id": "scientific-ie-kg",
                "domains": [
                    {
                        "domain_id": "scientific-ie-kg",
                        "path": ".",
                    }
                ],
            }
        self.default_domain_id = str(registry["default_domain_id"])
        self.domain_configs = {
            str(item["domain_id"]): dict(item)
            for item in registry.get("domains", [])
        }
        if custom_domain is not None:
            custom_id = str(custom_domain["domain_id"])
            self.domain_configs[custom_id] = {
                "domain_id": custom_id,
                "domain_name": str(custom_domain.get("domain_name") or custom_id),
                "description": str(custom_domain.get("description") or ""),
                "path": ".",
                "is_custom": True,
            }
        selected_domain_id = domain_id or self.default_domain_id
        if selected_domain_id not in self.domain_configs:
            raise KeyError(f"Unknown domain: {selected_domain_id}")
        self.selected_domain_id = selected_domain_id
        selected_config = self.domain_configs[selected_domain_id]
        vertical_root = (
            vertical_base / str(selected_config.get("path", "."))
        ).resolve()
        resolved_base = vertical_base.resolve()
        if vertical_root != resolved_base and resolved_base not in vertical_root.parents:
            raise ValueError("Vertical corpus path must stay inside data/vertical_kb.")
        if custom_domain is not None:
            self.vertical_corpus = VerticalCorpus(
                vertical_root,
                root / "extraction_schema.json",
                manifest={
                    "domain_id": str(custom_domain["domain_id"]),
                    "domain_name": str(custom_domain.get("domain_name") or custom_domain["domain_id"]),
                    "version": "custom",
                    "description": str(custom_domain.get("description") or ""),
                    "corpus_type": "custom",
                    "source_scope": "用户自定义领域，没有公共语料，论文由用户自己从文献库导入。",
                    "papers": [],
                },
            )
        else:
            self.vertical_corpus = VerticalCorpus(
                vertical_root,
                root / "extraction_schema.json",
            )
        # 扩展切片严格隔离。默认切片保留早期多智能体阅读清单，
        # 以保持 demo/测试的向后兼容。
        if custom_domain is not None:
            self.papers = []
        elif selected_domain_id == self.default_domain_id:
            vertical_ids = {
                paper.paper_id for paper in self.vertical_corpus.papers
            }
            self.papers = [
                *self.vertical_corpus.papers,
                *(
                    paper
                    for paper in self.legacy_papers
                    if paper.paper_id not in vertical_ids
                ),
            ]
        else:
            self.papers = list(self.vertical_corpus.papers)
        self.relations = self._load_json(root / "relations.json")
        self.paper_by_id = {paper.paper_id: paper for paper in self.papers}
        self.schema = self.vertical_corpus.extractor.schema
        self.entity_type_by_name: dict[str, str] = {}
        for concept in self.schema["concepts"]:
            for name in {concept["canonical"], *concept.get("aliases", [])}:
                self.entity_type_by_name[name.casefold()] = concept["entity_type"]
        self._extracted_graph: dict[str, Any] | None = None
        # 附加证据层：默认空，行为与以前完全一致。评测集把真原文片段（库里查不到的
        # 那些）登记进来后，`evidence_is_valid` / `evidence_details` /
        # `entity_mentioned_in_evidence` 就能在这层上工作，而不必去读 outputs 下的库。
        self.evidence_registry: dict[str, dict[str, Any]] = {}
        # 附加别名层：同样默认空。真原文里的实体名（SciREX、GLiREL、SCIIE……）多数
        # 不在 `extraction_schema.json` 的 concepts 里，而 DYGIE 这类解析断词（词间
        # 空格丢失，`SCIIE` 被截成 `CIIE`）也不是 schema 能预料的。评测集为每条案例
        # 声明自己用到的写法，登记在这里，`entity_mentioned_in_evidence` 即可按
        # 同一套别名机制匹配，不必去改 schema。
        self.entity_alias_overlay: dict[str, tuple[str, set[str]]] = {}
        # 项目自己那批候选关系：默认空（行为与以前一致），只有把用户导入的论文
        # 叠上来跑研究时才有内容。
        self.project_relations: list[dict[str, Any]] = []

    @property
    def domain(self) -> dict[str, Any]:
        metadata = dict(self.domain_configs[self.selected_domain_id])
        metadata.pop("path", None)
        return {**metadata, **self.vertical_corpus.domain}

    def list_domain_configs(self) -> list[dict[str, Any]]:
        return [
            {
                **{
                    key: value
                    for key, value in config.items()
                    if key != "path"
                },
                "is_default": domain_id == self.default_domain_id,
            }
            for domain_id, config in self.domain_configs.items()
        ]

    @staticmethod
    def _load_json(path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_papers(self, path: Path) -> list[Paper]:
        return [Paper.from_dict(item) for item in self._load_json(path)]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        terms = set(re.findall(r"[a-z0-9][a-z0-9-]+|[\u4e00-\u9fff]{2,}", lowered))
        # 标准库正则会把整句中文当作一个 token。字符 n-gram 让离线 demo
        # 保持对查询敏感，且不引入分词器依赖；正式实验可通过检索适配器
        # 替换为领域分词器。
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
            for width in (2, 3, 4, 5, 6):
                terms.update(
                    run[index : index + width]
                    for index in range(max(0, len(run) - width + 1))
                )
        for key, aliases in QUERY_ALIASES.items():
            if key in text:
                terms.add(key)
                terms.update(aliases)
                for alias in aliases:
                    terms.update(
                        re.findall(
                            r"[a-z0-9][a-z0-9-]+|[\u4e00-\u9fff]{2,}",
                            alias.casefold(),
                        )
                    )
        return terms

    def search(
        self,
        query: str,
        profile: LearnerProfile,
        blind_spots: list[str],
        limit: int = 8,
        information_gain: bool = False,
    ) -> list[Paper]:
        query_terms = self._tokens(query)
        context_terms = self._tokens(
            " ".join(
                [profile.goal, *profile.interests, *blind_spots, *profile.required_concepts]
            )
        )
        scored: list[tuple[float, Paper]] = []
        for paper in self.papers:
            haystack = " ".join(
                [paper.title, paper.summary, *paper.categories, *paper.concepts]
            ).lower()
            if information_gain:
                query_score = sum(
                    3.0 if term in paper.concepts else 1.5
                    for term in query_terms
                    if term in haystack
                )
                context_score = sum(
                    0.8 if term in paper.concepts else 0.35
                    for term in context_terms
                    if term in haystack
                )
                novelty_bonus = 0.15 * len(set(paper.concepts) - context_terms)
                score = query_score + context_score + novelty_bonus
            else:
                terms = query_terms | context_terms
                score = sum(
                    2.0 if term in paper.concepts else 1.0
                    for term in terms
                    if term in haystack
                )
            score += 0.01 * (paper.year - 2020)
            scored.append((score, paper))
        scored.sort(key=lambda item: (item[0], item[1].year), reverse=True)
        selected: list[Paper] = []
        seen: set[str] = set()
        for score, paper in scored:
            if score <= 0 or paper.paper_id in seen:
                continue
            selected.append(paper)
            seen.add(paper.paper_id)
            if len(selected) >= limit:
                break
        if selected:
            return selected
        for _, paper in scored:
            if paper.paper_id in seen:
                continue
            selected.append(paper)
            seen.add(paper.paper_id)
            if len(selected) >= limit:
                break
        return selected

    def with_project_evidence(
        self,
        evidence: Any,
        *,
        include_corpus: bool = True,
        ) -> "KnowledgeBase":
        """拿一份"领域知识库 + 我自己导入的论文"的**运行期**视图。

        为什么是浅拷贝再覆盖，而不是直接改这个对象：领域知识库是进程级缓存的，
        一个账号把自己的论文叠上去，另一个账号下一次运行就会看到别人的证据。
        浅拷贝只重建那几个可变容器，语料与 schema 仍然共用（只读），开销很小。

        `include_corpus=False` 时连公共语料论文一起摘掉，`extracted_paper_graph()`
        也换成这份证据自己的图——页面上看到的就真的只是自己那几篇。
        """
        clone = copy.copy(self)
        project_papers = list(getattr(evidence, "papers", []) or [])
        clone.papers = list(project_papers) if not include_corpus else [*project_papers, *self.papers]
        clone.paper_by_id = {paper.paper_id: paper for paper in clone.papers}
        clone.evidence_registry = {
            **self.evidence_registry,
            **getattr(evidence, "evidence_index", lambda: {})(),
        }
        clone.entity_alias_overlay = {
            **self.entity_alias_overlay,
            **getattr(evidence, "entity_alias_overlay", lambda: {})(),
        }
        # 项目自己那批候选关系另放一层，`candidate_relations` 会一起看。
        clone.project_relations = list(getattr(evidence, "relations", []) or [])
        # 界面显示用的那份"我导入的论文"图谱，`display_graph()` 会优先用它。
        clone.project_graph = getattr(evidence, "graph_payload", lambda: {})()
        return clone

    def candidate_relations(self, paper_ids: set[str], limit: int = 8) -> list[dict[str, Any]]:
        """给提出者的候选关系：**自己导入的论文排在最前面**，公共语料补在后面。

        这里的顺序不是"谁分数高谁上"。用户把自己那几篇论文放进项目、又选了它来跑，
        要的就是从自己的文献里得出结论；如果让公共语料的置信度把它挤下去，
        这个功能等于没做。所以项目里的候选先占坑，剩下的名额才给语料。
        """
        project_candidates = self._project_candidates(paper_ids)
        project_candidates.sort(
            key=lambda item: (
                str(item.get("upstream_status") or "") in {"accepted", "include"},
                float(item.get("confidence") or 0),
                len(item.get("evidence_ids") or []),
            ),
            reverse=True,
        )
        graph_candidates = self.candidate_graph_relations(paper_ids, limit=limit)
        if not project_candidates and not graph_candidates:
            candidates = [
                relation
                for relation in self.relations
                if paper_ids.intersection(relation["evidence_ids"])
            ]
            candidates.sort(
                key=lambda relation: (
                    float(relation["confidence"]),
                    len(relation["evidence_ids"]),
                ),
                reverse=True,
            )
            return candidates[:limit]

        merged = [*project_candidates, *graph_candidates]
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in merged:
            key = (
                str(item.get("source") or "").casefold(),
                str(item.get("relation_type") or ""),
                str(item.get("target") or "").casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:limit]

    def _project_candidates(self, paper_ids: set[str]) -> list[dict[str, Any]]:
        """把项目里那批候选关系整理成和语料候选一样的形状。"""
        index = self.evidence_registry
        candidates: list[dict[str, Any]] = []
        for relation in getattr(self, "project_relations", []):
            evidence_ids = [
                str(item) for item in relation.get("evidence_ids") or [] if str(item) in index
            ]
            if not evidence_ids:
                continue
            paper_hit = {
                str(index[item].get("paper_id") or "") for item in evidence_ids
            }.intersection(paper_ids)
            if not paper_hit:
                continue
            candidates.append(
                {
                    "source": relation["source"],
                    "source_type": relation.get("source_type") or self.entity_type_for_name(relation["source"]),
                    "relation": relation.get("relation") or str(relation["relation_type"]).lower(),
                    "target": relation["target"],
                    "target_type": relation.get("target_type") or self.entity_type_for_name(relation["target"]),
                    "relation_type": relation["relation_type"],
                    "confidence": float(relation.get("confidence") or 0),
                    "evidence_ids": evidence_ids,
                    "upstream_status": str(relation.get("machine_status") or "needs_review"),
                    "extraction_method": str(relation.get("extraction_method") or "user-import"),
                }
            )
        return candidates

    def candidate_graph_relations(
        self,
        paper_ids: set[str],
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        payload = self.extracted_paper_graph()
        entity_by_id = {
            item["entity_id"]: item for item in payload["entities"]
        }
        evidence_by_id = {
            item["evidence_id"]: item for item in payload["evidence"]
        }
        candidates: list[dict[str, Any]] = []
        for relation in payload["relations"]:
            relation_paper_ids = {
                evidence_by_id[evidence_id]["paper_id"]
                for evidence_id in relation["evidence_ids"]
                if evidence_id in evidence_by_id
            }
            if not relation_paper_ids.intersection(paper_ids):
                continue
            source = entity_by_id.get(relation.get("source_id", ""))
            target = entity_by_id.get(relation.get("target_id", ""))
            if source is None or target is None:
                # 关系两端在实体表里查不到就没法渲染，跳过而不是抛 ——
                # 这条关系本身仍然可以通过 `project_relations` 那层进候选。
                continue
            candidates.append(
                {
                    "source": source["canonical_name"],
                    "source_type": source["entity_type"],
                    "relation": relation["relation_type"].lower(),
                    "target": target["canonical_name"],
                    "target_type": target["entity_type"],
                    "relation_type": relation["relation_type"],
                    "confidence": relation["confidence"],
                    "evidence_ids": relation["evidence_ids"],
                    "upstream_status": relation["status"],
                    "extraction_method": relation["extraction_method"],
                }
            )
        candidates.sort(
            key=lambda item: (
                item["upstream_status"] == "accepted",
                float(item["confidence"]),
                len(item["evidence_ids"]),
            ),
            reverse=True,
        )
        return candidates[:limit]

    def graph_for_claims(
        self,
        claims: list[dict[str, Any]],
        *,
        include_provenance: bool = False,
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, str]] = {}
        edges: list[dict[str, Any]] = []
        for claim in claims:
            if claim["status"] in {"rejected", "abstained"}:
                continue
            source_id = f"concept:{claim['source']}"
            target_id = f"concept:{claim['target']}"
            nodes[source_id] = {
                "id": source_id,
                "label": claim["source"],
                "kind": "concept",
            }
            nodes[target_id] = {
                "id": target_id,
                "label": claim["target"],
                "kind": "outcome",
            }
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "label": claim["relation"],
                    "status": claim["status"],
                    "confidence": claim["judge_score"],
                    "evidence_ids": claim["evidence_ids"],
                }
            )
            for paper_id in claim["evidence_ids"]:
                if not self.evidence_is_valid(paper_id):
                    continue
                resolved_paper_id = self.paper_id_for_evidence(paper_id)
                if resolved_paper_id not in self.paper_by_id:
                    continue
                paper = self.paper_by_id[resolved_paper_id]
                nodes[paper_id] = {
                    "id": paper_id,
                    "label": paper.title,
                    "kind": "paper",
                }
                edges.append(
                    {
                        "source": paper_id,
                        "target": source_id,
                        "label": "evidence",
                        "status": "accepted",
                        "confidence": 1.0,
                        "evidence_ids": [paper_id],
                    }
                )
            if include_provenance:
                for span in claim.get("evidence_spans", []):
                    span_id = f"span:{span['sentence_id']}"
                    nodes[span_id] = {
                        "id": span_id,
                        "label": span["text"],
                        "kind": "evidence_span",
                    }
                    edges.append(
                        {
                            "source": span["paper_id"],
                            "target": span_id,
                            "label": "contains",
                            "status": "accepted",
                            "confidence": 1.0,
                            "evidence_ids": [span["paper_id"]],
                        }
                    )
                    edges.append(
                        {
                            "source": span_id,
                            "target": source_id,
                            "label": span["stance"],
                            "status": (
                                "review"
                                if span["stance"] == "contradict"
                                else claim["status"]
                            ),
                            "confidence": claim["judge_score"],
                            "evidence_ids": [span["paper_id"]],
                        }
                    )
        return {"nodes": list(nodes.values()), "edges": edges}

    def extracted_paper_graph(self) -> dict[str, Any]:
        """构建由论文文本生成、而非人工三元组雕琢的证据优先图谱。"""
        if self._extracted_graph is None:
            self._extracted_graph = self.vertical_corpus.extraction_dict()
        return self._extracted_graph

    def display_graph(self) -> dict[str, Any]:
        """界面上那张"论文级图谱"该显示哪一份。

        这一次运行如果叠了用户自己导入的论文，就显示**那一份**：
        候选关系、主张与证据都来自它们，再把领域公共语料的图摆上去，
        读者会以为图里的关系是这次跑出来的。没有叠项目证据时才回落到语料图谱。
        """
        project_graph = getattr(self, "project_graph", None)
        if project_graph:
            return project_graph
        return self.extracted_paper_graph()

    def paper_id_for_evidence(self, evidence_id: str) -> str:
        if evidence_id.startswith("evidence:"):
            parts = evidence_id.split(":")
            return parts[1] if len(parts) > 1 else evidence_id
        return evidence_id

    def evidence_is_valid(self, evidence_id: str) -> bool:
        if evidence_id in self.evidence_registry:
            return True
        if evidence_id in self.vertical_corpus.paper_records:
            record = self.vertical_corpus.paper_records[evidence_id]
            return not record.get("exclude_from_evidence_graph", False)
        if evidence_id in self.paper_by_id:
            return True
        return evidence_id in self.vertical_corpus.evidence_index()

    def evidence_details(self, evidence_ids: list[str]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for evidence_id in evidence_ids:
            registered = self.evidence_registry.get(evidence_id)
            if registered is not None:
                details.append(registered)
        index = self.vertical_corpus.evidence_index()
        for evidence_id in evidence_ids:
            if evidence_id in self.evidence_registry:
                continue
            if evidence_id in index:
                details.append(index[evidence_id])
                continue
            paper = self.paper_by_id.get(evidence_id)
            if paper and self.evidence_is_valid(evidence_id):
                details.append(
                    {
                        "evidence_id": evidence_id,
                        "paper_id": paper.paper_id,
                        "section_id": "paper-level",
                        "text": paper.summary,
                        "char_start": 0,
                        "char_end": len(paper.summary),
                    }
                )
        return details

    def evidence_for_entity(self, entity_name: str) -> list[dict[str, Any]]:
        """返回某个已抽取规范实体的可追溯跨度。"""
        normalized = entity_name.casefold()
        payload = self.extracted_paper_graph()
        evidence_index = {
            item["evidence_id"]: item for item in payload["evidence"]
        }
        evidence_ids = {
            mention["evidence_id"]
            for entity in payload["entities"]
            if entity["canonical_name"].casefold() == normalized
            for mention in entity["mentions"]
        }
        return [
            evidence_index[evidence_id]
            for evidence_id in sorted(evidence_ids)
            if evidence_id in evidence_index
        ]

    def entity_mentioned_in_evidence(self, entity_name: str, evidence_id: str) -> bool:
        """Return whether an extracted entity is mentioned in a specific evidence span.

        The critic uses this instead of a canonical-name substring match so that
        entities matched via Chinese aliases are still recognised inside Chinese
        evidence text (canonical names are usually English). When mention linkage
        is unavailable for the entity, fall back to alias-aware substring matching
        against the evidence text.
        """
        normalized = entity_name.casefold()
        payload = self.extracted_paper_graph()
        for entity in payload["entities"]:
            if entity["canonical_name"].casefold() != normalized:
                continue
            mention_ids = {mention["evidence_id"] for mention in entity["mentions"]}
            if mention_ids and evidence_id in mention_ids:
                return True
            # 命中了图谱里的同名实体但这条例证不在它的 mention 里时，不能直接判否：
            # 评测集为这个名字声明过写法的话，下面那段声明优先，否则调用方会拿
            # `SCIIE` 去问、被 `SciIE` 那条问答成"没提到"。
            break
        # Entity has no mention linkage (or is absent from the extracted graph):
        # fall back to alias-aware substring matching against the evidence text.
        details = self.evidence_details([evidence_id])
        if not details:
            return False
        text = details[0].get("text", "").casefold()
        # 评测集为这个实体声明过写法时，就以声明的写法为准，不再叠 schema 里的别名表。
        # 不这么做会撞名：schema 把 `SCIIE` 列为 `SciIE` 的别名（PDF 解析会把首字母
        # 切到上一行），于是"某片段提到 SCIIE"会被判成"提到了 SciIE"，
        # 而这两条在真原文里是不同论文里的不同系统。
        overlay = self.entity_alias_overlay.get(normalized)
        if overlay is not None:
            aliases = set(overlay[1])
            if not aliases:
                aliases = {entity_name.casefold()}
            return any(alias and alias in text for alias in aliases)
        aliases = {entity_name.casefold()}
        for concept in self.schema["concepts"]:
            if concept["canonical"].casefold() == normalized:
                aliases.update(
                    alias.casefold() for alias in concept.get("aliases", [])
                )
        return any(alias and alias in text for alias in aliases)

    def entity_type_for_name(self, name: str) -> str:
        overlay = self.entity_alias_overlay.get(name.casefold())
        if overlay is not None:
            return overlay[0]
        return self.entity_type_by_name.get(name.casefold(), "")

    def relation_types_are_valid(
        self,
        relation_type: str,
        source_type: str,
        target_type: str,
    ) -> bool:
        constraints = self.schema.get("relation_constraints", {}).get(relation_type)
        if not constraints:
            return relation_type in self.schema["relation_types"]
        return (
            source_type in constraints.get("source", [])
            and target_type in constraints.get("target", [])
        )
