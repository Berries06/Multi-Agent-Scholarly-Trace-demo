"""Audit the frozen 100-paper corpus against primary paper sources.

The script resolves each exact title against arXiv's author-submitted corpus,
downloads the primary PDF when available, and records document hashes plus the
presence of abstract/method/conclusion/limitations sections.  It deliberately
does not turn a successful title lookup into a novelty claim.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ATOM = {"a": "http://www.w3.org/2005/Atom"}
SECTION_PATTERNS = {
    "abstract": re.compile(r"\b(abstract|summary)\b", re.IGNORECASE),
    "method": re.compile(
        r"\b(methods?|methodology|approach|model|architecture|system|framework|implementation)\b",
        re.IGNORECASE,
    ),
    "conclusion": re.compile(
        r"\b(conclusions?|discussion)\b|c\s*o\s*n\s*c\s*l\s*u\s*s\s*i\s*o\s*n\s*s?",
        re.IGNORECASE,
    ),
    "limitations": re.compile(r"\b(limitations?|future work|future directions)\b", re.IGNORECASE),
}
USER_AGENT = "yanhai-literature-audit/1.0 (research reproducibility)"
PMLR_VOLUMES = {2020: "v119", 2022: "v162", 2024: "v235"}
DIRECT_SOURCES = {
    "P097": {
        "primary_url": "https://www.nature.com/articles/s41586-025-10072-4",
        "pdf_url": "https://www.nature.com/articles/s41586-025-10072-4.pdf",
    },
    "P099": {
        "primary_url": "https://www.nature.com/articles/s41586-025-09442-9",
        "pdf_url": "",
        "html_url": "https://www.nature.com/articles/s41586-025-09442-9",
    },
}


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._parts).split())
            if text:
                self.links.append((text, self._href))
            self._href = None
            self._parts = []


class TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def fetch(url: str, timeout: int = 45, attempts: int = 4) -> bytes:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt + 1 == attempts:
                raise
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"unreachable fetch failure: {url}")


def collect_links(url: str) -> list[tuple[str, str]]:
    parser = LinkCollector()
    parser.feed(fetch(url, timeout=90).decode("utf-8", "ignore"))
    return parser.links


def best_link(title: str, links: list[tuple[str, str]], minimum: float = 0.82) -> tuple[str, float] | None:
    expected = normalize_title(title)
    candidates = [
        (SequenceMatcher(None, expected, normalize_title(text)).ratio(), href)
        for text, href in links
    ]
    if not candidates:
        return None
    score, href = max(candidates)
    return (href, score) if score >= minimum else None


def resolve_official(paper: dict[str, Any], cache: dict[str, list[tuple[str, str]]]) -> dict[str, Any] | None:
    venue = paper["venue"]
    year = paper["year"]
    if paper["id"] in DIRECT_SOURCES:
        return {
            "title": paper["title"],
            "score": 1.0,
            "abstract": "",
            **DIRECT_SOURCES[paper["id"]],
            "comment": f"direct primary source for {venue}",
            "source_status": "official_publication_resolved",
        }
    event: str | None = None
    if venue.startswith("ACL"):
        event = f"acl-{year}"
    elif venue.startswith("NAACL"):
        event = f"naacl-{year}"
    elif venue.startswith("EMNLP"):
        event = f"emnlp-{year}"
    elif venue.startswith("EACL"):
        event = f"eacl-{year}"

    if event:
        index_url = f"https://aclanthology.org/events/{event}/"
        if index_url not in cache:
            cache[index_url] = collect_links(index_url)
        links = cache[index_url]
        found = best_link(paper["title"], links)
        if found:
            href, score = found
            page_url = urllib.parse.urljoin("https://aclanthology.org", href)
            return {
                "title": paper["title"],
                "score": round(score, 4),
                "abstract": "",
                "primary_url": page_url,
                "pdf_url": page_url.rstrip("/") + ".pdf",
                "comment": f"official {venue} proceedings",
                "source_status": "official_proceedings_resolved",
            }

    if venue == "ICML" and year in PMLR_VOLUMES:
        volume = PMLR_VOLUMES[year]
        index_url = f"https://proceedings.mlr.press/{volume}/"
        if index_url not in cache:
            cache[index_url] = collect_links(index_url)
        links = cache[index_url]
        found = best_link(paper["title"], links)
        if found:
            href, score = found
            page_url = urllib.parse.urljoin(index_url, href)
            slug = page_url.rsplit("/", 1)[-1].removesuffix(".html")
            pdf_url = f"https://proceedings.mlr.press/{volume}/{slug}/{slug}.pdf"
            return {
                "title": paper["title"],
                "score": round(score, 4),
                "abstract": "",
                "primary_url": page_url,
                "pdf_url": pdf_url,
                "comment": "official PMLR proceedings",
                "source_status": "official_proceedings_resolved",
            }

    if venue.startswith("NeurIPS"):
        index_url = f"https://proceedings.neurips.cc/paper_files/paper/{year}"
        if index_url not in cache:
            cache[index_url] = collect_links(index_url)
        links = cache[index_url]
        found = best_link(paper["title"], links)
        if found:
            href, score = found
            page_url = urllib.parse.urljoin("https://proceedings.neurips.cc", href)
            pdf_url = (
                page_url.replace("/hash/", "/file/")
                .replace("-Abstract-", "-Paper-")
                .replace("-Abstract.html", "-Paper.pdf")
                .replace(".html", ".pdf")
            )
            return {
                "title": paper["title"],
                "score": round(score, 4),
                "abstract": "",
                "primary_url": page_url,
                "pdf_url": pdf_url,
                "comment": "official NeurIPS proceedings",
                "source_status": "official_proceedings_resolved",
            }
    return None


def resolve_arxiv(title: str) -> dict[str, Any] | None:
    query = urllib.parse.urlencode({"search_query": f'ti:"{title}"', "max_results": 6})
    root = ET.fromstring(fetch(f"https://export.arxiv.org/api/query?{query}"))
    expected = normalize_title(title)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for entry in root.findall("a:entry", ATOM):
        found_title = " ".join((entry.findtext("a:title", default="", namespaces=ATOM)).split())
        score = SequenceMatcher(None, expected, normalize_title(found_title)).ratio()
        links = {
            link.attrib.get("type", ""): link.attrib.get("href", "")
            for link in entry.findall("a:link", ATOM)
        }
        item = {
            "title": found_title,
            "score": round(score, 4),
            "abstract": " ".join((entry.findtext("a:summary", default="", namespaces=ATOM)).split()),
            "primary_url": entry.findtext("a:id", default="", namespaces=ATOM).replace("http://", "https://"),
            "pdf_url": links.get("application/pdf", "").replace("http://", "https://"),
            "comment": entry.findtext("{http://arxiv.org/schemas/atom}comment", default=""),
        }
        candidates.append((score, item))
    if not candidates:
        return None
    score, best = max(candidates, key=lambda pair: pair[0])
    return best if score >= 0.78 else None


def inspect_pdf(pdf_url: str) -> dict[str, Any]:
    payload = fetch(pdf_url, timeout=90)
    reader = PdfReader(io.BytesIO(payload))
    page_texts = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(page_texts)
    return {
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "pdf_bytes": len(payload),
        "pages": len(reader.pages),
        "text_chars": len(text),
        "sections_found": [name for name, pattern in SECTION_PATTERNS.items() if pattern.search(text)],
    }


def inspect_html(html_url: str) -> dict[str, Any]:
    payload = fetch(html_url, timeout=90)
    parser = TextCollector()
    parser.feed(payload.decode("utf-8", "ignore"))
    text = "\n".join(part.strip() for part in parser.parts if part.strip())
    return {
        "html_sha256": hashlib.sha256(payload).hexdigest(),
        "html_bytes": len(payload),
        "pages": None,
        "text_chars": len(text),
        "sections_found": [name for name, pattern in SECTION_PATTERNS.items() if pattern.search(text)],
    }


def audit(
    corpus_path: Path,
    *,
    delay: float,
    include_pdfs: bool,
    resume_from: Path | None = None,
) -> dict[str, Any]:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    papers = corpus["papers"]
    rows: list[dict[str, Any]] = []
    index_cache: dict[str, list[tuple[str, str]]] = {}
    previous: dict[str, dict[str, Any]] = {}
    if resume_from and resume_from.exists():
        previous_audit = json.loads(resume_from.read_text(encoding="utf-8"))
        expected_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
        if previous_audit.get("corpus_sha256") != expected_hash:
            raise ValueError("resume audit was produced from a different corpus hash")
        previous = {paper["id"]: paper for paper in previous_audit["papers"]}
    for index, paper in enumerate(papers, start=1):
        cached = previous.get(paper["id"])
        if cached and cached.get("read_status") == "targeted_sections_read":
            if cached.get("source_status") == "unresolved" and "arxiv.org" in cached.get("primary_url", ""):
                cached["source_status"] = "primary_preprint_resolved"
            rows.append(cached)
            print(f"[{index:03d}/{len(papers)}] {paper['id']} cached_targeted", flush=True)
            continue
        row = {**paper, "source_status": "unresolved", "read_status": "not_counted"}
        used_arxiv = False
        try:
            source = resolve_official(paper, index_cache)
            if source is None:
                used_arxiv = True
                source = resolve_arxiv(paper["title"])
            if source:
                row.update(source)
                if row["source_status"] == "unresolved":
                    row["source_status"] = "primary_preprint_resolved"
                if include_pdfs and (source.get("pdf_url") or source.get("html_url")):
                    if source.get("pdf_url"):
                        row.update(inspect_pdf(source["pdf_url"]))
                    else:
                        row.update(inspect_html(source["html_url"]))
                    found_sections = set(row["sections_found"])
                    has_core = {"abstract", "method"}.issubset(found_sections)
                    has_closing_boundary = bool({"conclusion", "limitations"} & found_sections)
                    row["read_status"] = (
                        "targeted_sections_read"
                        if has_core and has_closing_boundary
                        else "partial_sections_read"
                    )
                else:
                    row["read_status"] = "abstract_read"
        except Exception as exc:  # keep the ledger complete even when a source is down
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        print(f"[{index:03d}/{len(papers)}] {paper['id']} {row['read_status']}", flush=True)
        if index < len(papers):
            time.sleep(delay if used_arxiv else 0.05)

    counts = Counter(row["read_status"] for row in rows)
    return {
        "schema_version": "1.0.0",
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "paper_count": len(rows),
        "read_status_counts": dict(sorted(counts.items())),
        "novelty_claims_frozen": False,
        "papers": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("config/文献/literature_corpus_100.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/研发记录/审计/数据/百篇文献审计.json"),
    )
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--abstract-only", action="store_true")
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()

    result = audit(
        args.corpus,
        delay=args.delay,
        include_pdfs=not args.abstract_only,
        resume_from=args.resume_from,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["read_status_counts"], ensure_ascii=False), flush=True)
    print(args.output.resolve(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
