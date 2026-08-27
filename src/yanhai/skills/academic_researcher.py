"""学术文献调研 Skill

对应 doubao-academic-researcher 的核心方法论，以可调用的 Python 模块落地：
- 证据分级：研究设计层级 x 学科内适配度 双轴定级
- 引用核验：DOI 格式校验、标题一致性检查
- 主题聚类：基于概念/类别的文献分组
- 争议与空白识别：矛盾主张检测、研究缺口发现
- 文献地图：主题 x 代表文献 x 争议 x 空白 矩阵
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

TOP_VENUES = {
    "nature", "science", "cell", "pnas", "physical review letters",
    "physical review a", "physical review b", "physical review x",
    "nature physics", "nature materials", "nature chemistry",
    "nature communications", "nature methods", "nature machine intelligence",
    "science advances", "neurips", "icml", "iclr", "acl", "emnlp",
    "cvpr", "iccv", "eccv", "aaai", "ijcai", "kdd", "www", "sigmod",
    "vldb", "osdi", "sosp", "isca", "micro", "asplos",
    "reviews of modern physics", "nature reviews physics",
    "nature reviews materials", "chemical reviews",
    "npj quantum information", "physical review research",
}

_STOPWORDS = frozenset({
    "using", "with", "from", "based", "toward", "towards", "through",
    "their", "this", "that", "these", "those", "have", "been", "were",
    "are", "for", "and", "the", "into", "over", "under", "between",
    "about", "after", "before", "above", "below", "which", "where",
    "when", "what", "while", "during", "without", "within", "across",
    "via", "per", "can", "may", "its", "our", "they",
})

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


@dataclass(slots=True, frozen=True)
class EvidenceGrade:
    design_level: int
    design_label: str
    discipline_fit: str
    authority_signal: str
    quality_basis: str
    source_quality: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "design_level": self.design_level,
            "design_label": self.design_label,
            "discipline_fit": self.discipline_fit,
            "authority_signal": self.authority_signal,
            "quality_basis": self.quality_basis,
            "source_quality": self.source_quality,
        }


@dataclass(slots=True, frozen=True)
class CitationCheck:
    paper_id: str
    doi_present: bool
    doi_valid: bool
    doi: str
    title_in_url: bool
    verification_status: str
    issues: list = field(default_factory=list)

    def to_dict(self):
        return {
            "paper_id": self.paper_id, "doi_present": self.doi_present,
            "doi_valid": self.doi_valid, "doi": self.doi,
            "title_in_url": self.title_in_url,
            "verification_status": self.verification_status,
            "issues": list(self.issues)}


@dataclass(slots=True, frozen=True)
class TopicCluster:
    topic_id: str
    label: str
    paper_ids: list
    key_concepts: list
    paper_count: int
    avg_year: float
    top_papers: list

    def to_dict(self):
        return {
            "topic_id": self.topic_id, "label": self.label,
            "paper_ids": list(self.paper_ids),
            "key_concepts": list(self.key_concepts),
            "paper_count": self.paper_count,
            "avg_year": round(self.avg_year, 1),
            "top_papers": list(self.top_papers)}


@dataclass(slots=True, frozen=True)
class Controversy:
    topic: str
    claim_a: str
    claim_b: str
    papers_a: list
    papers_b: list
    severity: str

    def to_dict(self):
        return {
            "topic": self.topic, "claim_a": self.claim_a,
            "claim_b": self.claim_b, "papers_a": list(self.papers_a),
            "papers_b": list(self.papers_b), "severity": self.severity}


@dataclass(slots=True, frozen=True)
class ResearchGap:
    gap_id: str
    description: str
    related_topics: list
    evidence_count: int
    suggested_direction: str

    def to_dict(self):
        return {
            "gap_id": self.gap_id, "description": self.description,
            "related_topics": list(self.related_topics),
            "evidence_count": self.evidence_count,
            "suggested_direction": self.suggested_direction}


@dataclass(slots=True)
class ResearchReport:
    topic: str
    total_papers: int
    grades: dict
    citation_checks: list
    clusters: list
    controversies: list
    gaps: list
    literature_map: list
    summary_stats: dict

    def to_dict(self):
        return {
            "topic": self.topic, "total_papers": self.total_papers,
            "evidence_grades": {pid: g.to_dict() for pid, g in self.grades.items()},
            "citation_checks": [c.to_dict() for c in self.citation_checks],
            "topic_clusters": [c.to_dict() for c in self.clusters],
            "controversies": [c.to_dict() for c in self.controversies],
            "research_gaps": [g.to_dict() for g in self.gaps],
            "literature_map": self.literature_map,
            "summary_stats": self.summary_stats}


def grade_paper(paper, discipline="cs_ai", citation_count=0, current_year=2026):
    title = _get(paper, "title", "").lower()
    published = _get(paper, "published", "").lower()
    year = int(_get(paper, "year", 2020) or 2020)
    categories = tuple(str(c).lower() for c in (_get(paper, "categories", ()) or ()))
    summary = _get(paper, "summary", "").lower()
    authority_tier = int(_get(paper, "authority_tier", 2) or 2)

    design_level, design_label = _infer_design_level(title, summary, categories)
    discipline_fit = _infer_discipline_fit(design_level, discipline, categories, summary)
    authority_signal, quality_basis = _infer_authority(
        published, year, citation_count, authority_tier, current_year)
    strong_fit = discipline_fit in ("gold_standard", "strong")
    source_quality = "A" if (design_level <= 4 and strong_fit and authority_tier <= 2) else "B"

    return EvidenceGrade(
        design_level=design_level, design_label=design_label,
        discipline_fit=discipline_fit, authority_signal=authority_signal,
        quality_basis=quality_basis, source_quality=source_quality)


def _infer_design_level(title, summary, categories):
    text = f"{title} {summary}"
    if re.search(r"systematic review|meta-analysis|meta analysis|survey of|literature review on", text):
        return 1, "systematic_review_meta_analysis"
    if re.search(r"randomized|randomised|controlled trial|rct|placebo|double-blind", text):
        return 2, "rct_or_equivalent"
    if re.search(r"ablation|benchmark|controlled experiment|baseline comparison|empirical study", text):
        return 3, "controlled_study"
    if re.search(r"cohort|case-control|longitudinal|large-scale|empirical evaluation|dataset of", text):
        return 4, "cohort_or_case_control"
    if re.search(r"theorem|proof|mechanism|simulation|theoretical|laboratory|in vitro", text):
        return 5, "mechanistic_or_lab_study"
    if re.search(r"case study|qualitative|interview|ethnograph|field study", text):
        return 6, "case_study_or_qualitative"
    if re.search(r"editorial|opinion|perspective|commentary|viewpoint", text):
        return 7, "expert_opinion_or_editorial"
    return (3, "controlled_study") if "cs." in " ".join(categories) else (5, "mechanistic_or_lab_study")


def _infer_discipline_fit(design_level, discipline, categories, summary):
    text = f"{' '.join(categories)} {summary}".lower()
    if discipline == "cs_ai":
        if re.search(r"ablation|benchmark|reproduc|open.?source|code available", text):
            return "gold_standard"
        if design_level <= 3:
            return "strong"
        if design_level <= 5:
            return "moderate"
        return "weak"
    if discipline == "biomedicine":
        if re.search(r"phase (i|ii|iii|iv)|clinical trial|patient|cohort", text):
            return "gold_standard"
        if design_level <= 4:
            return "strong"
        return "moderate"
    if discipline in ("social_science", "economics"):
        if re.search(r"instrumental variable|difference.in.differences|regression discontinuity|natural experiment|rct", text):
            return "gold_standard"
        if design_level <= 4:
            return "strong"
        return "moderate"
    if discipline == "physics":
        if re.search(r"experiment|replicat|theoretical|proof|observation", text):
            return "gold_standard"
        if design_level <= 5:
            return "strong"
        return "moderate"
    return "moderate"


def _infer_authority(published, year, citations, tier, current_year):
    venue = published.strip().lower()
    if any(v in venue for v in TOP_VENUES):
        return "top_journal", f"发表于顶刊/顶会：{published}"
    if citations >= 100:
        return "high_citation", f"被引 {citations} 次"
    age = current_year - year
    if age >= 10 and tier <= 2:
        return "classic", f"发表 {age} 年，领域内经典工作"
    if re.search(r"arxiv|preprint", venue):
        return "official", "arXiv 预印本，未经同行评审"
    if tier <= 2:
        return "core_journal", f"权威层级 {tier} 期刊：{published}"
    return "official", f"普通来源：{published}"


def verify_citation(paper):
    """引用核验（格式级初筛，不是权威跨库核验）。

    只做两件事：DOI 格式校验、标题核心词与来源 URL 的一致性检查。
    结果状态 ``PRELIMINARY`` 仅表示"格式与链接自洽"，不代表该文献在
    外部数据库中被交叉验证存在。对外不得把本函数的结果表述为权威
    学术核验能力。
    """
    paper_id = _get(paper, "paper_id", "")
    title = _get(paper, "title", "")
    source_url = _get(paper, "source_url", "")
    external_ids = _get(paper, "external_ids", {}) or {}

    issues = []
    doi = str(external_ids.get("DOI", "") or external_ids.get("doi", ""))
    if not doi:
        m = DOI_PATTERN.search(source_url)
        if m:
            doi = m.group(0)

    doi_present = bool(doi)
    doi_valid = bool(doi and DOI_PATTERN.fullmatch(doi))

    if not doi_present:
        issues.append("缺少 DOI，无法做标识符级核验")
    elif not doi_valid:
        issues.append(f"DOI 格式异常：{doi}")

    title_words = [w for w in re.findall(r"[a-zA-Z]{4,}", title.lower())
                   if w not in _STOPWORDS][:3]
    title_in_url = all(w in source_url.lower() for w in title_words) if title_words else True
    if source_url and title_words and not title_in_url:
        issues.append("URL 中未找到标题核心词，标题与链接可能不匹配")

    if doi_valid and title_in_url:
        status = "PRELIMINARY"
    elif doi_present and not doi_valid:
        status = "MAJOR"
    elif not doi_present and source_url:
        status = "MINOR"
    else:
        status = "UNVERIFIABLE"

    return CitationCheck(
        paper_id=paper_id, doi_present=doi_present, doi_valid=doi_valid,
        doi=doi, title_in_url=title_in_url,
        verification_status=status, issues=issues)


def cluster_papers(papers, n_topics=6):
    if not papers:
        return []

    concept_df = Counter()
    paper_concepts = {}
    for p in papers:
        concepts = [str(c).lower() for c in (_get(p, "concepts", ()) or ())]
        categories = [str(c).lower() for c in (_get(p, "categories", ()) or ())]
        all_concepts = list({*concepts, *categories})
        pid = _get(p, "paper_id", "")
        paper_concepts[pid] = all_concepts
        for c in all_concepts:
            concept_df[c] += 1

    _BROAD = {"cs.ai", "cs.lg", "cs.cl", "physics", "quant-ph", "cs.cv"}
    anchors = [c for c, _ in concept_df.most_common(n_topics * 3)
               if c not in _BROAD][:n_topics]
    if not anchors:
        anchors = [c for c, _ in concept_df.most_common(n_topics)]

    clusters = defaultdict(list)
    for p in papers:
        pid = _get(p, "paper_id", "")
        concepts = set(paper_concepts.get(pid, []))
        best_anchor = None
        best_freq = 0
        for a in anchors:
            if a in concepts and concept_df[a] > best_freq:
                best_anchor = a
                best_freq = concept_df[a]
        if best_anchor is None:
            best_anchor = anchors[0] if anchors else "other"
        clusters[best_anchor].append(pid)

    result = []
    for i, anchor in enumerate(anchors):
        pids = clusters.get(anchor, [])
        if not pids:
            continue
        years = []
        for p in papers:
            if _get(p, "paper_id", "") in pids:
                y = int(_get(p, "year", 0) or 0)
                if y:
                    years.append(y)
        avg_year = sum(years) / len(years) if years else 0
        top = sorted(
            pids,
            key=lambda pid: next(
                (int(_get(p, "authority_tier", 3) or 3)
                 for p in papers if _get(p, "paper_id", "") == pid), 3))[:5]
        cluster_concepts = Counter()
        for p in papers:
            if _get(p, "paper_id", "") in pids:
                for c in paper_concepts.get(_get(p, "paper_id", ""), []):
                    if c != anchor:
                        cluster_concepts[c] += 1
        key_concepts = [c for c, _ in cluster_concepts.most_common(5)]
        result.append(TopicCluster(
            topic_id=f"T{i+1}",
            label=anchor.replace("-", " ").replace("_", " ").title(),
            paper_ids=pids, key_concepts=key_concepts,
            paper_count=len(pids), avg_year=avg_year, top_papers=top))
    return result


def identify_controversies(claims):
    pairs = defaultdict(list)
    for c in claims:
        if _get(c, "status", "") != "accepted":
            continue
        key = frozenset({_get(c, "source", ""), _get(c, "target", "")})
        pairs[key].append(c)

    controversies = []
    for key, group in pairs.items():
        if len(group) < 2:
            continue
        relations = {_get(c, "relation", "") for c in group}
        if len(relations) > 1:
            entities = list(key)
            c_a, c_b = group[0], group[1]
            severity = "high" if any(
                r in relations for r in ("contradicts", "disproves", "refutes")
            ) else "medium"
            controversies.append(Controversy(
                topic=f"{entities[0]} <-> {entities[1]}" if len(entities) == 2 else "未知",
                claim_a=f"{_get(c_a, 'source', '')} -{_get(c_a, 'relation', '')}-> {_get(c_a, 'target', '')}",
                claim_b=f"{_get(c_b, 'source', '')} -{_get(c_b, 'relation', '')}-> {_get(c_b, 'target', '')}",
                papers_a=[_get(c_a, "claim_id", "")],
                papers_b=[_get(c_b, "claim_id", "")],
                severity=severity))
    return controversies


def identify_gaps(clusters, claims, papers):
    gaps = []
    accepted_claims = [c for c in claims if _get(c, "status", "") == "accepted"]

    for cl in clusters:
        if cl.paper_count <= 2 and cl.avg_year >= 2022:
            gaps.append(ResearchGap(
                gap_id=f"G{len(gaps)+1}",
                description=f"「{cl.label}」方向文献稀少（{cl.paper_count} 篇），且多为近年工作，可能处于早期阶段",
                related_topics=[cl.label], evidence_count=cl.paper_count,
                suggested_direction=f"扩大 {cl.label} 的实证范围，补充基准测试或消融实验"))

    rejected_by_topic = defaultdict(int)
    for c in claims:
        if _get(c, "status", "") == "rejected":
            rejected_by_topic[_get(c, "source", "")] += 1
    for topic, count in rejected_by_topic.items():
        if count >= 1:
            gaps.append(ResearchGap(
                gap_id=f"G{len(gaps)+1}",
                description=f"「{topic}」存在 {count} 条被拒绝的命题，证据基础不稳固",
                related_topics=[topic], evidence_count=count,
                suggested_direction=f"为 {topic} 补充原始证据或重新审视命题表述"))

    connected_pairs = set()
    for c in accepted_claims:
        connected_pairs.add((_get(c, "source", "").lower(), _get(c, "target", "").lower()))
    for i, cl_a in enumerate(clusters):
        for cl_b in clusters[i+1:]:
            has_link = any(
                (a.lower(), b.lower()) in connected_pairs or (b.lower(), a.lower()) in connected_pairs
                for a in [cl_a.label, *cl_a.key_concepts[:2]]
                for b in [cl_b.label, *cl_b.key_concepts[:2]])
            if not has_link:
                gaps.append(ResearchGap(
                    gap_id=f"G{len(gaps)+1}",
                    description=f"「{cl_a.label}」与「{cl_b.label}」之间缺乏已验证的命题连接",
                    related_topics=[cl_a.label, cl_b.label], evidence_count=0,
                    suggested_direction=f"探索 {cl_a.label} 与 {cl_b.label} 的交叉应用或机制关联"))
    return gaps[:8]


def build_literature_map(clusters, grades, papers, controversies, gaps):
    paper_by_id = {_get(p, "paper_id", ""): p for p in papers}
    result = []
    for cl in clusters:
        a_papers = [pid for pid in cl.paper_ids
                    if pid in grades and grades[pid].source_quality == "A"]
        representatives = []
        for pid in cl.top_papers[:3]:
            p = paper_by_id.get(pid)
            if p:
                representatives.append({
                    "paper_id": pid, "title": _get(p, "title", ""),
                    "year": _get(p, "year", ""), "published": _get(p, "published", ""),
                    "grade": grades.get(pid, EvidenceGrade(
                        5, "", "", "", "", "B")).source_quality})
        topic_controversies = [
            c.topic for c in controversies
            if any(kw in c.topic.lower() for kw in [cl.label.lower(), *cl.key_concepts[:2]])]
        topic_gaps = [g.description for g in gaps if cl.label in g.related_topics]
        result.append({
            "topic_id": cl.topic_id, "topic": cl.label,
            "paper_count": cl.paper_count, "a_grade_count": len(a_papers),
            "avg_year": cl.avg_year, "representatives": representatives,
            "controversies": topic_controversies, "gaps": topic_gaps,
            "key_concepts": cl.key_concepts})
    return result


def conduct_research(papers, claims=None, topic="", discipline="cs_ai", current_year=2026):
    grades = {}
    for p in papers:
        pid = _get(p, "paper_id", "")
        grades[pid] = grade_paper(p, discipline=discipline, current_year=current_year)

    citation_checks = [verify_citation(p) for p in papers]
    clusters = cluster_papers(papers)
    controversies = identify_controversies(claims or [])
    gaps = identify_gaps(clusters, claims or [], papers)
    literature_map = build_literature_map(clusters, grades, papers, controversies, gaps)

    a_count = sum(1 for g in grades.values() if g.source_quality == "A")
    preliminary = sum(1 for c in citation_checks if c.verification_status == "PRELIMINARY")
    years = [int(_get(p, "year", 0) or 0) for p in papers]
    years = [y for y in years if y]
    summary_stats = {
        "total_papers": len(papers),
        "a_grade_papers": a_count,
        "b_grade_papers": len(papers) - a_count,
        "citations_preliminary": preliminary,
        "citations_minor": sum(1 for c in citation_checks if c.verification_status == "MINOR"),
        "citations_major": sum(1 for c in citation_checks if c.verification_status == "MAJOR"),
        "citations_unverifiable": sum(1 for c in citation_checks if c.verification_status == "UNVERIFIABLE"),
        "topic_count": len(clusters),
        "controversy_count": len(controversies),
        "gap_count": len(gaps),
        "year_range": f"{min(years)}-{max(years)}" if years else "",
    }

    return ResearchReport(
        topic=topic or "未指定话题", total_papers=len(papers),
        grades=grades, citation_checks=citation_checks,
        clusters=clusters, controversies=controversies, gaps=gaps,
        literature_map=literature_map, summary_stats=summary_stats)


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
