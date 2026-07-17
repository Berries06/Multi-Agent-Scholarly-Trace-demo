from __future__ import annotations

from .models import Claim


def claims_to_graph(claims: list[Claim], confidence_threshold: float = 0.55) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    for claim in claims:
        if claim.confidence < confidence_threshold:
            continue
        if claim.source_entity not in nodes:
            nodes[claim.source_entity] = {"id": claim.source_entity, "type": "concept"}
        if claim.target_entity not in nodes:
            nodes[claim.target_entity] = {"id": claim.target_entity, "type": "concept"}

        edge_type = "support"
        if claim.status == "contested":
            edge_type = "conflict"
        edges.append(
            {
                "id": claim.claim_id,
                "source": claim.source_entity,
                "target": claim.target_entity,
                "relation": claim.relation,
                "type": edge_type,
                "confidence": round(claim.confidence, 4),
                "evidence": [{"doc_id": e.doc_id, "sentence": e.sentence} for e in claim.evidence],
            }
        )

    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": edges}
