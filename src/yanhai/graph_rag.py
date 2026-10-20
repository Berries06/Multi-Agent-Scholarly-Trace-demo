from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .knowledge import QUERY_ALIASES, KnowledgeBase


ROUTE_CONFIG = {
    "literature_retrieval": {
        "route": "graph_breadth",
        "label": "论文检索 / 领域探索",
        "graphrag_analogue": "global_search",
        "description": "从相关概念与社区出发做广度展开，优先覆盖更多论文。",
        "max_depth": 2,
        "max_nodes": 18,
    },
    "analysis_reasoning": {
        "route": "graph_depth",
        "label": "分析推理 / 机制追踪",
        "graphrag_analogue": "local_search",
        "description": "锚定查询实体，沿有证据关系深挖多跳路径。",
        "max_depth": 3,
        "max_nodes": 14,
    },
    "idea_discovery": {
        "route": "hybrid_drift",
        "label": "研究 Idea / 空白发现",
        "graphrag_analogue": "drift_search",
        "description": "以相关社区扩展起点，再沿局部路径寻找缺失边与追问。",
        "max_depth": 2,
        "max_nodes": 18,
    },
}


class GraphRAGLiteEngine:
    """在本地概念图上做证据优先、受 GraphRAG 启发的检索。

    这里刻意不宣称是微软 GraphRAG 查询引擎：它保留兼容的概念
    （实体、关系、text unit、社区），同时让竞赛 demo 保持离线且确定性。
    """

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self.kb = knowledge_base

    def query(
        self,
        query: str,
        intent: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self.kb.extracted_paper_graph()
        entities = {
            item["entity_id"]: item for item in payload["entities"]
        }
        evidence = {
            item["evidence_id"]: item for item in payload["evidence"]
        }
        relations = [
            self._enrich_relation(item, entities)
            for item in payload["relations"]
            if item["status"] == "accepted"
            and item["source_id"] in entities
            and item["target_id"] in entities
        ]
        adjacency = self._adjacency(relations)
        seed_ids = self._seed_entities(query, entities, adjacency)
        route = intent["route"]
        route_config = ROUTE_CONFIG[intent["primary_intent"]]

        if route == "graph_breadth":
            traversal = self._breadth_search(
                seed_ids,
                adjacency,
                relations,
                max_depth=route_config["max_depth"],
                max_nodes=route_config["max_nodes"],
            )
        elif route == "graph_depth":
            traversal = self._depth_search(
                seed_ids,
                adjacency,
                relations,
                query=query,
                max_depth=route_config["max_depth"],
                max_nodes=route_config["max_nodes"],
            )
        else:
            traversal = self._hybrid_search(
                seed_ids,
                adjacency,
                relations,
                payload.get("communities", []),
                entities,
                query=query,
                max_nodes=route_config["max_nodes"],
            )

        selected_ids = set(traversal["node_ids"])
        selected_edges = [
            relation
            for relation in relations
            if relation["source_id"] in selected_ids
            and relation["target_id"] in selected_ids
        ]
        if not selected_edges:
            selected_edges = traversal["edges"]
        relevant_communities = self._relevant_communities(
            payload.get("communities", []),
            selected_ids,
        )
        concept_subgraph = self._concept_subgraph(
            entities,
            selected_ids,
            selected_edges,
            seed_ids,
            traversal,
        )
        recommendations = self._recommend_papers(
            query,
            selected_ids,
            selected_edges,
            entities,
            evidence,
            limit=5,
        )
        facts = [
            {
                "triple": [
                    edge["source_label"],
                    edge["relation_type"],
                    edge["target_label"],
                ],
                "confidence": edge["confidence"],
                "evidence_ids": list(edge["evidence_ids"]),
            }
            for edge in selected_edges[:10]
        ]
        return {
            "query": query,
            "intent": intent,
            "implementation": {
                "current": "graphrag-inspired-offline-baseline",
                "official_analogue": route_config["graphrag_analogue"],
                "not_claimed": "microsoft-graphrag-runtime",
                "graph_contract": [
                    "entities",
                    "relationships",
                    "text_units/evidence",
                    "communities",
                ],
            },
            "retrieval_plan": {
                "route": route,
                "label": route_config["label"],
                "reason": route_config["description"],
                "seed_count": len(seed_ids),
                "visited_concepts": len(selected_ids),
                "selected_relationships": len(selected_edges),
                "community_count": len(relevant_communities),
                "max_depth": route_config["max_depth"],
            },
            "seed_entities": [
                {
                    "entity_id": entity_id,
                    "label": entities[entity_id]["canonical_name"],
                    "entity_type": entities[entity_id]["entity_type"],
                }
                for entity_id in seed_ids
                if entity_id in entities
            ],
            "communities": relevant_communities,
            "concept_subgraph": concept_subgraph,
            "paths": traversal["paths"],
            "recommended_papers": recommendations,
            "answer": {
                "summary": self._answer_summary(
                    intent,
                    seed_ids,
                    selected_ids,
                    selected_edges,
                    recommendations,
                ),
                "facts": facts,
                "follow_up_questions": self._follow_up_questions(
                    intent["primary_intent"],
                    concept_subgraph["nodes"],
                    facts,
                ),
                "caveat": (
                    "回答骨架只使用已接收且带 evidence_ids 的图谱关系；"
                    "完整自然语言答案仍需在该上下文上生成并接受裁判复核。"
                ),
            },
        }

    @staticmethod
    def _enrich_relation(
        relation: dict[str, Any],
        entities: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            **relation,
            "source_label": entities[relation["source_id"]]["canonical_name"],
            "source_type": entities[relation["source_id"]]["entity_type"],
            "target_label": entities[relation["target_id"]]["canonical_name"],
            "target_type": entities[relation["target_id"]]["entity_type"],
        }

    @staticmethod
    def _adjacency(
        relations: list[dict[str, Any]],
    ) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        for relation in relations:
            adjacency[relation["source_id"]].append(
                (relation["target_id"], relation)
            )
            adjacency[relation["target_id"]].append(
                (relation["source_id"], relation)
            )
        for neighbours in adjacency.values():
            neighbours.sort(
                key=lambda item: (
                    float(item[1]["confidence"]),
                    item[1]["relation_type"],
                ),
                reverse=True,
            )
        return adjacency

    def _seed_entities(
        self,
        query: str,
        entities: dict[str, dict[str, Any]],
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]],
        limit: int = 4,
    ) -> list[str]:
        lowered = query.casefold()
        query_terms = self.kb._tokens(query)
        scored: list[tuple[float, int, str]] = []
        for entity_id, entity in entities.items():
            aliases = {
                entity["canonical_name"],
                *entity.get("aliases", []),
            }
            entity_text = " ".join(aliases)
            entity_terms = self.kb._tokens(entity_text)
            semantic_score = sum(
                4.0
                for key, expansions in QUERY_ALIASES.items()
                if key in query
                and any(
                    expansion.casefold() in entity_text.casefold()
                    for expansion in expansions
                )
            )
            phrase_score = sum(
                3.0
                for alias in aliases
                if len(alias) >= 3 and alias.casefold() in lowered
            )
            overlap = len(query_terms.intersection(entity_terms))
            score = semantic_score + phrase_score + float(overlap)
            if score:
                scored.append(
                    (score, len(adjacency.get(entity_id, [])), entity_id)
                )
        scored.sort(reverse=True)
        if scored:
            minimum_score = max(2.0, scored[0][0] * 0.5)
            return [
                entity_id
                for score, _, entity_id in scored
                if score >= minimum_score
            ][:limit]
        degree_ranked = sorted(
            entities,
            key=lambda entity_id: len(adjacency.get(entity_id, [])),
            reverse=True,
        )
        return degree_ranked[: min(3, limit)]

    @staticmethod
    def _breadth_search(
        seed_ids: list[str],
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]],
        relations: list[dict[str, Any]],
        *,
        max_depth: int,
        max_nodes: int,
    ) -> dict[str, Any]:
        visited: set[str] = set()
        depth_by_id: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque(
            (entity_id, 0) for entity_id in seed_ids
        )
        while queue and len(visited) < max_nodes:
            entity_id, depth = queue.popleft()
            if entity_id in visited or depth > max_depth:
                continue
            visited.add(entity_id)
            depth_by_id[entity_id] = depth
            if depth == max_depth:
                continue
            for neighbour_id, _ in adjacency.get(entity_id, []):
                if neighbour_id not in visited:
                    queue.append((neighbour_id, depth + 1))
        edges = [
            relation
            for relation in relations
            if relation["source_id"] in visited
            and relation["target_id"] in visited
        ]
        layers = [
            {
                "depth": depth,
                "entity_ids": sorted(
                    entity_id
                    for entity_id, value in depth_by_id.items()
                    if value == depth
                ),
            }
            for depth in sorted(set(depth_by_id.values()))
        ]
        return {
            "node_ids": sorted(visited),
            "edges": edges,
            "paths": [],
            "layers": layers,
        }

    def _depth_search(
        self,
        seed_ids: list[str],
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]],
        relations: list[dict[str, Any]],
        *,
        query: str,
        max_depth: int,
        max_nodes: int,
    ) -> dict[str, Any]:
        query_terms = self.kb._tokens(query)
        candidates: list[dict[str, Any]] = []

        def visit(
            current: str,
            node_path: list[str],
            edge_path: list[dict[str, Any]],
        ) -> None:
            if edge_path:
                path_terms = self.kb._tokens(
                    " ".join(
                        [
                            *(
                                edge["source_label"]
                                + " "
                                + edge["target_label"]
                                for edge in edge_path
                            )
                        ]
                    )
                )
                candidates.append(
                    {
                        "entity_ids": list(node_path),
                        "relation_ids": [
                            edge["relation_id"] for edge in edge_path
                        ],
                        "triples": [
                            [
                                edge["source_label"],
                                edge["relation_type"],
                                edge["target_label"],
                            ]
                            for edge in edge_path
                        ],
                        "evidence_ids": sorted(
                            {
                                evidence_id
                                for edge in edge_path
                                for evidence_id in edge["evidence_ids"]
                            }
                        ),
                        "score": round(
                            sum(float(edge["confidence"]) for edge in edge_path)
                            + 0.15 * len(edge_path)
                            + 0.2 * len(query_terms.intersection(path_terms)),
                            3,
                        ),
                    }
                )
            if len(edge_path) >= max_depth:
                return
            for neighbour_id, edge in adjacency.get(current, []):
                if neighbour_id in node_path:
                    continue
                visit(
                    neighbour_id,
                    [*node_path, neighbour_id],
                    [*edge_path, edge],
                )

        for seed_id in seed_ids:
            visit(seed_id, [seed_id], [])
        candidates.sort(
            key=lambda item: (
                len(item["relation_ids"]),
                item["score"],
            ),
            reverse=True,
        )
        paths = candidates[:6]
        selected_ids: list[str] = []
        for path in paths:
            for entity_id in path["entity_ids"]:
                if entity_id not in selected_ids and len(selected_ids) < max_nodes:
                    selected_ids.append(entity_id)
        if not selected_ids:
            selected_ids = seed_ids[:max_nodes]
        selected = set(selected_ids)
        selected_edges = [
            relation
            for relation in relations
            if relation["source_id"] in selected
            and relation["target_id"] in selected
        ]
        return {
            "node_ids": selected_ids,
            "edges": selected_edges,
            "paths": paths,
            "layers": [],
        }

    def _hybrid_search(
        self,
        seed_ids: list[str],
        adjacency: dict[str, list[tuple[str, dict[str, Any]]]],
        relations: list[dict[str, Any]],
        communities: list[dict[str, Any]],
        entities: dict[str, dict[str, Any]],
        *,
        query: str,
        max_nodes: int,
    ) -> dict[str, Any]:
        relevant = self._relevant_communities(communities, set(seed_ids))
        primer_ids: list[str] = list(seed_ids)
        for community in relevant[:2]:
            ranked = sorted(
                community["member_ids"],
                key=lambda entity_id: len(adjacency.get(entity_id, [])),
                reverse=True,
            )
            for entity_id in ranked[:3]:
                if entity_id in entities and entity_id not in primer_ids:
                    primer_ids.append(entity_id)
        depth_result = self._depth_search(
            primer_ids[:6],
            adjacency,
            relations,
            query=query,
            max_depth=2,
            max_nodes=max_nodes,
        )
        depth_result["primer_entity_ids"] = primer_ids[:6]
        return depth_result

    @staticmethod
    def _relevant_communities(
        communities: list[dict[str, Any]],
        selected_ids: set[str],
    ) -> list[dict[str, Any]]:
        ranked = []
        for community in communities:
            overlap = selected_ids.intersection(community["member_ids"])
            if not overlap:
                continue
            ranked.append(
                {
                    **community,
                    "matched_member_ids": sorted(overlap),
                    "match_score": round(
                        len(overlap) / max(1, len(community["member_ids"])),
                        3,
                    ),
                }
            )
        ranked.sort(
            key=lambda item: (
                len(item["matched_member_ids"]),
                item["match_score"],
            ),
            reverse=True,
        )
        return ranked

    @staticmethod
    def _concept_subgraph(
        entities: dict[str, dict[str, Any]],
        selected_ids: set[str],
        edges: list[dict[str, Any]],
        seed_ids: list[str],
        traversal: dict[str, Any],
    ) -> dict[str, Any]:
        degrees: dict[str, int] = defaultdict(int)
        for edge in edges:
            degrees[edge["source_id"]] += 1
            degrees[edge["target_id"]] += 1
        depth_by_id = {
            entity_id: layer["depth"]
            for layer in traversal.get("layers", [])
            for entity_id in layer["entity_ids"]
        }
        nodes = [
            {
                "id": entity_id,
                "label": entities[entity_id]["canonical_name"],
                "entity_type": entities[entity_id]["entity_type"],
                "confidence": entities[entity_id]["confidence"],
                "degree": degrees[entity_id],
                "is_seed": entity_id in seed_ids,
                "depth": depth_by_id.get(entity_id),
            }
            for entity_id in selected_ids
            if entity_id in entities
        ]
        nodes.sort(
            key=lambda item: (
                item["is_seed"],
                item["degree"],
                item["confidence"],
            ),
            reverse=True,
        )
        return {
            "nodes": nodes,
            "edges": [
                {
                    "id": edge["relation_id"],
                    "source": edge["source_id"],
                    "target": edge["target_id"],
                    "label": edge["relation_type"],
                    "confidence": edge["confidence"],
                    "evidence_ids": list(edge["evidence_ids"]),
                }
                for edge in edges
            ],
            "node_semantics": "knowledge_concepts_only",
        }

    def _recommend_papers(
        self,
        query: str,
        selected_ids: set[str],
        edges: list[dict[str, Any]],
        entities: dict[str, dict[str, Any]],
        evidence: dict[str, dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        score_by_paper: dict[str, float] = defaultdict(float)
        evidence_by_paper: dict[str, set[str]] = defaultdict(set)
        concept_by_paper: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            for evidence_id in edge["evidence_ids"]:
                item = evidence.get(evidence_id)
                if not item:
                    continue
                paper_id = item["paper_id"]
                score_by_paper[paper_id] += 2.0 * float(edge["confidence"])
                evidence_by_paper[paper_id].add(evidence_id)
                concept_by_paper[paper_id].update(
                    [edge["source_label"], edge["target_label"]]
                )
        for entity_id in selected_ids:
            entity = entities.get(entity_id)
            if not entity:
                continue
            for mention in entity.get("mentions", []):
                item = evidence.get(mention["evidence_id"])
                if not item:
                    continue
                paper_id = item["paper_id"]
                score_by_paper[paper_id] += 0.35
                evidence_by_paper[paper_id].add(mention["evidence_id"])
                concept_by_paper[paper_id].add(entity["canonical_name"])
        query_terms = self.kb._tokens(query)
        for paper_id in list(score_by_paper):
            paper = self.kb.paper_by_id.get(paper_id)
            if not paper:
                continue
            paper_terms = self.kb._tokens(
                " ".join([paper.title, paper.summary, *paper.concepts])
            )
            score_by_paper[paper_id] += 0.4 * len(
                query_terms.intersection(paper_terms)
            )
            score_by_paper[paper_id] += 0.01 * max(0, paper.year - 2020)
        ranked = sorted(
            score_by_paper,
            key=lambda paper_id: (
                score_by_paper[paper_id],
                self.kb.paper_by_id[paper_id].year,
            ),
            reverse=True,
        )
        return [
            {
                **self.kb.paper_by_id[paper_id].to_dict(),
                "retrieval_score": round(score_by_paper[paper_id], 3),
                "matched_concepts": sorted(concept_by_paper[paper_id])[:6],
                "evidence_ids": sorted(evidence_by_paper[paper_id])[:8],
                "recommendation_reason": (
                    f"命中 {len(concept_by_paper[paper_id])} 个查询子图概念，"
                    f"关联 {len(evidence_by_paper[paper_id])} 个可追溯证据跨度。"
                ),
            }
            for paper_id in ranked[:limit]
            if paper_id in self.kb.paper_by_id
        ]

    @staticmethod
    def _answer_summary(
        intent: dict[str, Any],
        seed_ids: list[str],
        selected_ids: set[str],
        selected_edges: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
    ) -> str:
        if intent["route"] == "graph_breadth":
            action = "按社区和相邻概念做广度探索"
        elif intent["route"] == "graph_depth":
            action = "沿实体关系与原文证据做多跳深挖"
        else:
            action = "先用社区扩展起点，再沿局部关系寻找缺失边"
        return (
            f"系统识别为“{intent['label']}”，{action}；"
            f"从 {len(seed_ids)} 个种子概念扩展到 {len(selected_ids)} 个概念、"
            f"{len(selected_edges)} 条已接收关系，并推荐 {len(recommendations)} 篇论文。"
        )

    @staticmethod
    def _follow_up_questions(
        primary_intent: str,
        nodes: list[dict[str, Any]],
        facts: list[dict[str, Any]],
    ) -> list[str]:
        labels = [item["label"] for item in nodes[:3]]
        if primary_intent == "literature_retrieval":
            return [
                f"{label} 在不同数据集上的评测结论是否一致？"
                for label in labels[:2]
            ] + ["是否需要按年份、方法或数据集继续筛选论文？"]
        if primary_intent == "analysis_reasoning":
            questions = [
                f"关系“{fact['triple'][0]} → {fact['triple'][2]}”的适用条件是什么？"
                for fact in facts[:2]
            ]
            return questions + ["哪些关系目前只有单一论文证据，需要交叉验证？"]
        return [
            f"{label} 是否存在尚未覆盖的数据集或任务？"
            for label in labels[:2]
        ] + ["缺失边是否已被近期论文研究，需要怎样设计新颖性检索？"]
