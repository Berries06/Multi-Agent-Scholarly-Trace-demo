from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERTICAL_ROOT = PROJECT_ROOT / "data" / "vertical_kb"
CACHE_PATH = VERTICAL_ROOT / "search_cache" / "crossref-candidates-2026-07-30.json"
TARGET_PAPERS = 30
CROSSREF_ENDPOINT = "https://api.crossref.org/works"
CROSSREF_TYPES = {"journal-article", "proceedings-article"}
USER_AGENT = (
    "Yanhai-Scholarly-Trace/0.3 "
    "(https://github.com/Berries06/Multi-Agent-Scholarly-Trace-demo)"
)


@dataclass(frozen=True)
class DomainSpec:
    domain_id: str
    manifest_path: Path
    queries: tuple[str, ...]
    required_groups: tuple[tuple[str, ...], ...]
    weighted_terms: dict[str, float]
    categories: tuple[str, ...]
    fallback_concept: str
    priority_dois: tuple[str, ...]


DOMAIN_SPECS = (
    DomainSpec(
        domain_id="scientific-ie-kg",
        manifest_path=VERTICAL_ROOT / "manifest.json",
        queries=(
            "scientific information extraction knowledge graph",
            "scientific literature entity relation extraction",
            "scientific document level information extraction",
            "scholarly knowledge graph construction",
        ),
        required_groups=(
            (
                "scientific",
                "scholarly",
                "research literature",
                "academic literature",
                "science",
            ),
            (
                "information extraction",
                "knowledge graph",
                "entity",
                "relation",
                "claim",
                "event extraction",
                "citation",
            ),
        ),
        weighted_terms={
            "scientific": 3.0,
            "scholarly": 3.0,
            "literature": 2.0,
            "knowledge graph": 5.0,
            "information extraction": 5.0,
            "entity extraction": 4.0,
            "named entity": 3.0,
            "relation extraction": 4.0,
            "claim": 2.0,
            "event extraction": 3.0,
            "document-level": 2.0,
            "citation": 1.0,
        },
        categories=("scientific information extraction", "knowledge graph"),
        fallback_concept="scientific information extraction",
        priority_dois=(
            "10.1109/ecis65594.2025.11086863",
            "10.1016/j.cageo.2017.12.007",
            "10.1109/ickg59574.2023.00036",
            "10.3724/2096-7004.di.2025.0175",
            "10.1007/s00799-021-00313-y",
            "10.5220/0012260300003598",
            "10.1109/anthology.2013.6784932",
            "10.18653/v1/2026.findings-acl.1657",
            "10.1016/j.ipm.2020.102309",
            "10.1109/icoict66265.2025.11193072",
            "10.1145/3460210.3493582",
            "10.31763/businta.v8i2.657",
            "10.1145/3383583.3398530",
            "10.18653/v1/2025.wasp-main.4",
            "10.1109/s.a.i.ence50533.2020.9303196",
            "10.1016/j.neunet.2025.107250",
            "10.3390/math12091349",
            "10.52825/cordi.v1i.272",
            "10.1109/icsc.2018.00045",
            "10.1117/12.3111111",
            "10.1109/icbda65366.2025.11211295",
            "10.18653/v1/2021.semeval-1.175",
        ),
    ),
    DomainSpec(
        domain_id="materials-discovery-gnn",
        manifest_path=(
            VERTICAL_ROOT
            / "domains"
            / "materials-discovery-gnn"
            / "manifest.json"
        ),
        queries=(
            "graph neural network materials property prediction",
            "crystal graph neural network materials discovery",
            "machine learning interatomic potential graph neural network",
            "machine learning materials discovery high throughput",
        ),
        required_groups=(
            ("material", "materials", "crystal", "molecular", "interatomic"),
            (
                "graph neural",
                "graph network",
                "machine learning",
                "deep learning",
                "property prediction",
                "materials discovery",
                "interatomic potential",
            ),
        ),
        weighted_terms={
            "materials": 3.0,
            "material": 2.0,
            "crystal": 3.0,
            "molecular": 1.0,
            "interatomic": 3.0,
            "graph neural": 5.0,
            "graph network": 4.0,
            "machine learning": 3.0,
            "deep learning": 3.0,
            "property prediction": 4.0,
            "materials discovery": 5.0,
            "interatomic potential": 4.0,
            "high-throughput": 2.0,
        },
        categories=("materials informatics", "machine learning"),
        fallback_concept="material property prediction",
        priority_dois=(
            "10.1021/acs.jcim.5c01460",
            "10.1103/physrevmaterials.8.033802",
            "10.1103/physrevmaterials.4.063801",
            "10.1038/s41524-021-00650-1",
            "10.1038/s41467-021-26226-7",
            "10.1109/ijcnn64981.2025.11228283",
            "10.1038/s41524-026-02131-9",
            "10.1039/d4dd00352g",
            "10.1063/5.0066061",
            "10.1016/j.mtcomm.2025.112021",
            "10.1109/bigdata50022.2020.9378060",
            "10.1007/s00521-021-06616-0",
            "10.3390/inorganics13120395",
            "10.1039/d5ce00096c",
            "10.1016/j.commatsci.2023.112655",
            "10.1016/j.commatsci.2024.113358",
            "10.1016/j.actamat.2025.121347",
            "10.1016/j.commatsci.2023.112619",
            "10.1038/s41524-024-01407-2",
            "10.1039/d3dd00233k",
            "10.1002/adma.202409175",
            "10.1016/j.commatsci.2024.112783",
            "10.1103/physrevmaterials.4.113807",
            "10.1103/physrevmaterials.4.093801",
            "10.1088/2632-2153/acf115",
        ),
    ),
    DomainSpec(
        domain_id="educational-knowledge-tracing",
        manifest_path=(
            VERTICAL_ROOT
            / "domains"
            / "educational-knowledge-tracing"
            / "manifest.json"
        ),
        queries=(
            "knowledge tracing deep learning",
            "Bayesian knowledge tracing student modeling",
            "transformer knowledge tracing",
            "knowledge tracing intelligent tutoring systems",
        ),
        required_groups=(
            ("knowledge tracing",),
            (
                "student",
                "learner",
                "education",
                "educational",
                "tutoring",
                "knowledge tracing",
            ),
        ),
        weighted_terms={
            "knowledge tracing": 8.0,
            "deep knowledge tracing": 3.0,
            "bayesian knowledge tracing": 3.0,
            "student modeling": 4.0,
            "learner": 2.0,
            "educational": 2.0,
            "intelligent tutoring": 3.0,
            "student performance": 3.0,
            "transformer": 2.0,
            "attention": 1.0,
        },
        categories=("knowledge tracing", "student modeling"),
        fallback_concept="knowledge tracing",
        priority_dois=(
            "10.1007/s11257-017-9193-2",
            "10.1016/j.knosys.2018.03.001",
            "10.1109/icdm.2018.00156",
            "10.1145/3543507.3583255",
            "10.1145/3448139.3448170",
            "10.1007/s10489-022-03621-1",
            "10.1109/tlt.2023.3254544",
            "10.1145/2883851.2883885",
            "10.1145/3303772.3303830",
            "10.1609/aaai.v36i11.21560",
            "10.1145/3231644.3231647",
            "10.1016/j.knosys.2023.111300",
            "10.1016/j.eswa.2024.124451",
            "10.1145/3051457.3053985",
            "10.1145/3051457.3053976",
            "10.1007/s11257-023-09389-4",
            "10.1145/3580595",
            "10.1109/tlt.2023.3346671",
            "10.1109/tlt.2023.3336240",
            "10.1016/j.knosys.2022.110036",
            "10.1145/3303772.3303786",
            "10.1145/3350546.3352513",
            "10.1609/aaai.v33i01.3301750",
            "10.1007/s40593-022-00297-z",
        ),
    ),
)


def _plain_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.casefold())


def _published_date(item: dict[str, Any]) -> tuple[str, int]:
    for key in ("published-print", "published-online", "published", "issued"):
        parts = item.get(key, {}).get("date-parts", [])
        if not parts or not parts[0]:
            continue
        raw_values = list(parts[0][:3])
        if not raw_values or raw_values[0] is None:
            continue
        year = int(raw_values[0])
        month = (
            int(raw_values[1])
            if len(raw_values) > 1 and raw_values[1] is not None
            else 1
        )
        day = (
            int(raw_values[2])
            if len(raw_values) > 2 and raw_values[2] is not None
            else 1
        )
        return f"{year:04d}-{month:02d}-{day:02d}", year
    return "", 0


def _authors(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for author in item.get("author", []):
        name = " ".join(
            part
            for part in (
                _plain_text(str(author.get("given", ""))),
                _plain_text(str(author.get("family", ""))),
            )
            if part
        )
        if name and name not in names:
            names.append(name)
    return names


def _crossref_request(query: str, rows: int = 80) -> list[dict[str, Any]]:
    params = urlencode(
        {
            "query.bibliographic": query,
            "rows": rows,
            "select": (
                "DOI,title,author,published,published-print,published-online,"
                "issued,container-title,type,is-referenced-by-count,URL"
            ),
        }
    )
    request = Request(
        f"{CROSSREF_ENDPOINT}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=25) as response:  # noqa: S310 - fixed host
                payload = json.load(response)
            return list(payload["message"].get("items", []))
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if isinstance(error, HTTPError) and error.code not in {
                429,
                500,
                502,
                503,
                504,
            }:
                break
            if attempt < 3:
                time.sleep(1.5 * (2**attempt))
    raise RuntimeError(f"Crossref request failed for {query!r}: {last_error}")


def _keyword_score(spec: DomainSpec, title: str) -> float:
    lowered = title.casefold()
    if not all(any(term in lowered for term in group) for group in spec.required_groups):
        return -1.0
    return sum(
        weight for term, weight in spec.weighted_terms.items() if term in lowered
    )


def _sanitize_candidate(
    spec: DomainSpec,
    item: dict[str, Any],
    query: str,
    rank: int,
) -> dict[str, Any] | None:
    if item.get("type") not in CROSSREF_TYPES:
        return None
    title_values = item.get("title") or []
    title = _plain_text(str(title_values[0])) if title_values else ""
    venue_values = item.get("container-title") or []
    venue = _plain_text(str(venue_values[0])) if venue_values else ""
    doi = str(item.get("DOI", "")).strip().lower()
    published, year = _published_date(item)
    score = _keyword_score(spec, title)
    lowered_title = title.casefold()
    excluded_markers = (
        "author correction",
        "correction:",
        "corrigendum",
        "erratum",
        "retraction",
        "retracted:",
        "withdrawn:",
        "supplementary material",
    )
    if (
        score < 5
        or not title
        or not venue
        or not doi
        or not published
        or year < 1990
        or year > 2026
        or any(marker in lowered_title for marker in excluded_markers)
    ):
        return None
    citation_count = int(item.get("is-referenced-by-count") or 0)
    return {
        "doi": doi,
        "title": title,
        "authors": _authors(item),
        "year": year,
        "published": published,
        "venue": venue,
        "type": item["type"],
        "citation_count": citation_count,
        "source_url": f"https://doi.org/{doi}",
        "query_hits": [query],
        "best_query_rank": rank,
        "keyword_score": score,
    }


def _merge_candidates(
    spec: DomainSpec,
    query_results: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_doi: dict[str, dict[str, Any]] = {}
    by_title: dict[str, str] = {}
    for query in spec.queries:
        for rank, item in enumerate(query_results.get(query, []), start=1):
            candidate = _sanitize_candidate(spec, item, query, rank)
            if candidate is None:
                continue
            normalized = _normalized_title(candidate["title"])
            key = candidate["doi"]
            if normalized in by_title:
                key = by_title[normalized]
            if key in by_doi:
                current = by_doi[key]
                if query not in current["query_hits"]:
                    current["query_hits"].append(query)
                current["best_query_rank"] = min(
                    current["best_query_rank"], rank
                )
                current["citation_count"] = max(
                    current["citation_count"], candidate["citation_count"]
                )
                current["keyword_score"] = max(
                    current["keyword_score"], candidate["keyword_score"]
                )
                continue
            by_doi[key] = candidate
            by_title[normalized] = key

    candidates = list(by_doi.values())
    for candidate in candidates:
        query_coverage = len(candidate["query_hits"])
        rank_bonus = 4.0 / math.sqrt(candidate["best_query_rank"])
        citation_bonus = min(4.0, math.log10(candidate["citation_count"] + 1))
        recency_bonus = max(0.0, candidate["year"] - 2015) * 0.04
        candidate["selection_score"] = round(
            candidate["keyword_score"]
            + 1.5 * query_coverage
            + rank_bonus
            + citation_bonus
            + recency_bonus,
            4,
        )
    candidates.sort(
        key=lambda item: (
            item["selection_score"],
            item["citation_count"],
            item["year"],
            item["title"],
        ),
        reverse=True,
    )
    return candidates


def refresh_cache() -> dict[str, Any]:
    jobs: dict[Any, tuple[str, str]] = {}
    raw_by_domain: dict[str, dict[str, list[dict[str, Any]]]] = {
        spec.domain_id: {} for spec in DOMAIN_SPECS
    }
    with ThreadPoolExecutor(max_workers=3) as executor:
        for spec in DOMAIN_SPECS:
            for query in spec.queries:
                future = executor.submit(_crossref_request, query)
                jobs[future] = (spec.domain_id, query)
        for future in as_completed(jobs):
            domain_id, query = jobs[future]
            raw_by_domain[domain_id][query] = future.result()
            print(f"fetched: {domain_id} | {query}")

    retrieved_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    payload: dict[str, Any] = {
        "provider": "Crossref REST API",
        "endpoint": CROSSREF_ENDPOINT,
        "retrieved_at": retrieved_at,
        "target_papers_per_domain": TARGET_PAPERS,
        "selection_policy": (
            "Crossref journal/proceedings records with DOI and venue; "
            "two required title-keyword groups; title/DOI deduplication; "
            "rank, query coverage, citation snapshot and recency scoring; "
            "domain-curated priority list; correction/retraction exclusion."
        ),
        "domains": {},
    }
    for spec in DOMAIN_SPECS:
        candidates = _merge_candidates(spec, raw_by_domain[spec.domain_id])
        payload["domains"][spec.domain_id] = {
            "queries": list(spec.queries),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote cache: {CACHE_PATH.relative_to(PROJECT_ROOT)}")
    return payload


def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CACHE_PATH}. Run with --refresh before --apply."
        )
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def _existing_keys(papers: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    dois: set[str] = set()
    titles: set[str] = set()
    for paper in papers:
        source_url = str(paper.get("source_url", "")).casefold()
        doi = str(paper.get("doi", "")).casefold()
        if not doi and "doi.org/" in source_url:
            doi = source_url.split("doi.org/", 1)[1]
        if doi:
            dois.add(doi)
        titles.add(_normalized_title(str(paper["title"])))
    return dois, titles


def select_new_records(
    spec: DomainSpec,
    cache: dict[str, Any],
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    existing = list(manifest["papers"])
    needed = max(0, TARGET_PAPERS - len(existing))
    existing_dois, existing_titles = _existing_keys(existing)
    candidates = cache["domains"][spec.domain_id]["candidates"]
    by_doi = {candidate["doi"]: candidate for candidate in candidates}
    missing_priority = [
        doi for doi in spec.priority_dois if doi not in by_doi
    ]
    if missing_priority:
        raise RuntimeError(
            f"{spec.domain_id}: curated DOI records missing from cache: "
            f"{missing_priority}"
        )
    priority_set = set(spec.priority_dois)
    curated_first = [by_doi[doi] for doi in spec.priority_dois]
    remaining = [
        candidate
        for candidate in candidates
        if candidate["doi"] not in priority_set
    ]
    selected: list[dict[str, Any]] = []
    for candidate in [*curated_first, *remaining]:
        if (
            candidate["doi"] in existing_dois
            or _normalized_title(candidate["title"]) in existing_titles
        ):
            continue
        selected.append(candidate)
        existing_dois.add(candidate["doi"])
        existing_titles.add(_normalized_title(candidate["title"]))
        if len(selected) == needed:
            break
    if len(selected) < needed:
        raise RuntimeError(
            f"{spec.domain_id}: only {len(selected)} eligible new records; "
            f"{needed} required."
        )
    return selected


def _concepts_for(spec: DomainSpec, title: str) -> list[str]:
    lowered = title.casefold()
    concepts = [spec.fallback_concept]
    for term in spec.weighted_terms:
        if term in lowered and term not in concepts:
            concepts.append(term)
    return concepts[:6]


def _paper_id(doi: str) -> str:
    return doi.replace("/", "-")


def _card_path(manifest_path: Path, doi: str) -> Path:
    digest = hashlib.sha1(doi.encode("utf-8")).hexdigest()[:12]
    return manifest_path.parent / "documents" / f"metadata-{digest}.md"


def _metadata_card(
    domain_name: str,
    candidate: dict[str, Any],
) -> str:
    authors = ", ".join(candidate["authors"]) or "Crossref 未提供作者字段"
    query_hits = "；".join(candidate["query_hits"])
    return (
        f"# {candidate['title']}\n\n"
        "## 书目信息\n\n"
        f"- 作者：{authors}\n"
        f"- 年份：{candidate['year']}\n"
        f"- 来源：{candidate['venue']}\n"
        f"- DOI：{candidate['doi']}\n"
        f"- Crossref 类型：{candidate['type']}\n"
        f"- 检索时引用量快照：{candidate['citation_count']}\n\n"
        "## 收录范围\n\n"
        f"本记录经 Crossref 元数据筛选纳入“{domain_name}”扩展检索层，"
        "仅用于题名、作者、来源和主题检索。项目尚未在本地持有或解析该论文全文，"
        "因此本卡片不声明论文采用了何种方法、取得了何种实验结果，也不能作为"
        "知识图谱关系的证据。\n\n"
        "## 溯源与待办\n\n"
        f"- DOI 来源：{candidate['source_url']}\n"
        f"- 命中检索式：{query_hits}\n"
        "- 元数据提供方：Crossref REST API\n"
        "- 待办：合法取得全文后执行结构解析、实体关系抽取和人工证据复核；"
        "通过前不得提升为证据层。\n"
    )


def apply_expansion(cache: dict[str, Any]) -> None:
    retrieved_on = str(cache["retrieved_at"])[:10]
    for spec in DOMAIN_SPECS:
        manifest = json.loads(spec.manifest_path.read_text(encoding="utf-8"))
        selected = select_new_records(spec, cache, manifest)
        for paper in manifest["papers"]:
            paper.setdefault("evidence_tier", "evidence_card")
            paper.setdefault("exclude_from_evidence_graph", False)

        for candidate in selected:
            card_path = _card_path(spec.manifest_path, candidate["doi"])
            card_path.parent.mkdir(parents=True, exist_ok=True)
            card_path.write_text(
                _metadata_card(manifest["domain_name"], candidate),
                encoding="utf-8",
            )
            relative_card = card_path.relative_to(spec.manifest_path.parent)
            manifest["papers"].append(
                {
                    "paper_id": _paper_id(candidate["doi"]),
                    "doi": candidate["doi"],
                    "title": candidate["title"],
                    "authors": candidate["authors"],
                    "year": candidate["year"],
                    "published": candidate["published"],
                    "venue": candidate["venue"],
                    "categories": list(spec.categories),
                    "summary": (
                        f"该论文经 Crossref 元数据筛选纳入"
                        f"“{manifest['domain_name']}”检索扩展层；"
                        "方法、实验和结论须在取得全文并完成证据抽取后写入关系图。"
                    ),
                    "concepts": _concepts_for(spec, candidate["title"]),
                    "source_url": candidate["source_url"],
                    "document_path": relative_card.as_posix(),
                    "peer_reviewed": True,
                    "peer_reviewed_status": "Crossref-type-inferred",
                    "crossref_type": candidate["type"],
                    "citation_count_snapshot": candidate["citation_count"],
                    "metadata_provider": "Crossref REST API",
                    "metadata_retrieved_on": retrieved_on,
                    "source_acquired": False,
                    "source_verified_against_original": False,
                    "knowledge_card_basis": "Crossref bibliographic metadata only",
                    "evidence_tier": "metadata_only",
                    "exclude_from_evidence_graph": True,
                }
            )

        if len(manifest["papers"]) != TARGET_PAPERS:
            raise RuntimeError(
                f"{spec.domain_id}: expected {TARGET_PAPERS}, "
                f"got {len(manifest['papers'])}"
            )
        evidence_count = sum(
            not paper.get("exclude_from_evidence_graph", False)
            for paper in manifest["papers"]
        )
        manifest["version"] = "2026-07-30"
        manifest["paper_count_target"] = TARGET_PAPERS
        manifest["evidence_tier_summary"] = {
            "evidence_cards": evidence_count,
            "metadata_only": TARGET_PAPERS - evidence_count,
            "policy": (
                "Only evidence_cards are parsed into the relation graph. "
                "Metadata-only records participate in bibliographic retrieval "
                "but cannot support graph relations."
            ),
        }
        previous_audit = manifest.get("search_audit", {})
        if previous_audit.get("provider") == cache["provider"]:
            previous_audit = previous_audit.get("previous_manual_audit", {})
        manifest["search_audit"] = {
            "searched_on": retrieved_on,
            "provider": cache["provider"],
            "queries": cache["domains"][spec.domain_id]["queries"],
            "inclusion": (
                "Crossref journal-article/proceedings-article; DOI, venue and "
                "publication date present; title passes two domain keyword groups."
            ),
            "exclusion": (
                "Books, chapters, preprints/posted content, missing DOI/venue/date, "
                "duplicate DOI/title, and off-topic title records."
            ),
            "selection": cache["selection_policy"],
            "candidate_count": cache["domains"][spec.domain_id][
                "candidate_count"
            ],
            "cache_path": CACHE_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "previous_manual_audit": previous_audit,
        }
        spec.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"expanded: {spec.domain_id} = {TARGET_PAPERS} "
            f"({evidence_count} evidence cards + "
            f"{TARGET_PAPERS - evidence_count} metadata-only)"
        )


def preview(cache: dict[str, Any]) -> None:
    for spec in DOMAIN_SPECS:
        manifest = json.loads(spec.manifest_path.read_text(encoding="utf-8"))
        selected = select_new_records(spec, cache, manifest)
        print(f"\n[{spec.domain_id}] existing={len(manifest['papers'])} new={len(selected)}")
        for index, item in enumerate(selected, start=1):
            print(
                f"{index:02d}. {item['year']} | {item['title']} | "
                f"{item['venue']} | cited={item['citation_count']} | "
                f"score={item['selection_score']} | {item['doi']}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expand each vertical scholarly corpus to 30 DOI records."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch Crossref candidates with bounded concurrency and refresh cache.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the cached, deterministic selection to manifests and cards.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cache = refresh_cache() if args.refresh else load_cache()
    preview(cache)
    if args.apply:
        apply_expansion(cache)


if __name__ == "__main__":
    main()
