from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import PyPDFParser, SchemaGuidedExtractor  # noqa: E402
from yanhai.store import KnowledgeGraphStore  # noqa: E402


def main() -> None:
    manifest = json.loads(
        (PROJECT_ROOT / "data" / "vertical_kb" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    parser = PyPDFParser()
    documents = []
    missing = []
    for paper in manifest["papers"]:
        path = PROJECT_ROOT / paper["local_pdf"]
        if not path.exists():
            missing.append(str(path.relative_to(PROJECT_ROOT)))
            continue
        documents.append(
            parser.parse(
                path,
                paper_id=paper["paper_id"],
                source_url=paper["source_url"],
                title=paper["title"],
            )
        )
    if not documents:
        raise SystemExit(
            "No local PDFs found. Run scripts/fetch_vertical_corpus.py first."
        )

    extractor = SchemaGuidedExtractor.from_path(
        PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
    )
    payload = extractor.extract_documents(documents).to_dict()
    payload["domain"] = {
        "domain_id": manifest["domain_id"],
        "domain_name": manifest["domain_name"],
        "version": manifest["version"],
        "paper_count": len(documents),
        "source_mode": "local-pdf-pypdf",
    }
    output_root = PROJECT_ROOT / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    graph_path = output_root / "fulltext-knowledge-graph.json"
    graph_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store_counts = KnowledgeGraphStore(
        output_root / "fulltext-knowledge.db"
    ).rebuild(payload)
    print(
        json.dumps(
            {
                "graph_path": str(graph_path),
                "documents": len(documents),
                "missing": missing,
                "sections": sum(len(item.sections) for item in documents),
                "quality": payload["audit"]["quality"],
                "sqlite": store_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
