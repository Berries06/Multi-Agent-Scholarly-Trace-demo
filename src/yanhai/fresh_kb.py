"""Single-paper knowledge-base adapter for the three decision agents.

The three decision agents (proposer, critic, judge) and the resource agent only
duck-type a small subset of :class:`yanhai.knowledge.KnowledgeBase`. This module
provides the same read-only contract for a freshly extracted paper, so a member
can run the full pipeline on pasted text without touching the versioned corpus.
"""

from __future__ import annotations

from typing import Any


class FreshPaperKB:
    """Wrap a single paper's extraction result into the decision agents' contract."""

    def __init__(self, extraction: dict[str, Any], schema: dict[str, Any]) -> None:
        self.schema = schema
        self.entity_by_id = {
            item["entity_id"]: item for item in extraction["entities"]
        }
        self.evidence_by_id = {
            item["evidence_id"]: item for item in extraction["evidence"]
        }
        self.relations = list(extraction["relations"])
        self.entity_type_by_name: dict[str, str] = {}
        for concept in schema["concepts"]:
            for name in {concept["canonical"], *concept.get("aliases", [])}:
                self.entity_type_by_name[name.casefold()] = concept["entity_type"]

    def candidate_relations(
        self, paper_ids: set[str], limit: int = 8
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for relation in self.relations:
            source = self.entity_by_id.get(relation["source_id"])
            target = self.entity_by_id.get(relation["target_id"])
            if source is None or target is None:
                continue
            candidates.append(
                {
                    "source": source["canonical_name"],
                    "source_type": source["entity_type"],
                    "relation": relation["relation_type"].lower(),
                    "target": target["canonical_name"],
                    "target_type": target["entity_type"],
                    "relation_type": relation["relation_type"],
                    "confidence": float(relation["confidence"]),
                    "evidence_ids": list(relation["evidence_ids"]),
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

    def evidence_is_valid(self, evidence_id: str) -> bool:
        return evidence_id in self.evidence_by_id

    def evidence_details(self, evidence_ids: list[str]) -> list[dict[str, Any]]:
        return [
            self.evidence_by_id[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in self.evidence_by_id
        ]

    def paper_id_for_evidence(self, evidence_id: str) -> str:
        span = self.evidence_by_id.get(evidence_id)
        return span["paper_id"] if span else evidence_id

    def evidence_for_entity(self, entity_name: str) -> list[dict[str, Any]]:
        normalized = entity_name.casefold()
        evidence_ids = {
            mention["evidence_id"]
            for entity in self.entity_by_id.values()
            if entity["canonical_name"].casefold() == normalized
            for mention in entity["mentions"]
        }
        return [
            self.evidence_by_id[evidence_id]
            for evidence_id in sorted(evidence_ids)
            if evidence_id in self.evidence_by_id
        ]

    def entity_mentioned_in_evidence(self, entity_name: str, evidence_id: str) -> bool:
        normalized = entity_name.casefold()
        for entity in self.entity_by_id.values():
            if entity["canonical_name"].casefold() != normalized:
                continue
            mention_ids = {mention["evidence_id"] for mention in entity["mentions"]}
            if mention_ids:
                return evidence_id in mention_ids
            break
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
        self, relation_type: str, source_type: str, target_type: str
    ) -> bool:
        constraints = self.schema.get("relation_constraints", {}).get(relation_type)
        if not constraints:
            return relation_type in self.schema["relation_types"]
        return (
            source_type in constraints.get("source", [])
            and target_type in constraints.get("target", [])
        )
