from __future__ import annotations

import json
import re
from dataclasses import replace
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
        self.candidate_by_id: dict[str, Paper] = {}

    @staticmethod
    def _load_json(path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_papers(self, path: Path) -> list[Paper]:
        return [Paper.from_dict(item) for item in self._load_json(path)]

    def stage_candidates(self, papers: list[Paper]) -> list[dict[str, Any]]:
        """Add live or uploaded sources to the in-memory candidate zone."""
        staged: list[dict[str, Any]] = []
        for paper in papers:
            if paper.paper_id in self.paper_by_id:
                staged.append(
                    {"paper_id": paper.paper_id, "status": "already_verified"}
                )
                continue
            candidate = replace(
                paper,
                knowledge_status="candidate",
                validation_note="等待来源与证据复核",
            )
            self.candidate_by_id[candidate.paper_id] = candidate
            staged.append(
                {"paper_id": candidate.paper_id, "status": "candidate"}
            )
        return staged

    def promote_candidate(
        self,
        paper_id: str,
        validation_note: str,
    ) -> Paper:
        """Promote a reviewed candidate into the verified local zone."""
        if not validation_note.strip():
            raise ValueError("Promoting a candidate requires a validation note.")
        try:
            candidate = self.candidate_by_id.pop(paper_id)
        except KeyError as exc:
            raise KeyError(f"Unknown candidate paper: {paper_id}") from exc
        verified = replace(
            candidate,
            knowledge_status="verified",
            validation_note=validation_note.strip(),
        )
        self.papers.append(verified)
        self.paper_by_id[verified.paper_id] = verified
        return verified

    def knowledge_zones(self) -> dict[str, Any]:
        return {
            "verified": [paper.to_dict() for paper in self.papers],
            "candidate": [
                paper.to_dict() for paper in self.candidate_by_id.values()
            ],
            "policy": {
                "verified_usage": "可参与本地检索和正式资源生成",
                "candidate_usage": "仅供本轮联网研究或人工复核，不自动进入正式知识库",
                "persistence": "当前候选区为进程内 Demo，后续接数据库",
            },
        }

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
        """Build a concept-first graph; papers remain provenance on relation edges."""
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        def add_concept(label: str, role: str) -> str:
            node_id = f"concept:{label}"
            existing = nodes.get(node_id)
            if existing is None:
                nodes[node_id] = {
                    "id": node_id,
                    "label": label,
                    "kind": "concept",
                    "role": role,
                }
            elif existing.get("role") != role:
                existing["role"] = "both"
            return node_id

        for claim in claims:
            if claim["status"] in {"rejected", "abstained"}:
                continue
            source_id = add_concept(claim["source"], "mechanism")
            target_id = add_concept(claim["target"], "outcome")
            evidence_titles = [
                self.paper_by_id[paper_id].title
                for paper_id in claim["evidence_ids"]
                if paper_id in self.paper_by_id
            ]
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "label": claim["relation"],
                    "status": claim["status"],
                    "confidence": claim["judge_score"],
                    "evidence_ids": claim["evidence_ids"],
                    "evidence_titles": evidence_titles,
                    "evidence_spans": (
                        claim.get("evidence_spans", []) if include_provenance else []
                    ),
                    "claim_id": claim["claim_id"],
                    "criticisms": claim.get("criticisms", []),
                }
            )
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "graph_type": "paper_grounded_concept_graph",
            "language": "zh-CN",
        }
    def extracted_paper_graph(self) -> dict[str, Any]:
        """Build the evidence-first graph produced from paper text, not curated triples."""
        extractor = SchemaGuidedExtractor.from_path(self.root / "extraction_schema.json")
        return extractor.extract_papers(self.papers).to_dict()
