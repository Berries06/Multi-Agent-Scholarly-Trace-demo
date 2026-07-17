from __future__ import annotations

import json
from pathlib import Path

from .models import Document


def load_documents(jsonl_path: Path) -> list[Document]:
    docs: list[Document] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            payload = json.loads(line)
            docs.append(
                Document(
                    doc_id=payload["doc_id"],
                    title=payload["title"],
                    abstract=payload["abstract"],
                    year=int(payload["year"]),
                    keywords=payload.get("keywords", []),
                )
            )
    return docs


def load_gold_triples(jsonl_path: Path) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            payload = json.loads(line)
            triples.append((payload["source"], payload["relation"], payload["target"]))
    return triples
