from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .extraction import SchemaGuidedExtractor
from .models import EvidenceSpan, LearnerProfile, Paper


QUERY_ALIASES = {
    "多智能体": ("multi-agent", "agent", "debate", "collaboration"),
    "科研": ("scientific", "research", "scholarly"),
    "幻觉": ("hallucination", "factuality", "grounding"),
    "知识图谱": ("knowledge graph", "evidence", "retrieval"),
    "争议": ("debate", "critique", "conflict"),
    "蓝海": ("discovery", "gap", "uncertainty"),
    "溯源": ("traceability", "citation", "evidence"),
}


class KnowledgeBase:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.papers = self._load_papers(root / "papers.json")
        self.relations = self._load_json(root / "relations.json")
        self.paper_by_id = {paper.paper_id: paper for paper in self.papers}

    @staticmethod
    def _load_json(path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_papers(self, path: Path) -> list[Paper]:
        return [Paper.from_dict(item) for item in self._load_json(path)]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.lower()
        terms = set(re.findall(r"[a-z0-9][a-z0-9-]+|[\u4e00-\u9fff]{2,}", lowered))
        # The standard library regex treats a complete Chinese sentence as one
        # token. Character n-grams keep the offline demo query-sensitive without
        # adding a tokenizer dependency. Formal experiments can replace this
        # with a domain tokenizer through the retrieval adapter.
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

    def candidate_relations(self, paper_ids: set[str], limit: int = 8) -> list[dict[str, Any]]:
        candidates = [
            relation
            for relation in self.relations
            if paper_ids.intersection(relation["evidence_ids"])
        ]
        candidates.sort(
            key=lambda relation: (float(relation["confidence"]), len(relation["evidence_ids"])),
            reverse=True,
        )
        return candidates[:limit]

    def evidence_spans_for_relation(
        self, relation: dict[str, Any]
    ) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        for paper_id in relation.get("evidence_ids", []):
            paper = self.paper_by_id.get(paper_id)
            if paper:
                spans.append(
                    EvidenceSpan(
                        paper_id=paper_id,
                        section="摘要",
                        sentence_id=f"{paper_id}:summary:1",
                        text=paper.summary,
                        stance="support",
                    )
                )
        for paper_id in relation.get("counter_evidence_ids", []):
            paper = self.paper_by_id.get(paper_id)
            if paper:
                spans.append(
                    EvidenceSpan(
                        paper_id=paper_id,
                        section="摘要",
                        sentence_id=f"{paper_id}:summary:1",
                        text=paper.summary,
                        stance="contradict",
                    )
                )
        return spans

    def graph_for_claims(
        self,
        claims: list[dict[str, Any]],
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
                paper = self.paper_by_id.get(paper_id)
                if paper is None:
                    continue
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
        """Build the evidence-first graph produced from paper text, not curated triples."""
        extractor = SchemaGuidedExtractor.from_path(self.root / "extraction_schema.json")
        return extractor.extract_papers(self.papers).to_dict()
