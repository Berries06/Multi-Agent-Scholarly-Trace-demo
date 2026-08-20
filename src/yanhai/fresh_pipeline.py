"""Fresh-paper end-to-end pipeline, shared by the labs and the FastAPI backend.

Runs a single pasted paper through structure parsing, rule extraction, learner
diagnosis, the three decision agents and personalized resource generation, and
returns every intermediate stage for transparent inspection.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .agents import (
    CriticAgent,
    DiagnosisAgent,
    JudgeAgent,
    ProposerAgent,
    ResourceAgent,
)
from .extraction import PlainTextParser, SchemaGuidedExtractor, ScientificDocument
from .fresh_kb import FreshPaperKB
from .models import LearnerProfile, Paper


def load_schema(schema_path: Path) -> dict[str, Any]:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def run_fresh_document_pipeline(
    *,
    document: ScientificDocument,
    profile: LearnerProfile,
    schema_path: Path,
    accept_threshold: float = 0.72,
) -> dict[str, Any]:
    """Run the full pipeline on an already-parsed document (text or PDF pages)."""
    schema = load_schema(schema_path)
    extraction = SchemaGuidedExtractor.from_path(
        schema_path, accept_threshold=accept_threshold
    ).extract_documents([document]).to_dict()

    kb = FreshPaperKB(extraction, schema)
    paper = Paper(
        paper_id=document.paper_id,
        title=document.title,
        authors=(),
        year=2026,
        published="",
        categories=(),
        summary="",
        concepts=(),
        source_url=document.source_url,
    )

    diagnosis = DiagnosisAgent().diagnose(profile)

    claims = ProposerAgent().propose(kb, [paper])
    proposed_claims = [claim.to_dict() for claim in claims]

    claims = CriticAgent().critique(claims, kb)
    critiqued_claims = [claim.to_dict() for claim in claims]

    claims = JudgeAgent().adjudicate(claims, kb)
    adjudicated_claims = [claim.to_dict() for claim in claims]

    resources = ResourceAgent().generate(profile, diagnosis, claims, kb)

    accepted = [claim for claim in claims if claim.status == "accepted"]
    accepted_without_evidence = [claim for claim in accepted if not claim.evidence_ids]
    text_char_count = sum(len(text) for text in document.sections.values())
    return {
        "run_id": uuid.uuid4().hex,
        "fingerprint": {
            "paper_id": document.paper_id,
            "title": document.title,
            "text_char_count": text_char_count,
            "accept_threshold": accept_threshold,
            "profile_id": profile.profile_id,
            "schema_version": extraction["schema_version"],
        },
        "document": {
            "paper_id": document.paper_id,
            "title": document.title,
            "sections": document.sections,
        },
        "extraction": extraction,
        "diagnosis": diagnosis,
        "proposed_claims": proposed_claims,
        "critiqued_claims": critiqued_claims,
        "adjudicated_claims": adjudicated_claims,
        "resources": resources,
        "summary": {
            "entity_count": len(extraction["entities"]),
            "candidate_relation_count": len(extraction["relations"]),
            "claim_count": len(claims),
            "accepted_count": len(accepted),
            "rejected_count": sum(c.status == "rejected" for c in claims),
            "needs_review_count": sum(c.status == "needs_review" for c in claims),
            "accepted_without_evidence_count": len(accepted_without_evidence),
        },
    }


def run_fresh_paper_pipeline(
    *,
    paper_id: str,
    title: str,
    text: str,
    profile: LearnerProfile,
    schema_path: Path,
    accept_threshold: float = 0.72,
) -> dict[str, Any]:
    """Run the full pipeline on one pasted paper and return staged intermediates."""
    document = PlainTextParser().parse_text(
        text,
        paper_id=paper_id,
        fallback_title=title or paper_id,
        source_url="member-pasted-text",
    )
    return run_fresh_document_pipeline(
        document=document,
        profile=profile,
        schema_path=schema_path,
        accept_threshold=accept_threshold,
    )
