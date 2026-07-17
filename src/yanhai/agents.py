from __future__ import annotations

from collections import defaultdict

from .models import Claim


class ProposerAgent:
    def propose(self, claims: list[Claim]) -> list[Claim]:
        return claims


class CriticAgent:
    def critique(self, claims: list[Claim]) -> list[Claim]:
        by_pair: dict[tuple[str, str], list[Claim]] = defaultdict(list)
        for claim in claims:
            by_pair[(claim.source_entity, claim.target_entity)].append(claim)

        for pair_claims in by_pair.values():
            relations = {c.relation for c in pair_claims}
            if "improves" in relations and "reduces" in relations:
                for c in pair_claims:
                    c.status = "contested"
                    c.confidence -= 0.15
                    c.notes.append("critic: possible methodological conflict")
        return claims


class JudgeAgent:
    def adjudicate(self, claims: list[Claim]) -> list[Claim]:
        support_count: dict[tuple[str, str, str], int] = defaultdict(int)
        for claim in claims:
            key = (claim.source_entity, claim.relation, claim.target_entity)
            support_count[key] += len(claim.evidence)

        for claim in claims:
            key = (claim.source_entity, claim.relation, claim.target_entity)
            support_bonus = min(0.35, 0.1 * support_count[key])
            confidence = claim.confidence + support_bonus
            if claim.status == "contested":
                confidence -= 0.1
            claim.confidence = max(0.05, min(0.99, confidence))
            if claim.confidence >= 0.7 and claim.status != "contested":
                claim.status = "accepted"
            elif claim.confidence >= 0.55:
                claim.status = "review"
            else:
                claim.status = "rejected"
        return claims
