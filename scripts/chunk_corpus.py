"""Sentence-level corpus chunker with global char offsets.

Design (docs/研发记录/文献管线升级方案_2026-08-23.md C1-C3):
- 切分单元 = 句子级 span（带全局字符偏移），块 = 连续 N 句（默认 8、重叠 1），
  绝不割裂句子；
- 每块元数据：paper_id / section / sentence_ids / char_start / char_end；
- 疑似表格/图表块打 needs_human_ocr=true（不猜内容）。

用法:
  python scripts/chunk_corpus.py --text tmp/paper.txt --paper-id arxiv-1234 [--section-title 摘要]
  python scripts/chunk_corpus.py --pdf tmp/paper.pdf --paper-id arxiv-1234
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from yanhai.extraction import PlainTextParser  # noqa: E402

SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])\s*|\n+")
TABLE_FIGURE_HINT = re.compile(r"^(表|图|Table|Figure)\s*\d", re.MULTILINE)
DIGIT_DENSE = re.compile(r"\d")


def split_sentences(text: str) -> list[dict[str, Any]]:
    """Return sentence spans with global char offsets; boundaries never split a sentence."""
    sentences: list[dict[str, Any]] = []
    position = 0
    for part in SENTENCE_BOUNDARY.split(text):
        segment = part.strip()
        if not segment:
            continue
        start = text.find(segment, position)
        if start == -1:  # defensive: exact text preserved
            start = position
        sentences.append(
            {
                "text": segment,
                "char_start": start,
                "char_end": start + len(segment),
            }
        )
        position = start + len(segment)
    return sentences


def needs_ocr_flag(block_text: str) -> bool:
    if TABLE_FIGURE_HINT.search(block_text):
        return True
    digits = len(DIGIT_DENSE.findall(block_text))
    return digits / max(len(block_text), 1) > 0.25


def chunk_sections(
    sections: dict[str, str],
    paper_id: str,
    block_size: int = 8,
    overlap: int = 1,
) -> list[dict[str, Any]]:
    """Chunk one paper (sections) into sentence-aligned blocks with metadata."""
    blocks: list[dict[str, Any]] = []
    for section_name, text in sections.items():
        sentences = split_sentences(text)
        if not sentences:
            continue
        sentence_ids = [
            f"{paper_id}::{section_name}::s{i}" for i in range(len(sentences))
        ]
        index = 0
        while index < len(sentences):
            window = sentences[index : index + block_size]
            block_text = "\n".join(item["text"] for item in window)
            blocks.append(
                {
                    "paper_id": paper_id,
                    "section": section_name,
                    "sentence_ids": sentence_ids[index : index + block_size],
                    "char_start": window[0]["char_start"],
                    "char_end": window[-1]["char_end"],
                    "needs_human_ocr": needs_ocr_flag(block_text),
                    "text": block_text,
                }
            )
            index += block_size - overlap
            if overlap >= block_size:  # defensive: avoid infinite loop
                index += 1
    return blocks


def chunk_document(
    paper_id: str, sections: dict[str, str], block_size: int = 8, overlap: int = 1
) -> dict[str, Any]:
    blocks = chunk_sections(sections, paper_id, block_size, overlap)
    return {
        "paper_id": paper_id,
        "schema": "sentence-aligned-chunks-v1",
        "block_size": block_size,
        "overlap": overlap,
        "chunk_count": len(blocks),
        "chunks": blocks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=Path)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--block-size", type=int, default=8)
    parser.add_argument("--overlap", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    sections: dict[str, str]
    if args.text:
        document = PlainTextParser().parse_text(
            args.text.read_text(encoding="utf-8"),
            paper_id=args.paper_id,
            fallback_title=args.paper_id,
            source_url="local-text",
        )
        sections = document.sections
    elif args.pdf:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(args.pdf.read_bytes()))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        sections = {"fulltext": text}
    else:
        raise SystemExit("需要 --text 或 --pdf 之一。")

    result = chunk_document(args.paper_id, sections, args.block_size, args.overlap)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
        print(args.output)
    else:
        print(payload)
    print(f"chunks: {result['chunk_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
