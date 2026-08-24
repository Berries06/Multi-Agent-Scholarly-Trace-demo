"""Weekly literature scan: arXiv sweep -> dedup vs frozen corpus -> four-question
interpretation (optional, cheap model) -> weekly report + candidate queue.

Design (docs/研发记录/文献管线升级方案_2026-08-23.md):
- S1 定时自动检索：三类目 x 三组关键词，只取最近 7 天新提交；
- S2 去重（arXiv ID > DOI > 规范化标题）并与冻结语料/垂直语料比对；
- S3 新颖性初筛：与已有工作相似度 + 可选 LLM 四问解读，输出 candidate|novel
  线索标签（最终以人工复核为准）；
- S4 周报 md + candidate_queue.json（human_review_required=true）。

用法:
  python scripts/weekly_literature_scan.py --days 7 --max-per-query 25
  python scripts/weekly_literature_scan.py --days 7 --interpret --interpret-limit 10

纪律：--interpret 需要 .env 里的 Key；缺 Key 直接报错退出（ProviderError），
绝不静默跳过解读。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
SRC = PROJECT_ROOT / "src"
for path in (SCRIPTS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_literature_corpus import fetch, normalize_title  # noqa: E402

ATOM = {"a": "http://www.w3.org/2005/Atom"}
ARXIV = "http://arxiv.org/schemas/atom"

QUERIES = {
    "scientific-claim-verification": (
        'cat:cs.CL AND (abs:"claim verification" OR abs:"fact verification" '
        'OR abs:"evidence adjudication")'
    ),
    "kg-construction-llm": (
        'cat:cs.AI AND (abs:"knowledge graph" AND abs:"large language")'
    ),
    "multiagent-verification": (
        'cat:cs.SI AND (abs:"multi-agent" AND (abs:"debate" OR abs:"verification"))'
    ),
}


def _norm(value: str) -> str:
    return " ".join(value.split())


def load_dotenv(path: Path) -> None:
    """Load KEY=value lines from .env into the process environment (setdefault)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_known_titles() -> list[str]:
    """Frozen corpus + addendum + vertical manifest titles (normalized)."""
    titles: list[str] = []
    for path in (
        PROJECT_ROOT / "config" / "literature_corpus_100.json",
        PROJECT_ROOT / "config" / "literature_corpus_addendum_2.json",
    ):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        titles.extend(item["title"] for item in payload.get("papers", []))
    manifest_path = PROJECT_ROOT / "data" / "vertical_kb" / "manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for paper in payload.get("papers", []):
            if paper.get("title"):
                titles.append(paper["title"])
    return [normalize_title(title) for title in titles]


def known_match(title: str, known_norm: list[str], threshold: float = 0.82) -> str | None:
    """Return the closest known title when similarity >= threshold."""
    from difflib import SequenceMatcher

    normalized = normalize_title(title)
    best: tuple[float, str] | None = None
    for known in known_norm:
        score = SequenceMatcher(None, normalized, known).ratio()
        if best is None or score > best[0]:
            best = (score, known)
    if best and best[0] >= threshold:
        return best[1]
    return None


def scan_arxiv(days: int, max_per_query: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    hits: dict[str, dict[str, Any]] = {}
    query_log: dict[str, list[str]] = {}
    for name, query in QUERIES.items():
        url = (
            "https://export.arxiv.org/api/query?"
            + urllib.parse.urlencode(
                {
                    "search_query": query,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                    "max_results": max_per_query,
                }
            )
        )
        root = ET.fromstring(fetch(url, timeout=60))
        query_log[name] = []
        for entry in root.findall("a:entry", ATOM):
            published = entry.findtext("a:published", default="", namespaces=ATOM)
            try:
                published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                continue
            if published_dt < since:
                continue
            arxiv_id = _norm(entry.findtext("a:id", default="", namespaces=ATOM)).split("/abs/")[-1]
            title = _norm(entry.findtext("a:title", default="", namespaces=ATOM))
            if not title:
                continue
            query_log[name].append(arxiv_id)
            links = {
                link.attrib.get("type", ""): link.attrib.get("href", "")
                for link in entry.findall("a:link", ATOM)
            }
            if arxiv_id in hits:
                hits[arxiv_id]["matched_queries"].append(name)
                continue
            hits[arxiv_id] = {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": [
                    _norm(author.findtext("a:name", default="", namespaces=ATOM))
                    for author in entry.findall("a:author", ATOM)
                ],
                "affiliations": [
                    _norm(author.findtext(f"{{{ARXIV}}}affiliation", default="") or "")
                    for author in entry.findall("a:author", ATOM)
                ],
                "abstract": _norm(entry.findtext("a:summary", default="", namespaces=ATOM)),
                "published": published,
                "primary_url": arxiv_id,
                "pdf_url": links.get("application/pdf", ""),
                "journal_ref": _norm(entry.findtext(f"{{{ARXIV}}}journal_ref", default="") or ""),
                "comment": _norm(entry.findtext(f"{{{ARXIV}}}comment", default="") or ""),
                "matched_queries": [name],
            }
    papers = sorted(hits.values(), key=lambda item: item["published"], reverse=True)
    return papers, query_log


def interpret(
    papers: list[dict[str, Any]],
    known_norm: list[str],
    limit: int,
) -> dict[str, dict[str, Any]]:
    """Four-question interpretation via the cheapest available provider."""
    from yanhai.providers import ProviderConfig, create_provider, load_config_from_env

    providers = ["deepseek", "kimi", "zhipu"]
    config: ProviderConfig | None = None
    for provider in providers:
        try:
            config = load_config_from_env(provider)
            break
        except Exception:  # noqa: BLE001 - 换下一家
            continue
    if config is None:
        raise SystemExit(
            "未找到任何可用 Key（DEEPSEEK/KIMI/ZHIPU_API_KEY）。"
            "--interpret 需要至少一家 .env Key，绝不静默跳过。"
        )
    client = create_provider(config)
    schema = {
        "type": "object",
        "properties": {
            "core_question": {"type": "string"},
            "application_scenario": {"type": "string"},
            "method_diff": {"type": "string"},
            "innovation_judgment": {"type": "string", "enum": ["candidate", "novel"]},
        },
        "required": [
            "core_question",
            "application_scenario",
            "method_diff",
            "innovation_judgment",
        ],
    }
    results: dict[str, dict[str, Any]] = {}
    for paper in papers[:limit]:
        similar = known_match(paper["title"], known_norm) or "无高度相似工作"
        system = (
            "你是科研文献初筛助手。对论文输出四问解读（每问≤50字）："
            "1) 核心问题：这篇论文在研究什么？2) 应用场景：解决什么场景的关键问题？"
            "3) 方法差异：与已有工作主要不同在哪？4) 创新判断：相对已有工作是"
            "candidate（疑似相近改进）还是 novel（未见高度相似）。创新判断只是初筛线索，"
            "最终以人工复核为准。"
        )
        user = (
            f"论文标题：{paper['title']}\n摘要：{paper['abstract'][:1200]}\n"
            f"与之最相似的已有工作：{similar}"
        )
        try:
            data, _usage = client.complete_json(
                system, user, schema_name="four_question_interpretation", schema=schema
            )
        except Exception as exc:  # noqa: BLE001 - 单篇失败不拖垮整批，但记录失败
            results[paper["arxiv_id"]] = {"interpretation_error": f"{type(exc).__name__}"}
            continue
        results[paper["arxiv_id"]] = dict(data)
    return results


def weekly_report(
    papers: list[dict[str, Any]],
    interpretations: dict[str, dict[str, Any]],
    query_log: dict[str, list[str]],
    week: str,
    days: int,
) -> str:
    lines = [
        f"# 文献周报 {week}",
        "",
        f"- 扫描窗口：最近 {days} 天；来源：arXiv（三类目 × 三组关键词）；",
        f"- 新增候选 {len(papers)} 篇；人工复核前一律 human_review_required=true；",
        "- 创新判断为初筛线索，最终口径以人工复核为准（AI 解读不是证据）。",
        "",
        "## Top 候选",
        "",
    ]
    for paper in papers[:10]:
        interpretation = interpretations.get(paper["arxiv_id"], {})
        matched = ", ".join(paper["matched_queries"])
        affiliation = paper["affiliations"][0] if paper["affiliations"] else "未知机构"
        lines += [
            f"### {paper['title']}",
            f"- arXiv：{paper['arxiv_id']}（{paper['published'][:10]}）· 第一作者机构：{affiliation}",
            f"- 命中检索组：{matched}；期刊/会议：{paper['journal_ref'] or '未标注'}",
            f"- 核心问题：{interpretation.get('core_question', '待解读')}",
            f"- 应用场景：{interpretation.get('application_scenario', '待解读')}",
            f"- 方法差异：{interpretation.get('method_diff', '待解读')}",
            f"- 创新判断：{interpretation.get('innovation_judgment', 'candidate')}（线索级）",
            f"- PDF：{paper['pdf_url']}",
            "",
        ]
    lines += ["## 检索记录", ""]
    for name, ids in query_log.items():
        lines.append(f"- {name}：命中 {len(ids)} 篇")
    lines += ["", "## 全部新增（未入选 Top 的也在候选队列）", ""]
    for paper in papers[10:]:
        lines.append(f"- [{paper['arxiv_id']}] {paper['title']}（{paper['published'][:10]}）")
    return "\n".join(lines) + "\n"


def update_candidate_queue(
    papers: list[dict[str, Any]],
    interpretations: dict[str, dict[str, Any]],
    week: str,
) -> None:
    queue_path = PROJECT_ROOT / "data" / "vertical_kb" / "candidate_queue.json"
    existing: dict[str, dict[str, Any]] = {}
    if queue_path.exists():
        existing = {
            item["arxiv_id"]: item
            for item in json.loads(queue_path.read_text(encoding="utf-8")).get("entries", [])
        }
    for paper in papers:
        interpretation = interpretations.get(paper["arxiv_id"], {})
        existing[paper["arxiv_id"]] = {
            "arxiv_id": paper["arxiv_id"],
            "title": paper["title"],
            "authors": paper["authors"],
            "first_affiliation": paper["affiliations"][0] if paper["affiliations"] else "",
            "accepted_venue": paper["journal_ref"],
            "pdf_url": paper["pdf_url"],
            "primary_url": f"https://arxiv.org/abs/{paper['arxiv_id']}",
            "published": paper["published"],
            "matched_queries": paper["matched_queries"],
            "status": "candidate",
            "human_review_required": True,
            "novelty_label": interpretation.get("innovation_judgment", "candidate"),
            "interpretation": {
                key: interpretation.get(key)
                for key in ("core_question", "application_scenario", "method_diff")
                if interpretation.get(key)
            },
            # AI 解读与证据跨度严格分离：interpretation 仅供阅读辅助，
            # 任何入图证据必须来自原文 span，经裁决链确认。
            "evidence_spans": [],
            "scanned_week": week,
        }
    payload = {
        "schema_version": "1.0.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": (
            "candidate -> human review -> evidence_card -> EASG adjudication -> graph; "
            "interpretation is reading aid, never evidence."
        ),
        "entries": sorted(existing.values(), key=lambda item: item["published"], reverse=True),
    }
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"candidate_queue: {len(payload['entries'])} entries -> {queue_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-per-query", type=int, default=25)
    parser.add_argument("--interpret", action="store_true")
    parser.add_argument("--interpret-limit", type=int, default=10)
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    papers, query_log = scan_arxiv(args.days, args.max_per_query)
    known_norm = load_known_titles()
    for paper in papers:
        similar = known_match(paper["title"], known_norm)
        paper["similar_known_work"] = similar
    new_papers = [paper for paper in papers if not paper["similar_known_work"]]
    print(
        f"scanned {len(papers)} papers (last {args.days} days), "
        f"{len(new_papers)} not matching frozen corpus"
    )

    interpretations: dict[str, dict[str, Any]] = {}
    if args.interpret:
        interpretations = interpret(new_papers, known_norm, args.interpret_limit)
        print(f"interpreted {len(interpretations)} papers")

    week = datetime.now(timezone.utc).strftime("%Y-W%W")
    snapshot_dir = (
        PROJECT_ROOT
        / "data"
        / "vertical_kb"
        / "search_cache"
        / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": args.days,
        "queries": QUERIES,
        "query_log": query_log,
        "hits": papers,
        "interpreted": args.interpret,
    }
    (snapshot_dir / "scan_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    report_dir = PROJECT_ROOT / "docs" / "文献周报"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"weekly_{week}.md"
    report_path.write_text(
        weekly_report(new_papers, interpretations, query_log, week, args.days),
        encoding="utf-8",
    )
    update_candidate_queue(new_papers, interpretations, week)
    print(f"report: {report_path}")
    print(f"snapshot: {snapshot_dir / 'scan_snapshot.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
