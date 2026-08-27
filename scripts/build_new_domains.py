"""Build two new vertical corpora (single-cell transcriptomics & quantum computing)
from OpenAlex, with top-journal ISSN filtering, abstract reconstruction and
evidence-card generation.

Usage:
    python scripts/build_new_domains.py --fetch     # retrieve & cache candidates
    python scripts/build_new_domains.py --apply     # generate manifests + cards
    python scripts/build_new_domains.py             # both
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERTICAL_ROOT = PROJECT_ROOT / "data" / "vertical_kb"
CACHE_DIR = VERTICAL_ROOT / "search_cache"
OPENALEX_ENDPOINT = "https://api.openalex.org/works"
USER_AGENT = "Yanhai-Scholarly-Trace/0.5 (mailto:research@yanhai-trace.local)"
TARGET_PER_DOMAIN = 100
PER_PAGE = 200

# ---------------------------------------------------------------------------
# Domain specifications
# ---------------------------------------------------------------------------

DOMAIN_SPECS: list[dict[str, Any]] = [
    {
        "domain_id": "single-cell-transcriptomics",
        "domain_name": "单细胞转录组数据分析",
        "version": "2026-08-26",
        "description": "生物信息学切片：追踪单细胞 RNA-seq 分析方法、数据整合、细胞类型注释与轨迹推断路线。",
        "query_example": "请沿知识图谱分析单细胞转录组数据分析方法如何演进，并推荐关键论文。",
        "categories": ["single-cell transcriptomics", "bioinformatics"],
        "fallback_concept": "single-cell RNA-seq",
        "queries": [
            "single-cell RNA-seq analysis method",
            "single-cell transcriptomics data integration",
            "single-cell cell type annotation deep learning",
            "single-cell trajectory inference RNA velocity",
            "single-cell multimodal integration foundation model",
        ],
        # Top journals (print / electronic ISSN)
        "issns": [
            "1548-7091", "1548-7105",  # Nature Methods
            "0092-8674", "1097-4172",  # Cell
            "1087-0156", "1546-1696",  # Nature Biotechnology
            "1474-7596", "1474-760X",  # Genome Biology
            "2041-1723",               # Nature Communications
            "0036-8075", "1095-9203",  # Science
            "1061-4036", "1546-1718",  # Nature Genetics
            "1088-9051", "1549-5469",  # Genome Research
            "0028-0836", "1476-4687",  # Nature
            "1744-4292",               # Molecular Systems Biology
            "0305-1048", "1362-4962",  # Nucleic Acids Research
            "1367-4803", "1367-4811",  # Bioinformatics
            "2041-1723",               # Nat Commun (dup harmless)
        ],
        "weighted_terms": {
            "single-cell": 5.0, "single cell": 5.0, "scrna": 5.0,
            "single-cell rna": 6.0, "transcriptom": 4.0,
            "data integration": 3.0, "cell type": 3.0,
            "trajectory": 2.0, "rna velocity": 3.0,
            "clustering": 2.0, "annotation": 2.0,
            "multimodal": 2.0, "foundation model": 2.0,
            "deep learning": 2.0, "variational": 1.0,
            "spatial transcriptom": 4.0, "batch correction": 3.0,
            "normalization": 2.0, "imputation": 2.0,
            "dimensionality reduction": 2.0, "differential expression": 2.0,
            "cell-cell communication": 3.0, "gene regulatory network": 2.0,
            "atlas": 2.0, "denois": 2.0, "alignment": 1.0,
        },
        # Title OR abstract must contain at least one of these.
        "required_terms": [
            "single-cell", "single cell", "scrna", "single nucleus",
            "spatial transcriptom", "single-cell transcriptom",
            "single-cell rna", "single cell rna",
        ],
        # Exclude if title contains any of these off-topic markers.
        "excluded_terms": [
            "protein-protein interaction", "string database",
            "genome assembly", "reference genome",
            "methylation clock", "aging clock",
            "gwas", "genome-wide association",
            "covid-19", "sars-cov", "coronavirus",
            "retinal image", "wheat", "plant transcriptom",
            "bacterial transcriptom", "metabolom",
            "long-read sequencing", "x chromosome inactivation",
            "psychiatric", "gene set enrichment", "gsea",
            "tumour purity", "tumor purity",
            "coding potential", "rna-binding protein",
            "chromatin architecture reorganization",
            "somatic mutation profile", "copy number",
            "pan-cancer", "m6a", "n6-methyladenosine",
            "metabolic network", "protein subcellular localization",
            "phylogenom", "gene duplication",
            "immune cell infiltration", "timer",
            "expression profiling web", "gepia",
            "tumor-infiltrating", "fibrotic niche",
            "oligodendroglioma", "microglia identity",
            "brain development", "neuropsychiatric",
            "heart", "lung from single-cell",  # tissue atlas without method focus
        ],
    },
    {
        "domain_id": "quantum-computing",
        "domain_name": "量子计算与量子信息处理",
        "version": "2026-08-26",
        "description": "物理学切片：追踪超导量子处理器、量子纠错、量子优势与变分量子算法路线。",
        "query_example": "请沿知识图谱分析量子计算硬件与量子纠错如何发展，并推荐关键论文。",
        "categories": ["quantum computing", "quantum information"],
        "fallback_concept": "quantum computing",
        "queries": [
            "quantum computing superconducting processor",
            "quantum error correction surface code",
            "quantum supremacy advantage experiment",
            "variational quantum algorithm eigensolver",
            "quantum simulation trapped ion qubit",
        ],
        "issns": [
            "0028-0836", "1476-4687",  # Nature
            "0036-8075", "1095-9203",  # Science
            "0031-9007", "1079-7114",  # Physical Review Letters
            "1745-2473", "1745-2481",  # Nature Physics
            "2691-3399",               # PRX Quantum
            "2056-6387",               # npj Quantum Information
            "2469-9926", "2469-9934",  # Physical Review A
            "2643-1564",               # Physical Review Research
            "2375-2548",               # Science Advances
            "2041-1723",               # Nature Communications
            "0034-6861", "1539-0755",  # Reviews of Modern Physics
            "2160-3308",               # Physical Review X
            "2522-5820",               # Nature Reviews Physics
        ],
        "weighted_terms": {
            "quantum comput": 6.0, "quantum processor": 5.0,
            "qubit": 4.0, "superconducting": 3.0,
            "quantum error correction": 6.0, "surface code": 4.0,
            "quantum supremacy": 5.0, "quantum advantage": 5.0,
            "variational quantum": 4.0, "quantum simulation": 3.0,
            "trapped ion": 3.0, "quantum gate": 3.0,
            "quantum circuit": 2.0, "decoherence": 2.0,
            "logical qubit": 3.0, "fault tolerant": 3.0,
            "error mitigation": 3.0, "quantum algorithm": 4.0,
            "quantum neural network": 3.0, "boson sampling": 3.0,
            "quantum memory": 2.0, "quantum network": 2.0,
            "quantum key distribution": 2.0, "ansatz": 2.0,
            "transmon": 3.0, "rydberg": 2.0, "neutral atom": 2.0,
            "spin qubit": 3.0, "quantum dot": 2.0,
        },
        "required_terms": [
            "quantum comput", "quantum processor", "quantum circuit",
            "qubit", "quantum algorithm", "quantum error",
            "quantum simulation", "quantum supremacy", "quantum advantage",
            "variational quantum", "quantum gate", "quantum neural",
            "boson sampling", "quantum memory", "logical qubit",
            "fault tolerant", "quantum information",
        ],
        "excluded_terms": [
            "nanocavity", "waveguide quantum electrodynamics",
            "photon-mediated interaction", "quantum emitter",
        ],
    },
]


# ---------------------------------------------------------------------------
# OpenAlex helpers
# ---------------------------------------------------------------------------

def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, pos_list in inverted.items():
        for pos in pos_list:
            positions.append((pos, word))
    positions.sort()
    return " ".join(word for _, word in positions)


def _openalex_request(url: str) -> dict[str, Any]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(req, timeout=30) as response:  # noqa: S310
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503, 504}:
                break
            if attempt < 3:
                time.sleep(2.0 * (2**attempt))
    raise RuntimeError(f"OpenAlex request failed: {last_error}")


def fetch_candidates(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch candidates across multiple queries, filtered by top-journal ISSN."""
    issn_filter = "|".join(spec["issns"])
    seen_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for query in spec["queries"]:
        params = urlencode({
            "search": query,
            "filter": (
                f"type:article,from_publication_date:2015-01-01,"
                f"locations.source.issn:{issn_filter}"
            ),
            "per-page": PER_PAGE,
            "sort": "cited_by_count:desc",
            "mailto": "research@yanhai-trace.local",
        })
        url = f"{OPENALEX_ENDPOINT}?{params}"
        print(f"  fetching: {query}")
        data = _openalex_request(url)
        for work in data.get("results", []):
            oa_id = str(work.get("id", ""))
            if oa_id in seen_ids:
                continue
            seen_ids.add(oa_id)
            candidates.append(work)
        time.sleep(0.6)  # polite pool rate limit

    print(f"  total unique candidates: {len(candidates)}")
    return candidates


# ---------------------------------------------------------------------------
# Candidate sanitisation & scoring
# ---------------------------------------------------------------------------

def _plain(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _authors(work: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        name = _plain(author.get("display_name", ""))
        if name and name not in names:
            names.append(name)
    return names[:12]


def _venue(work: dict[str, Any]) -> tuple[str, list[str]]:
    loc = work.get("primary_location", {}) or {}
    source = loc.get("source", {}) or {}
    venue = _plain(source.get("display_name", ""))
    issns: list[str] = []
    for key in ("issn", "issn_l"):
        val = source.get(key)
        if isinstance(val, list):
            issns.extend(str(v) for v in val if v)
        elif isinstance(val, str) and val:
            issns.append(val)
    return venue, issns


def _published_date(work: dict[str, Any]) -> tuple[str, int]:
    raw = str(work.get("publication_date", ""))
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw, int(raw[:4])
    year = work.get("publication_year")
    if year:
        return f"{int(year)}-01-01", int(year)
    return "", 0


def _keyword_score(spec: dict[str, Any], title: str, abstract: str) -> float:
    text = f"{title} {abstract}".casefold()
    return sum(
        weight for term, weight in spec["weighted_terms"].items()
        if term in text
    )


def sanitize_candidates(
    spec: dict[str, Any],
    works: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_doi: dict[str, dict[str, Any]] = {}
    excluded_markers = (
        "correction", "corrigendum", "erratum", "retraction",
        "withdrawn", "supplementary", "editorial", "author response",
    )
    for work in works:
        title = _plain(work.get("title", ""))
        if not title:
            continue
        lowered = title.casefold()
        if any(marker in lowered for marker in excluded_markers):
            continue
        doi_url = str(work.get("doi") or "").strip()
        if not doi_url:
            continue
        doi = doi_url.replace("https://doi.org/", "").lower()
        published, year = _published_date(work)
        if not published or year < 2015 or year > 2026:
            continue
        venue, issns = _venue(work)
        if not venue:
            continue
        abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
        score = _keyword_score(spec, title, abstract)
        if score < 4:
            continue
        # Required-term filter: title or abstract must mention a core term.
        full_text = f"{title} {abstract}".casefold()
        required = spec.get("required_terms", [])
        if required and not any(term in full_text for term in required):
            continue
        # Excluded-term filter: reject off-topic titles.
        excluded = spec.get("excluded_terms", [])
        if excluded and any(term in lowered for term in excluded):
            continue
        record = {
            "doi": doi,
            "title": title,
            "authors": _authors(work),
            "year": year,
            "published": published,
            "venue": venue,
            "issns": issns,
            "citation_count": int(work.get("cited_by_count") or 0),
            "source_url": doi_url,
            "abstract": abstract,
            "openalex_id": str(work.get("id", "")),
            "keyword_score": score,
            "type": str(work.get("type", "article")),
        }
        if doi in by_doi:
            existing = by_doi[doi]
            existing["citation_count"] = max(existing["citation_count"], record["citation_count"])
            existing["keyword_score"] = max(existing["keyword_score"], record["keyword_score"])
            if not existing["abstract"] and record["abstract"]:
                existing["abstract"] = record["abstract"]
        else:
            by_doi[doi] = record

    candidates = list(by_doi.values())
    candidates.sort(
        key=lambda c: (c["citation_count"], c["keyword_score"], c["year"]),
        reverse=True,
    )
    return candidates


# ---------------------------------------------------------------------------
# Evidence-card generation from abstract
# ---------------------------------------------------------------------------

METHOD_PATTERNS = re.compile(
    r"\b(we present|we develop|we introduce|we propose|we report|here we present|"
    r"method|approach|framework|algorithm|pipeline|tool|model|architecture|"
    r"based on|uses?|leverages?|employs?)\b",
    re.IGNORECASE,
)
EVAL_PATTERNS = re.compile(
    r"\b(we apply|we evaluate|we test|we benchmark|we validate|dataset|"
    r"benchmark|data set|cells?|samples?|patients?|tumou?rs?|tissues?|"
    r"qubits?|experiments?|simulation|measured?)\b",
    re.IGNORECASE,
)
FINDING_PATTERNS = re.compile(
    r"\b(we find|we show|we demonstrate|we observe|results?|outperforms?|"
    r"improves?|achieves?|achieving|significant|enables?|reveals?|higher|"
    r"accuracy|fidelity|error rate|state-of-the-art)\b",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.strip()) > 20]


def _shorten(sentence: str, limit: int = 220) -> str:
    sentence = sentence.strip()
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "."


def _pick(sentences: list[str], pattern: re.Pattern[str], limit: int = 2) -> list[str]:
    picked: list[str] = []
    for s in sentences:
        if pattern.search(s) and s not in picked:
            picked.append(_shorten(s))
            if len(picked) >= limit:
                break
    return picked


def generate_evidence_card(title: str, abstract: str, doi: str) -> str:
    """Build a Method/Evaluation/Finding card from the abstract."""
    sentences = _split_sentences(abstract)
    method_sents = _pick(sentences, METHOD_PATTERNS, 2)
    eval_sents = _pick(sentences, EVAL_PATTERNS, 2)
    finding_sents = _pick(sentences, FINDING_PATTERNS, 2)

    # Fallbacks: if a section is empty, take the first/last available sentence.
    if not method_sents and sentences:
        method_sents = [_shorten(sentences[0])]
    if not finding_sents and sentences:
        finding_sents = [_shorten(sentences[-1])]
    if not eval_sents and len(sentences) > 1:
        eval_sents = [_shorten(sentences[len(sentences) // 2])]

    lines = [f"# {title}", ""]
    if method_sents:
        lines.append("## Method")
        lines.extend(method_sents)
        lines.append("")
    if eval_sents:
        lines.append("## Evaluation")
        lines.extend(eval_sents)
        lines.append("")
    if finding_sents:
        lines.append("## Finding")
        lines.extend(finding_sents)
        lines.append("")
    lines.append("## Provenance")
    lines.append(
        f"本卡片为项目组依据 DOI {doi} 的出版社元数据与公开摘要所作释义，"
        "不是论文全文逐字摘录。方法、实验和结论须取得全文后复核。"
    )
    return "\n".join(lines) + "\n"


def _metadata_card(domain_name: str, record: dict[str, Any]) -> str:
    authors = ", ".join(record["authors"]) or "OpenAlex 未提供作者字段"
    return (
        f"# {record['title']}\n\n"
        "## 书目信息\n\n"
        f"- 作者：{authors}\n"
        f"- 年份：{record['year']}\n"
        f"- 来源：{record['venue']}\n"
        f"- DOI：{record['doi']}\n"
        f"- 检索时引用量快照：{record['citation_count']}\n\n"
        "## 收录范围\n\n"
        f"本记录经 OpenAlex 元数据筛选纳入“{domain_name}”扩展检索层，"
        "仅用于题名、作者、来源和主题检索。项目尚未在本地持有或解析该论文全文，"
        "因此本卡片不声明论文采用了何种方法、取得了何种实验结果，也不能作为"
        "知识图谱关系的证据。\n\n"
        "## 溯源与待办\n\n"
        f"- DOI 来源：{record['source_url']}\n"
        "- 元数据提供方：OpenAlex REST API\n"
        "- 待办：合法取得全文后执行结构解析、实体关系抽取和人工证据复核；"
        "通过前不得提升为证据层。\n"
    )


# ---------------------------------------------------------------------------
# Manifest assembly
# ---------------------------------------------------------------------------

def _paper_id(doi: str) -> str:
    return doi.replace("/", "-")


def _card_path(domain_dir: Path, doi: str) -> Path:
    digest = hashlib.sha1(doi.encode("utf-8")).hexdigest()[:12]
    return domain_dir / "documents" / f"oa-{digest}.md"


def _concepts_for(spec: dict[str, Any], title: str, abstract: str) -> list[str]:
    text = f"{title} {abstract}".casefold()
    concepts = [spec["fallback_concept"]]
    for term in spec["weighted_terms"]:
        if term in text and term not in concepts:
            concepts.append(term)
    return concepts[:6]


def build_manifest(spec: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    domain_dir = VERTICAL_ROOT / "domains" / spec["domain_id"]
    docs_dir = domain_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    papers: list[dict[str, Any]] = []
    evidence_count = 0

    for record in records:
        card_path = _card_path(domain_dir, record["doi"])
        has_abstract = bool(record["abstract"])
        if has_abstract:
            card_text = generate_evidence_card(
                record["title"], record["abstract"], record["doi"]
            )
            evidence_tier = "evidence_card"
            exclude = False
            evidence_count += 1
        else:
            card_text = _metadata_card(spec["domain_name"], record)
            evidence_tier = "metadata_only"
            exclude = True

        card_path.write_text(card_text, encoding="utf-8")
        relative_path = card_path.relative_to(domain_dir).as_posix()

        papers.append({
            "paper_id": _paper_id(record["doi"]),
            "doi": record["doi"],
            "title": record["title"],
            "authors": record["authors"],
            "year": record["year"],
            "published": record["published"],
            "venue": record["venue"],
            "categories": list(spec["categories"]),
            "summary": (
                f"该论文经 OpenAlex 元数据筛选纳入“{spec['domain_name']}”"
                + ("证据卡层，基于公开摘要释义。"
                   if has_abstract else
                   "检索扩展层；方法、实验和结论须在取得全文并完成证据抽取后写入关系图。")
            ),
            "concepts": _concepts_for(spec, record["title"], record["abstract"]),
            "source_url": record["source_url"],
            "document_path": relative_path,
            "peer_reviewed": True,
            "peer_reviewed_status": "OpenAlex venue-inferred",
            "crossref_type": record["type"],
            "citation_count_snapshot": record["citation_count"],
            "metadata_provider": "OpenAlex REST API",
            "metadata_retrieved_on": "2026-08-26",
            "source_acquired": False,
            "source_verified_against_original": False,
            "knowledge_card_basis": (
                "publisher metadata and public abstract"
                if has_abstract
                else "OpenAlex bibliographic metadata only"
            ),
            "evidence_tier": evidence_tier,
            "exclude_from_evidence_graph": exclude,
        })

    manifest = {
        "domain_id": spec["domain_id"],
        "domain_name": spec["domain_name"],
        "version": spec["version"],
        "description": spec["description"],
        "query_example": spec["query_example"],
        "corpus_type": "tiered scholarly corpus: evidence cards plus metadata-only retrieval records",
        "source_scope": (
            f"{evidence_count} 篇经 DOI 与公开摘要整理的证据卡用于演示关系图；"
            f"{len(papers) - evidence_count} 篇 OpenAlex DOI 元数据记录只用于书目检索，"
            "取得并解析全文前不得作为关系证据。"
        ),
        "papers": papers,
        "paper_count_target": TARGET_PER_DOMAIN,
        "evidence_tier_summary": {
            "evidence_cards": evidence_count,
            "metadata_only": len(papers) - evidence_count,
            "policy": (
                "Only evidence_cards are parsed into the relation graph. "
                "Metadata-only records participate in bibliographic retrieval "
                "but cannot support graph relations."
            ),
        },
        "search_audit": {
            "searched_on": "2026-08-26",
            "provider": "OpenAlex REST API",
            "queries": spec["queries"],
            "inclusion": (
                "OpenAlex type:article; DOI and venue present; "
                "publication date 2015-2026; venue ISSN in curated top-journal list; "
                "title/abstract passes weighted domain keyword threshold."
            ),
            "exclusion": (
                "Corrections, errata, retractions, editorials, supplements; "
                "missing DOI/venue/date; duplicate DOI; off-topic records."
            ),
            "selection": (
                "Top-journal ISSN filter; multi-query merge with DOI dedup; "
                "citation-count descending; weighted keyword relevance; "
                f"top {TARGET_PER_DOMAIN} selected."
            ),
            "candidate_count": len(records),
            "top_journals_issn": spec["issns"],
        },
    }
    manifest_path = domain_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def update_registry(new_specs: list[dict[str, Any]]) -> None:
    registry_path = VERTICAL_ROOT / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    existing_ids = {d["domain_id"] for d in registry["domains"]}
    for spec in new_specs:
        if spec["domain_id"] in existing_ids:
            continue
        registry["domains"].append({
            "domain_id": spec["domain_id"],
            "path": f"domains/{spec['domain_id']}",
            "domain_name": spec["domain_name"],
            "description": spec["description"],
            "query_example": spec["query_example"],
        })
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"registry updated: {len(registry['domains'])} domains")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build bio/physics vertical corpora.")
    parser.add_argument("--fetch", action="store_true", help="Retrieve candidates from OpenAlex.")
    parser.add_argument("--apply", action="store_true", help="Generate manifests and cards.")
    args = parser.parse_args()
    do_fetch = args.fetch or not args.apply
    do_apply = args.apply or not args.fetch

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / "openalex-new-domains-2026-08-26.json"

    all_candidates: dict[str, list[dict[str, Any]]] = {}

    if do_fetch:
        for spec in DOMAIN_SPECS:
            print(f"\n[{spec['domain_id']}] fetching candidates ...")
            works = fetch_candidates(spec)
            records = sanitize_candidates(spec, works)
            print(f"  after filtering: {len(records)} eligible")
            if len(records) < TARGET_PER_DOMAIN:
                print(f"  WARNING: only {len(records)} eligible, target is {TARGET_PER_DOMAIN}")
            all_candidates[spec["domain_id"]] = records[:TARGET_PER_DOMAIN]
        cache_path.write_text(
            json.dumps(
                {
                    "retrieved_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                    "provider": "OpenAlex REST API",
                    "target_per_domain": TARGET_PER_DOMAIN,
                    "domains": {
                        spec["domain_id"]: {
                            "queries": spec["queries"],
                            "candidate_count": len(all_candidates.get(spec["domain_id"], [])),
                            "candidates": all_candidates.get(spec["domain_id"], []),
                        }
                        for spec in DOMAIN_SPECS
                    },
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"\ncache written: {cache_path.relative_to(PROJECT_ROOT)}")
    else:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        for spec in DOMAIN_SPECS:
            all_candidates[spec["domain_id"]] = cache["domains"][spec["domain_id"]]["candidates"]

    if do_apply:
        for spec in DOMAIN_SPECS:
            records = all_candidates[spec["domain_id"]]
            print(f"\n[{spec['domain_id']}] building manifest ({len(records)} papers) ...")
            manifest = build_manifest(spec, records)
            ev = manifest["evidence_tier_summary"]
            print(
                f"  done: {len(manifest['papers'])} papers "
                f"({ev['evidence_cards']} evidence cards + {ev['metadata_only']} metadata-only)"
            )
        update_registry(DOMAIN_SPECS)
        print("\nAll domains built successfully.")


if __name__ == "__main__":
    main()
