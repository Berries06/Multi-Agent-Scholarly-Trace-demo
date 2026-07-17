from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Evidence:
    doc_id: str
    sentence: str


@dataclass(slots=True)
class Document:
    doc_id: str
    title: str
    abstract: str
    year: int
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Claim:
    claim_id: str
    source_entity: str
    relation: str
    target_entity: str
    claim_type: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    status: str = "proposed"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = round(self.confidence, 4)
        return data
