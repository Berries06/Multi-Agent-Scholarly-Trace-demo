from __future__ import annotations

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


class KnowledgeBase:
    def __init__(self, root: Path, domain_id: str | None = None) -> None:
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
        self.vertical_corpus = VerticalCorpus(
            vertical_root,
            root / "extraction_schema.json",
        )
        # Expansion slices are strictly isolated. The default slice keeps the
        # earlier multi-agent reading list for backward-compatible demos/tests.
        if selected_domain_id == self.default_domain_id:
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

    def candidate_relations(self, paper_ids: set[str], limit: int = 8) -> list[dict[str, Any]]:
        graph_candidates = self.candidate_graph_relations(paper_ids, limit=limit)
        if graph_candidates:
            return graph_candidates
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
            source = entity_by_id[relation["source_id"]]
            target = entity_by_id[relation["target_id"]]
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
        """Build the evidence-first graph produced from paper text, not curated triples."""
        if self._extracted_graph is None:
            self._extracted_graph = self.vertical_corpus.extraction_dict()
        return self._extracted_graph

    def paper_id_for_evidence(self, evidence_id: str) -> str:
        if evidence_id.startswith("evidence:"):
            parts = evidence_id.split(":")
            return parts[1] if len(parts) > 1 else evidence_id
        return evidence_id

    def evidence_is_valid(self, evidence_id: str) -> bool:
        if evidence_id in self.vertical_corpus.paper_records:
            record = self.vertical_corpus.paper_records[evidence_id]
            return not record.get("exclude_from_evidence_graph", False)
        if evidence_id in self.paper_by_id:
            return True
        return evidence_id in self.vertical_corpus.evidence_index()

    def evidence_details(self, evidence_ids: list[str]) -> list[dict[str, Any]]:
        index = self.vertical_corpus.evidence_index()
        details: list[dict[str, Any]] = []
        for evidence_id in evidence_ids:
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
        """Return traceable spans for an extracted canonical entity."""
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
            if mention_ids:
                return evidence_id in mention_ids
            break
        # Entity has no mention linkage (or is absent from the extracted graph):
        # fall back to alias-aware substring matching against the evidence text.
        details = self.evidence_details([evidence_id])
        if not details:
            return False
        text = details[0].get("text", "").casefold()
        aliases = {entity_name.casefold()}
        for concept in self.schema["concepts"]:
            if concept["canonical"].casefold() == normalized:
                aliases.update(
                    alias.casefold() for alias in concept.get("aliases", [])
                )
        return any(alias and alias in text for alias in aliases)

    def entity_type_for_name(self, name: str) -> str:
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
