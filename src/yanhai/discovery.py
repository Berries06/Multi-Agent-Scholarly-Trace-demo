from __future__ import annotations

from collections import defaultdict
from typing import Any

from .knowledge import KnowledgeBase


class GraphInsightEngine:
    """从图谱结构推导可审计的文献脉络与未验证的研究 Idea。"""

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self.kb = knowledge_base

    def analyze(self, query: str = "") -> dict[str, Any]:
        payload = self.kb.extracted_paper_graph()
        entities = {item["entity_id"]: item for item in payload["entities"]}
        evidence = {item["evidence_id"]: item for item in payload["evidence"]}
        accepted = [
            item for item in payload["relations"] if item["status"] == "accepted"
        ]
        relations = [
            {
                **item,
                "source_label": entities[item["source_id"]]["canonical_name"],
                "source_type": entities[item["source_id"]]["entity_type"],
                "target_label": entities[item["target_id"]]["canonical_name"],
                "target_type": entities[item["target_id"]]["entity_type"],
            }
            for item in accepted
        ]
        return {
            "domain": payload["domain"],
            "timeline": self._timeline(relations, evidence),
            "research_ideas": self._research_ideas(relations),
            "graph_context": self._graph_context(query, relations),
            "warnings": [
                "研究想法由缺失边和跨论文路径生成，只是待验证假设。",
                "新颖性必须再经过联网文献检索与人工评审，不能由图结构单独证明。",
            ],
        }

    def _timeline(
        self,
        relations: list[dict[str, Any]],
        evidence: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        relations_by_paper: dict[str, list[str]] = defaultdict(list)
        evidence_ids_by_paper: dict[str, set[str]] = defaultdict(set)
        for relation in relations:
            statement = (
                f"{relation['source_label']} "
                f"{relation['relation_type']} "
                f"{relation['target_label']}"
            )
            for evidence_id in relation["evidence_ids"]:
                evidence_item = evidence.get(evidence_id)
                if not evidence_item:
                    continue
                paper_id = evidence_item["paper_id"]
                relations_by_paper[paper_id].append(statement)
                evidence_ids_by_paper[paper_id].add(evidence_id)
        timeline = []
        for paper in sorted(
            self.kb.vertical_corpus.papers,
            key=lambda item: (item.year, item.paper_id),
        ):
            timeline.append(
                {
                    "paper_id": paper.paper_id,
                    "year": paper.year,
                    "title": paper.title,
                    "source_url": paper.source_url,
                    "contributions": sorted(set(relations_by_paper[paper.paper_id]))[:4],
                    "evidence_ids": sorted(evidence_ids_by_paper[paper.paper_id]),
                }
            )
        return timeline

    @staticmethod
    def _research_ideas(
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        addresses: dict[str, list[dict[str, Any]]] = defaultdict(list)
        benchmarks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        existing_evaluations: set[tuple[str, str]] = set()
        for relation in relations:
            if relation["relation_type"] == "ADDRESSES":
                addresses[relation["target_label"]].append(relation)
            elif relation["relation_type"] == "BENCHMARKS" or (
                relation["relation_type"] == "ENABLES"
                and relation["source_type"] == "DATASET"
            ):
                benchmarks[relation["target_label"]].append(relation)
            elif relation["relation_type"] == "EVALUATES_ON":
                existing_evaluations.add(
                    (relation["source_label"], relation["target_label"])
                )

        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for task in sorted(set(addresses).intersection(benchmarks)):
            for method_relation in addresses[task]:
                for dataset_relation in benchmarks[task]:
                    method = method_relation["source_label"]
                    dataset = dataset_relation["source_label"]
                    key = (method, dataset, task)
                    if key in seen or (method, dataset) in existing_evaluations:
                        continue
                    seen.add(key)
                    evidence_ids = sorted(
                        {
                            *method_relation["evidence_ids"],
                            *dataset_relation["evidence_ids"],
                        }
                    )
                    candidates.append(
                        {
                            "idea_id": f"gap-{len(candidates) + 1:02d}",
                            "title": f"在 {dataset} 上系统评测 {method}",
                            "hypothesis": (
                                f"{method} 已用于“{task}”，而 {dataset} 也用于该任务；"
                                "图中尚无二者的 EVALUATES_ON 边，可设计统一实验验证其领域适配性。"
                            ),
                            "graph_basis": [
                                f"{method} -ADDRESSES-> {task}",
                                (
                                    f"{dataset} "
                                    f"-{dataset_relation['relation_type']}-> {task}"
                                ),
                                f"缺失：{method} -EVALUATES_ON-> {dataset}",
                            ],
                            "evidence_ids": evidence_ids,
                            "novelty_status": "unverified",
                            "next_check": "联网检索同任务论文，并由裁判比较既有工作与拟议实验差异。",
                        }
                    )
        return candidates[:5]

    @staticmethod
    def _graph_context(
        query: str,
        relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        lowered = query.casefold()
        selected = [
            relation
            for relation in relations
            if not lowered
            or any(
                token in (
                    relation["source_label"]
                    + " "
                    + relation["target_label"]
                ).casefold()
                for token in lowered.split()
            )
        ]
        if not selected:
            selected = relations
        return {
            "query": query,
            "generator_route": {
                "demo": "deterministic-graph-gap-miner",
                "planned_model": "Qwen/Qwen2.5-7B-Instruct",
                "constraint": "模型只能重写或扩展图谱候选，必须保留 graph_basis 与 evidence_ids。",
            },
            "facts": [
                {
                    "triple": [
                        item["source_label"],
                        item["relation_type"],
                        item["target_label"],
                    ],
                    "evidence_ids": item["evidence_ids"],
                }
                for item in selected[:12]
            ],
        }
