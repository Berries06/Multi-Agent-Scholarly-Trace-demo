"""Open scholarly and authoritative-document retrieval adapters."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Paper


ATOM = {"atom": "http://www.w3.org/2005/Atom"}
JsonGetter = Callable[[str, dict[str, str], float], dict[str, Any]]
_JSON_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 900


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strip_markup(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def _default_json_getter(
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _JSON_CACHE.get(url)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    request = Request(url, headers=headers)
    for attempt in range(2):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            with _CACHE_LOCK:
                if len(_JSON_CACHE) >= 256:
                    oldest = min(_JSON_CACHE, key=lambda key: _JSON_CACHE[key][0])
                    _JSON_CACHE.pop(oldest, None)
                _JSON_CACHE[url] = (time.monotonic(), payload)
            return payload
        except HTTPError as exc:
            if attempt == 0 and (exc.code == 429 or 500 <= exc.code < 600):
                time.sleep(0.5)
                continue
            raise
        except (TimeoutError, URLError):
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise
    raise RuntimeError("unreachable")


class SourceAdapter(Protocol):
    source_id: str

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]: ...


class ArxivRetriever:
    source_id = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _normalise_query(query: str) -> str:
        cleaned = re.sub(r"[\r\n\t]+", " ", query).strip()[:300]
        if not cleaned:
            raise ValueError("检索式不能为空。")
        if any(operator in cleaned for operator in ("all:", "ti:", "abs:", "cat:")):
            return cleaned
        words = [
            word
            for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#/-]*", cleaned)
            if word.lower() not in {"the", "and", "for", "with", "using", "design"}
        ][:10]
        if not words:
            return f'all:"{cleaned}"'
        if len(words) == 1:
            return f"all:{words[0]}"
        alternatives = " OR ".join(f"all:{word}" for word in words[1:])
        return f"all:{words[0]} AND ({alternatives})"

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        papers: list[Paper] = []
        seen: set[str] = set()
        per_query = max(2, min(4, limit))
        for raw_query in queries[:2]:
            params = urlencode(
                {
                    "search_query": self._normalise_query(raw_query),
                    "start": 0,
                    "max_results": per_query,
                    "sortBy": "relevance",
                    "sortOrder": "descending",
                }
            )
            request = Request(
                f"{self.endpoint}?{params}",
                headers={"User-Agent": "yanhai-trace/0.3"},
            )
            for attempt in range(2):
                try:
                    with urlopen(request, timeout=self.timeout_seconds) as response:
                        root = ET.fromstring(response.read())
                    break
                except (TimeoutError, URLError, HTTPError):
                    if attempt == 0:
                        time.sleep(0.5)
                        continue
                    raise
            for entry in root.findall("atom:entry", ATOM):
                identifier = entry.findtext("atom:id", default="", namespaces=ATOM).strip()
                raw_id = identifier.rsplit("/", 1)[-1]
                arxiv_id = re.sub(r"v\d+$", "", raw_id)
                paper_id = f"arxiv:{arxiv_id}"
                if not arxiv_id or paper_id in seen:
                    continue
                title = " ".join(
                    entry.findtext("atom:title", default="", namespaces=ATOM).split()
                )
                summary = " ".join(
                    entry.findtext("atom:summary", default="", namespaces=ATOM).split()
                )
                published = entry.findtext("atom:published", default="", namespaces=ATOM)
                authors = tuple(
                    name.text.strip()
                    for name in entry.findall("atom:author/atom:name", ATOM)
                    if name.text
                )
                categories = tuple(
                    item.attrib.get("term", "")
                    for item in entry.findall("atom:category", ATOM)
                    if item.attrib.get("term")
                )
                year = (
                    datetime.fromisoformat(published.replace("Z", "+00:00")).year
                    if published
                    else 0
                )
                papers.append(
                    Paper(
                        paper_id=paper_id,
                        title=title,
                        authors=authors,
                        year=year,
                        published=published,
                        categories=categories,
                        summary=summary,
                        concepts=(),
                        source_url=identifier,
                        source_type="preprint",
                        publisher="arXiv",
                        authority_tier=2,
                        license="metadata-only",
                        retrieved_at=_now(),
                        content_hash=_content_hash(title + "\n" + summary),
                        external_ids={"arxiv": arxiv_id},
                    )
                )
                seen.add(paper_id)
                if len(papers) >= limit:
                    return papers
        return papers


class OpenAlexRetriever:
    source_id = "openalex"
    endpoint = "https://api.openalex.org/works"

    def __init__(
        self,
        timeout_seconds: float = 12.0,
        getter: JsonGetter | None = None,
        api_key: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.getter = getter or _default_json_getter
        self.api_key = api_key if api_key is not None else os.environ.get("OPENALEX_API_KEY", "")

    @staticmethod
    def _abstract(inverted: Any) -> str:
        if not isinstance(inverted, dict):
            return ""
        positioned: list[tuple[int, str]] = []
        for word, positions in inverted.items():
            if not isinstance(positions, list):
                continue
            positioned.extend((int(position), str(word)) for position in positions)
        positioned.sort()
        return " ".join(word for _, word in positioned)

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        results: list[Paper] = []
        seen: set[str] = set()
        for query in queries[:2]:
            params = {
                "search": query,
                "per-page": min(6, limit),
                "select": (
                    "id,doi,title,publication_year,publication_date,authorships,"
                    "primary_location,open_access,abstract_inverted_index,topics"
                ),
            }
            if self.api_key:
                params["api_key"] = self.api_key
            payload = self.getter(
                f"{self.endpoint}?{urlencode(params)}",
                {"User-Agent": "yanhai-trace/0.3"},
                self.timeout_seconds,
            )
            for item in payload.get("results", []):
                raw_id = str(item.get("id", "")).rstrip("/").rsplit("/", 1)[-1]
                if not raw_id or raw_id in seen:
                    continue
                title = str(item.get("title") or "").strip()
                summary = self._abstract(item.get("abstract_inverted_index"))
                primary = item.get("primary_location") or {}
                landing = str(primary.get("landing_page_url") or item.get("doi") or item.get("id"))
                doi = str(item.get("doi") or "").removeprefix("https://doi.org/").lower()
                oa = item.get("open_access") or {}
                topics = tuple(
                    str(topic.get("display_name"))
                    for topic in item.get("topics", [])
                    if isinstance(topic, dict) and topic.get("display_name")
                )
                authors = tuple(
                    str((authorship.get("author") or {}).get("display_name"))
                    for authorship in item.get("authorships", [])
                    if isinstance(authorship, dict)
                    and (authorship.get("author") or {}).get("display_name")
                )
                results.append(
                    Paper(
                        paper_id=f"openalex:{raw_id}",
                        title=title,
                        authors=authors,
                        year=int(item.get("publication_year") or 0),
                        published=str(item.get("publication_date") or ""),
                        categories=topics,
                        summary=summary or title,
                        concepts=topics,
                        source_url=landing,
                        source_type="scholarly",
                        publisher=str((primary.get("source") or {}).get("display_name") or "OpenAlex"),
                        authority_tier=2,
                        license=str(oa.get("oa_status") or "metadata-only"),
                        retrieved_at=_now(),
                        content_hash=_content_hash(title + "\n" + summary),
                        external_ids={
                            key: value
                            for key, value in {"openalex": raw_id, "doi": doi}.items()
                            if value
                        },
                    )
                )
                seen.add(raw_id)
                if len(results) >= limit:
                    return results
        return results


class CrossrefRetriever:
    source_id = "crossref"
    endpoint = "https://api.crossref.org/v1/works"

    def __init__(
        self,
        timeout_seconds: float = 12.0,
        getter: JsonGetter | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.getter = getter or _default_json_getter

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        results: list[Paper] = []
        seen: set[str] = set()
        for query in queries[:2]:
            params = urlencode(
                {
                    "query.bibliographic": query,
                    "rows": min(6, limit),
                    "select": (
                        "DOI,title,author,published,abstract,URL,subject,publisher,type"
                    ),
                }
            )
            payload = self.getter(
                f"{self.endpoint}?{params}",
                {"User-Agent": "yanhai-trace/0.3"},
                self.timeout_seconds,
            )
            for item in (payload.get("message") or {}).get("items", []):
                doi = str(item.get("DOI") or "").lower()
                if not doi or doi in seen:
                    continue
                title_values = item.get("title") or []
                title = str(title_values[0] if title_values else doi)
                abstract = _strip_markup(str(item.get("abstract") or ""))
                date_parts = (
                    ((item.get("published") or {}).get("date-parts") or [[0]])[0]
                )
                year = int(date_parts[0]) if date_parts else 0
                authors = tuple(
                    " ".join(
                        part
                        for part in (
                            str(author.get("given") or "").strip(),
                            str(author.get("family") or "").strip(),
                        )
                        if part
                    )
                    for author in item.get("author", [])
                    if isinstance(author, dict)
                )
                subjects = tuple(str(value) for value in item.get("subject", []))
                results.append(
                    Paper(
                        paper_id=f"doi:{doi}",
                        title=title,
                        authors=authors,
                        year=year,
                        published="-".join(str(value) for value in date_parts),
                        categories=subjects,
                        summary=abstract or title,
                        concepts=subjects,
                        source_url=str(item.get("URL") or f"https://doi.org/{quote(doi)}"),
                        source_type="scholarly_metadata",
                        publisher=str(item.get("publisher") or "Crossref member"),
                        authority_tier=2,
                        license="metadata-only",
                        retrieved_at=_now(),
                        content_hash=_content_hash(title + "\n" + abstract),
                        external_ids={"doi": doi},
                    )
                )
                seen.add(doi)
                if len(results) >= limit:
                    return results
        return results


class SemanticScholarRetriever:
    source_id = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 12.0,
        getter: JsonGetter | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.getter = getter or _default_json_getter

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        params = urlencode(
            {
                "query": queries[0],
                "limit": min(limit, 10),
                "fields": (
                    "paperId,externalIds,title,abstract,year,url,authors,"
                    "fieldsOfStudy,openAccessPdf,publicationDate,venue"
                ),
            }
        )
        payload = self.getter(
            f"{self.endpoint}?{params}",
            {"x-api-key": self.api_key, "User-Agent": "yanhai-trace/0.3"},
            self.timeout_seconds,
        )
        results: list[Paper] = []
        for item in payload.get("data", []):
            paper_id = str(item.get("paperId") or "")
            if not paper_id:
                continue
            external = item.get("externalIds") or {}
            doi = str(external.get("DOI") or "").lower()
            oa_pdf = item.get("openAccessPdf") or {}
            title = str(item.get("title") or "")
            summary = str(item.get("abstract") or title)
            results.append(
                Paper(
                    paper_id=f"s2:{paper_id}",
                    title=title,
                    authors=tuple(
                        str(author.get("name"))
                        for author in item.get("authors", [])
                        if isinstance(author, dict) and author.get("name")
                    ),
                    year=int(item.get("year") or 0),
                    published=str(item.get("publicationDate") or ""),
                    categories=tuple(str(value) for value in item.get("fieldsOfStudy", [])),
                    summary=summary,
                    concepts=(),
                    source_url=str(oa_pdf.get("url") or item.get("url") or ""),
                    source_type="scholarly",
                    publisher=str(item.get("venue") or "Semantic Scholar"),
                    authority_tier=2,
                    license=str(oa_pdf.get("status") or "metadata-only"),
                    retrieved_at=_now(),
                    content_hash=_content_hash(title + "\n" + summary),
                    external_ids={
                        key: value
                        for key, value in {"semantic_scholar": paper_id, "doi": doi}.items()
                        if value
                    },
                )
            )
        return results


class OfficialDocsRetriever:
    source_id = "official_docs"

    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        self.documents = [
            Paper.from_dict(item)
            for item in json.loads(catalog_path.read_text(encoding="utf-8"))
        ]

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+#/-]{1,}|[\u4e00-\u9fff]{2,}", value)
        }

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        query_tokens = self._tokens(" ".join(queries))
        scored: list[tuple[int, Paper]] = []
        for document in self.documents:
            text = " ".join(
                [
                    document.title,
                    document.summary,
                    *document.categories,
                    *document.concepts,
                    document.publisher,
                ]
            )
            document_tokens = self._tokens(text)
            score = len(query_tokens & document_tokens)
            if score:
                scored.append((score, document))
        scored.sort(key=lambda item: (item[0], item[1].year), reverse=True)
        return [document for _, document in scored[:limit]]


@dataclass(slots=True)
class RetrievalReport:
    papers: list[Paper]
    attempted_sources: list[str]
    successful_sources: list[str]
    warnings: list[str]
    source_counts: dict[str, int] = field(default_factory=dict)


class MultiSourceRetriever:
    """Run independent adapters concurrently and keep partial successes."""

    source_id = "multi_source"

    def __init__(
        self,
        catalog_path: Path,
        adapters: list[SourceAdapter] | None = None,
    ) -> None:
        configuration_warnings: list[str] = []
        if adapters is None:
            adapters = [OfficialDocsRetriever(catalog_path)]
            openalex_key = os.environ.get("OPENALEX_API_KEY", "").strip()
            if openalex_key:
                adapters.append(OpenAlexRetriever(api_key=openalex_key))
            else:
                configuration_warnings.append("未配置 OpenAlex Key，已跳过该来源")
            adapters.extend([CrossrefRetriever(), ArxivRetriever()])
            semantic_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
            if semantic_key:
                adapters.append(SemanticScholarRetriever(semantic_key))
        self.adapters = adapters
        self.configuration_warnings = configuration_warnings
        self.last_report = RetrievalReport(
            papers=[],
            attempted_sources=[],
            successful_sources=[],
            warnings=list(configuration_warnings),
        )
        self._lock = threading.Lock()

    @staticmethod
    def _dedupe_key(paper: Paper) -> str:
        doi = paper.external_ids.get("doi", "").lower()
        if doi:
            return f"doi:{doi}"
        canonical = paper.external_ids.get("canonical_url") or paper.source_url
        return canonical.rstrip("/").lower() or paper.paper_id.lower()

    @staticmethod
    def _term_overlap(paper: Paper, query_text: str) -> int:
        tokens = {
            token.lower()
            for token in re.findall(
                r"[A-Za-z0-9][A-Za-z0-9.+#/-]{1,}|[\u4e00-\u9fff]{2,}",
                query_text,
            )
            if token.lower()
            not in {"and", "the", "for", "with", "using", "design", "system"}
        }
        title = paper.title.lower()
        evidence = f"{paper.title} {paper.summary} {' '.join(paper.concepts)}".lower()
        return sum(1 for token in tokens if token in evidence)

    @classmethod
    def _rank(cls, paper: Paper, query_text: str) -> tuple[int, float, int]:
        tokens = {
            token.lower()
            for token in re.findall(
                r"[A-Za-z0-9][A-Za-z0-9.+#/-]{1,}|[\u4e00-\u9fff]{2,}",
                query_text,
            )
        }
        title = paper.title.lower()
        evidence = f"{paper.title} {paper.summary} {' '.join(paper.concepts)}".lower()
        overlap = sum(3 if token in title else 1 for token in tokens if token in evidence)
        authority_bonus = max(0, 4 - paper.authority_tier) * 2
        abstract_bonus = min(2.0, len(paper.summary) / 500)
        return (
            1 if paper.authority_tier == 1 else 0,
            overlap + authority_bonus + abstract_bonus,
            paper.year,
        )

    def search(self, queries: list[str], limit: int = 8) -> list[Paper]:
        attempted = [adapter.source_id for adapter in self.adapters]
        successful: list[str] = []
        source_counts = {source_id: 0 for source_id in attempted}
        warnings: list[str] = list(self.configuration_warnings)
        collected: list[Paper] = []
        with ThreadPoolExecutor(max_workers=min(5, len(self.adapters))) as executor:
            future_by_adapter = {
                executor.submit(adapter.search, queries, max(limit, 6)): adapter
                for adapter in self.adapters
            }
            for future in as_completed(future_by_adapter):
                adapter = future_by_adapter[future]
                try:
                    results = future.result()
                except Exception as exc:
                    warnings.append(f"{adapter.source_id} 检索失败：{type(exc).__name__}")
                    continue
                source_counts[adapter.source_id] = len(results)
                successful.append(adapter.source_id)
                collected.extend(results)

        deduped: dict[str, Paper] = {}
        for paper in collected:
            key = self._dedupe_key(paper)
            previous = deduped.get(key)
            if previous is None or (
                paper.authority_tier,
                -len(paper.summary),
            ) < (
                previous.authority_tier,
                -len(previous.summary),
            ):
                deduped[key] = paper
        query_text = " ".join(queries)
        relevant = [
            paper
            for paper in deduped.values()
            if paper.authority_tier == 1 or self._term_overlap(paper, query_text) >= 2
        ]
        papers = sorted(
            relevant,
            key=lambda paper: self._rank(paper, query_text),
            reverse=True,
        )[:limit]
        with self._lock:
            self.last_report = RetrievalReport(
                papers=papers,
                attempted_sources=attempted,
                successful_sources=sorted(successful),
                warnings=warnings,
                source_counts=source_counts,
            )
        return papers
