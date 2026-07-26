from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.extraction import DoclingParser, SchemaGuidedExtractor  # noqa: E402
from yanhai.knowledge import KnowledgeBase  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract evidence-grounded entities and relations from papers."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional PDF/DOCX file. Requires the optional Docling dependency.",
    )
    parser.add_argument("--paper-id", help="Stable identifier for --input.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "extracted_graph.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    extractor = SchemaGuidedExtractor.from_path(
        PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"
    )
    if args.input:
        document = DoclingParser().parse(args.input, paper_id=args.paper_id)
        result = extractor.extract_documents([document])
    else:
        knowledge_base = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        result = extractor.extract_papers(knowledge_base.papers)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    print(json.dumps(result.audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
