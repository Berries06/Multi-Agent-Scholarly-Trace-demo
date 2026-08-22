"""Minimal Evidence Adjudication State Graph (EASG) kernel for the R006 toy run.

This module implements the smallest deterministic slice of the C1 mechanism:
an append-only DecisionEvent stream whose current projection is recomputed by a
pure, hand-computable policy, plus a static-provenance baseline with
last-write-wins semantics and no audit history.

Scope (documented, per refine-logs/EXPERIMENT_PLAN.md Block 2):
- toy/dev only; no LLM calls, no real papers, simulation_only.
- state per claim: evidence_layer (supported|refuted|contested|unsupported)
  and admission_status (candidate|accepted|needs_review|rejected|superseded).
- events: add_support, add_refute, delete_evidence, replace_span,
  add_superseding, human_override.
- Determinism is by construction: projection() is a pure function of the
  event list, so replay yields identical projections (formal replay ×3 is
  R007 and is not claimed here).

Policy (hand-computable; single source of truth for the gold cases):

EASG recompute for claim c:
  1. Build the valid evidence set: start from add_support/add_refute events;
     delete_evidence(id) removes an id; replace_span(old, new, valid) removes
     old and, when valid=true, adds new (invalid replacement == deletion).
  2. If the newest event for c is human_override, the admission status is the
     override value and held_by_override=True (evidence_layer still computed).
  3. Else if an add_superseding(c -> d) event exists and the successor claim d
     has a non-empty valid evidence set in the store: superseded, d recorded.
  4. Else evidence_layer: any valid refute -> "contested" (with supports) or
     "refuted" (without); otherwise "supported" (with supports) or
     "unsupported" (without).
  5. Else admission via the model-independent hard guard:
     - no valid evidence                    -> rejected (no_valid_evidence)
     - absolute claim, <2 independent srcs  -> rejected (absolute_claim_weak)
     - refutes with no valid support        -> rejected (refuted_no_support)
     - refutes alongside valid supports     -> needs_review (contested)
     - >=2 independent support sources      -> accepted
     - exactly 1 support source             -> needs_review (single_source)
  6. No events at all -> candidate.

Static provenance baseline:
  - stores only current values (status, evidence ids, superseded_by).
  - build: applies the same policy once to the initial events.
  - afterwards: add_support appends; add_refute ignored; delete_evidence
    removes; replace_span swaps; add_superseding overwrites status without
    validating the successor; human_override overwrites status.
  - No recompute, no reasons, no event history (the structural gap C1 targets).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EVENT_TYPES = {
    "add_support",
    "add_refute",
    "delete_evidence",
    "replace_span",
    "add_superseding",
    "human_override",
}
ACTORS = {"proposer", "critic", "judge", "human", "retraction_notice"}
STATUSES = {"candidate", "accepted", "needs_review", "rejected", "superseded"}
EVIDENCE_LAYERS = {"supported", "refuted", "contested", "unsupported"}
STRENGTHS = {"plain", "progressive", "absolute"}


@dataclass(frozen=True)
class DecisionEvent:
    """Immutable adjudication event (C1 event schema, minimal slice)."""

    event_id: str
    claim_id: str
    event_type: str
    actor: str
    seq: int
    config_hash: str
    evidence_id: str | None = None
    evidence_span: str | None = None
    source: str | None = None
    publication_time: str | None = None
    condition: str | None = None
    semantic_strength: str | None = None
    calibrated_risk: float | None = None
    superseded_by: str | None = None
    override_status: str | None = None
    replace_valid: bool | None = None

    def validate(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event_type: {self.event_type}")
        if self.actor not in ACTORS:
            raise ValueError(f"unknown actor: {self.actor}")
        if self.override_status is not None and self.override_status not in STATUSES:
            raise ValueError(f"unknown override_status: {self.override_status}")
        if self.semantic_strength is not None and self.semantic_strength not in STRENGTHS:
            raise ValueError(f"unknown semantic_strength: {self.semantic_strength}")
        if self.event_type == "human_override" and self.override_status is None:
            raise ValueError("human_override requires override_status")
        if self.event_type == "add_superseding" and self.superseded_by is None:
            raise ValueError("add_superseding requires superseded_by")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionEvent":
        event = cls(**payload)
        event.validate()
        return event


@dataclass
class Claim:
    """Toy claim fixture: identity plus the semantics the policy needs."""

    claim_id: str
    semantic_strength: str = "plain"
    condition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _independent_sources(events: list[DecisionEvent]) -> int:
    sources = {event.source for event in events if event.source}
    return len(sources)


def _valid_evidence(
    claim_id: str, events: list[DecisionEvent]
) -> tuple[list[DecisionEvent], list[DecisionEvent]]:
    """Return (valid supports, valid refutes) in event order.

    replace_span(old, new, valid) keeps the original event type
    (support stays support, refute stays refute); an invalid replacement
    equals deletion.
    """
    by_id: dict[str, DecisionEvent] = {}
    for event in events:
        if event.claim_id != claim_id:
            continue
        if event.event_type in {"add_support", "add_refute"}:
            by_id[event.evidence_id] = event
        elif event.event_type == "delete_evidence":
            by_id.pop(event.evidence_id, None)
        elif event.event_type == "replace_span":
            original = by_id.pop(event.evidence_id, None)
            if event.replace_valid:
                replacement = DecisionEvent(
                    event_id=f"{event.event_id}:{event.evidence_id}:{event.seq}",
                    claim_id=claim_id,
                    event_type=original.event_type if original else "add_support",
                    actor=event.actor,
                    seq=event.seq,
                    config_hash=event.config_hash,
                    evidence_id=event.evidence_id,
                    evidence_span=event.evidence_span,
                    source=event.source,
                    publication_time=event.publication_time,
                    condition=event.condition,
                    semantic_strength=event.semantic_strength,
                    calibrated_risk=event.calibrated_risk,
                )
                by_id[event.evidence_id] = replacement
    supports = [
        event for event in by_id.values() if event.event_type == "add_support"
    ]
    refutes = [
        event for event in by_id.values() if event.event_type == "add_refute"
    ]
    return supports, refutes


def _has_valid_evidence(store: "EASGStore", claim_id: str) -> bool:
    supports, refutes = _valid_evidence(claim_id, store.events)
    return bool(supports or refutes)


class EASGStore:
    """Append-only event log; projections recomputed on demand."""

    def __init__(self, claims: dict[str, Claim], events: list[DecisionEvent] | None = None) -> None:
        self.claims = dict(claims)
        self.events: list[DecisionEvent] = []
        for event in events or []:
            self.append(event)

    def append(self, event: DecisionEvent) -> None:
        event.validate()
        if event.claim_id not in self.claims:
            raise ValueError(f"unknown claim_id: {event.claim_id}")
        if self.events and event.seq <= self.events[-1].seq:
            raise ValueError("event seq must be strictly increasing")
        self.events.append(event)

    def projection(self, claim_id: str) -> dict[str, Any]:
        claim = self.claims[claim_id]
        events = [event for event in self.events if event.claim_id == claim_id]
        supports, refutes = _valid_evidence(claim_id, self.events)
        reasons: list[str] = []
        evidence_layer = "unsupported"
        if refutes:
            evidence_layer = "contested" if supports else "refuted"
        elif supports:
            evidence_layer = "supported"

        latest = events[-1] if events else None
        if not events:
            return {
                "claim_id": claim_id,
                "admission_status": "candidate",
                "evidence_layer": "unsupported",
                "superseded_by": None,
                "held_by_override": False,
                "reasons": [],
            }
        if latest is not None and latest.event_type == "human_override":
            return {
                "claim_id": claim_id,
                "admission_status": latest.override_status,
                "evidence_layer": evidence_layer,
                "superseded_by": None,
                "held_by_override": True,
                "reasons": ["human_override"],
            }

        superseding = [
            event
            for event in events
            if event.event_type == "add_superseding" and event.superseded_by
        ]
        if superseding:
            newest_supersede = superseding[-1]
            if _has_valid_evidence(self, newest_supersede.superseded_by):
                return {
                    "claim_id": claim_id,
                    "admission_status": "superseded",
                    "evidence_layer": evidence_layer,
                    "superseded_by": newest_supersede.superseded_by,
                    "held_by_override": False,
                    "reasons": ["superseded_by_newer_valid_successor"],
                }
            reasons.append("superseding_event_invalid_successor_ignored")

        independent = _independent_sources(supports)
        if not supports and not refutes:
            reasons.append("no_valid_evidence")
            return {
                "claim_id": claim_id,
                "admission_status": "rejected",
                "evidence_layer": evidence_layer,
                "superseded_by": None,
                "held_by_override": False,
                "reasons": reasons,
            }
        if claim.semantic_strength == "absolute" and independent < 2:
            reasons.append("absolute_claim_weak")
            return {
                "claim_id": claim_id,
                "admission_status": "rejected",
                "evidence_layer": evidence_layer,
                "superseded_by": None,
                "held_by_override": False,
                "reasons": reasons,
            }
        if refutes and not supports:
            reasons.append("refuted_no_support")
            return {
                "claim_id": claim_id,
                "admission_status": "rejected",
                "evidence_layer": evidence_layer,
                "superseded_by": None,
                "held_by_override": False,
                "reasons": reasons,
            }
        if refutes:
            reasons.append("contested_needs_review")
            return {
                "claim_id": claim_id,
                "admission_status": "needs_review",
                "evidence_layer": evidence_layer,
                "superseded_by": None,
                "held_by_override": False,
                "reasons": reasons,
            }
        if independent >= 2:
            reasons.append("independent_multi_source")
            return {
                "claim_id": claim_id,
                "admission_status": "accepted",
                "evidence_layer": evidence_layer,
                "superseded_by": None,
                "held_by_override": False,
                "reasons": reasons,
            }
        reasons.append("single_source")
        return {
            "claim_id": claim_id,
            "admission_status": "needs_review",
            "evidence_layer": evidence_layer,
            "superseded_by": None,
            "held_by_override": False,
            "reasons": reasons,
        }

    def replay(self, claim_id: str, times: int = 3) -> list[dict[str, Any]]:
        return [self.projection(claim_id) for _ in range(times)]


class StaticProvenanceStore:
    """Current-value baseline: last-write-wins, no history, no reasons."""

    def __init__(self, claims: dict[str, Claim], events: list[DecisionEvent] | None = None) -> None:
        self.claims = dict(claims)
        self.status: dict[str, str] = {claim_id: "candidate" for claim_id in claims}
        self.evidence: dict[str, list[str]] = {claim_id: [] for claim_id in claims}
        self.superseded_by: dict[str, str | None] = {claim_id: None for claim_id in claims}
        self._easg = EASGStore(claims, [])
        for event in events or []:
            self._easg.append(event)
        for claim_id in claims:
            projection = self._easg.projection(claim_id)
            self.status[claim_id] = projection["admission_status"]
            self.superseded_by[claim_id] = projection["superseded_by"]
            supports, refutes = _valid_evidence(claim_id, self._easg.events)
            self.evidence[claim_id] = [event.evidence_id for event in supports + refutes]

    def apply(self, event: DecisionEvent) -> None:
        """Apply one post-build event with documented overwrite semantics."""
        event.validate()
        claim_id = event.claim_id
        if claim_id not in self.claims:
            raise ValueError(f"unknown claim_id: {claim_id}")
        if event.event_type == "add_support":
            self.evidence[claim_id].append(event.evidence_id)
        elif event.event_type == "add_refute":
            return  # not modeled in the static baseline
        elif event.event_type == "delete_evidence":
            if event.evidence_id in self.evidence[claim_id]:
                self.evidence[claim_id].remove(event.evidence_id)
        elif event.event_type == "replace_span":
            if event.evidence_id in self.evidence[claim_id]:
                self.evidence[claim_id].remove(event.evidence_id)
                if event.replace_valid:
                    self.evidence[claim_id].append(event.evidence_id)
        elif event.event_type == "add_superseding":
            self.status[claim_id] = "superseded"
            self.superseded_by[claim_id] = event.superseded_by
        elif event.event_type == "human_override":
            self.status[claim_id] = event.override_status

    def projection(self, claim_id: str) -> dict[str, Any]:
        return {
            "claim_id": claim_id,
            "admission_status": self.status[claim_id],
            "evidence_layer": None,
            "superseded_by": self.superseded_by[claim_id],
            "held_by_override": None,
            "reasons": [],  # structural gap: no audit history
        }


def load_claims(payload: dict[str, Any]) -> dict[str, Claim]:
    return {
        item["claim_id"]: Claim(
            claim_id=item["claim_id"],
            semantic_strength=item.get("semantic_strength", "plain"),
            condition=item.get("condition"),
        )
        for item in payload.get("claims", [])
    }


def load_events(payload: dict[str, Any]) -> list[DecisionEvent]:
    return [DecisionEvent.from_dict(item) for item in payload.get("events", [])]


def load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
