from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Claim, Document, Evidence

CLAIM_PATTERNS: list[tuple[str, str]] = [
    (r"(?P<src>[A-Za-z0-9\- ]+) improves (?P<tgt>[A-Za-z0-9\- ]+)", "improves"),
    (r"(?P<src>[A-Za-z0-9\- ]+) reduces (?P<tgt>[A-Za-z0-9\- ]+)", "reduces"),
    (r"(?P<src>[A-Za-z0-9\- ]+) predicts (?P<tgt>[A-Za-z0-9\- ]+)", "predicts"),
]


def _sentences(text: str) -> Iterable[str]:
    for raw in re.split(r"(?<=[.!?])\s+", text.strip()):
        s = raw.strip()
        if s:
            yield s


def extract_claims(documents: list[Document]) -> list[Claim]:
    claims: list[Claim] = []
    idx = 1
    for doc in documents:
        for sentence in _sentences(f"{doc.title}. {doc.abstract}"):
            lowered = sentence.lower()
            for pattern, relation in CLAIM_PATTERNS:
                match = re.search(pattern, lowered)
                if not match:
                    continue
                src = " ".join(match.group("src").split())
                tgt = " ".join(match.group("tgt").split())
                if not src or not tgt or src == tgt:
                    continue
                claims.append(
                    Claim(
                        claim_id=f"C{idx:04d}",
                        source_entity=src,
                        relation=relation,
                        target_entity=tgt,
                        claim_type="cross_document_association",
                        confidence=0.55,
                        evidence=[Evidence(doc_id=doc.doc_id, sentence=sentence)],
                    )
                )
                idx += 1
    return claims
