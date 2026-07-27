from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class Paper:
    paper_id: str
    title: str
    authors: tuple[str, ...]
    year: int
    published: str
    categories: tuple[str, ...]
    summary: str
    concepts: tuple[str, ...]
    source_url: str
    source_type: str = "scholarly"
    publisher: str = ""
    authority_tier: int = 2
    license: str = ""
    retrieved_at: str = ""
    content_hash: str = ""
    external_ids: dict[str, str] = field(default_factory=dict)
    knowledge_status: str = "candidate"
    validation_note: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Paper":
        return cls(
            paper_id=data["paper_id"],
            title=data["title"],
            authors=tuple(data["authors"]),
            year=int(data["year"]),
            published=data["published"],
            categories=tuple(data["categories"]),
            summary=data["summary"],
            concepts=tuple(data["concepts"]),
            source_url=data["source_url"],
            source_type=str(data.get("source_type", "scholarly")),
            publisher=str(data.get("publisher", "")),
            authority_tier=int(data.get("authority_tier", 2)),
            license=str(data.get("license", "")),
            retrieved_at=str(data.get("retrieved_at", "")),
            content_hash=str(data.get("content_hash", "")),
            external_ids={
                str(key): str(value)
                for key, value in (data.get("external_ids") or {}).items()
            },
            knowledge_status=str(data.get("knowledge_status", "verified")),
            validation_note=str(data.get("validation_note", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["authors"] = list(self.authors)
        data["categories"] = list(self.categories)
        data["concepts"] = list(self.concepts)
        return data


@dataclass(slots=True, frozen=True)
class LearnerProfile:
    profile_id: str
    name: str
    persona: str
    education: str
    role: str
    goal: str
    interests: tuple[str, ...]
    knowledge_scores: dict[str, int]
    preferred_style: str
    expected_difficulty: int
    required_concepts: tuple[str, ...]
    synthetic: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LearnerProfile":
        return cls(
            profile_id=data["profile_id"],
            name=data["name"],
            persona=data["persona"],
            education=data["education"],
            role=data["role"],
            goal=data["goal"],
            interests=tuple(data["interests"]),
            knowledge_scores={key: int(value) for key, value in data["knowledge_scores"].items()},
            preferred_style=data["preferred_style"],
            expected_difficulty=int(data["expected_difficulty"]),
            required_concepts=tuple(data["required_concepts"]),
            synthetic=bool(data.get("synthetic", True)),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "persona": self.persona,
            "education": self.education,
            "role": self.role,
            "goal": self.goal,
            "interests": list(self.interests),
            "knowledge_scores": dict(self.knowledge_scores),
            "preferred_style": self.preferred_style,
            "expected_difficulty": self.expected_difficulty,
            "synthetic": self.synthetic,
        }


@dataclass(slots=True, frozen=True)
class EvidenceSpan:
    paper_id: str
    section: str
    sentence_id: str
    text: str
    stance: str = "support"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class Claim:
    claim_id: str
    source: str
    relation: str
    target: str
    relation_type: str
    base_confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)
    counter_evidence_ids: list[str] = field(default_factory=list)
    criticisms: list[str] = field(default_factory=list)
    debate_views: list[dict[str, Any]] = field(default_factory=list)
    falsification_steps: list[dict[str, Any]] = field(default_factory=list)
    judge_score: float = 0.0
    status: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "relation_type": self.relation_type,
            "base_confidence": round(self.base_confidence, 3),
            "evidence_ids": list(self.evidence_ids),
            "evidence_spans": [span.to_dict() for span in self.evidence_spans],
            "counter_evidence_ids": list(self.counter_evidence_ids),
            "criticisms": list(self.criticisms),
            "debate_views": list(self.debate_views),
            "falsification_steps": list(self.falsification_steps),
            "judge_score": round(self.judge_score, 3),
            "status": self.status,
        }


@dataclass(slots=True, frozen=True)
class AgentTrace:
    agent: str
    role: str
    status: str
    summary: str
    duration_ms: float
    input_count: int = 0
    output_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
