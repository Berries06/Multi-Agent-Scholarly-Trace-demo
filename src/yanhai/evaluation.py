from __future__ import annotations

from .models import Claim


def evaluate_against_gold(predicted_claims: list[Claim], gold_triples: list[tuple[str, str, str]]) -> dict:
    predicted = {
        (c.source_entity, c.relation, c.target_entity)
        for c in predicted_claims
        if c.status in {"accepted", "review", "contested"}
    }
    gold = set(gold_triples)

    tp = len(predicted & gold)
    fp = len(predicted - gold)
    fn = len(gold - predicted)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "predicted_count": len(predicted),
        "gold_count": len(gold),
    }
