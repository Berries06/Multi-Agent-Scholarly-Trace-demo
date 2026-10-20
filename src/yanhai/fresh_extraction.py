"""通用抽取：当一篇论文的术语不在内置词表里时，从它自己的文字里挖实体与关系。

为什么需要这一层
----------------
导入走的是 `SchemaGuidedExtractor`，它的实体**只认 `extraction_schema.json` 里那
188 个概念**。那 188 个概念来自仓库里的五批样本文献——材料、教育、单细胞、量子、
科学信息抽取。用户把「蛋白质相分离」的论文传上来，词表一个都命中不了，
结果就是零实体、零关系、零证据，工作台跑起来什么也说不出来。
这不是"抓得准不准"的问题，是"根本没抓"。

这里换一个思路：**实体名从论文自己身上挖，关系类型仍走共享本体**。

- 实体名：缩写（`CGCNN`）、专名短语（`Materials Project`）、带类型线索的名词
  （`crystal graph convolutional network` 后面紧跟 network → METHOD）、中文里
  反复出现的片段。
- 实体类型：仍只有本体那七种（DATASET / METHOD / METRIC / TASK / FINDING /
  DOMAIN / LIMITATION），按"这个词后面紧跟着什么词"猜，猜不出来记 FINDING。
- 关系：句子里同时出现两个实体时，先看有没有本体的触发词且类型约束对得上；
  再看不带触发词也成立的四条常见句式（在某数据集上评测 / 报告某个指标 /
  建立在另一个方法上 / 数据集服务某个任务）；都不成立就记 `RELATED_TO`——
  它的语义本来就是"同一证据片段内的待复核关联"，摆出来是给人看的。

置信度一律压在接收线以下（默认 0.72）：**这些候选全都要人复核**，机器不替人做
决定。批判与裁决仍调用 `SchemaGuidedExtractor` 里那两个方法，判据一模一样。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .extraction import (
    EntityMention,
    EvidenceSpan,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    SchemaGuidedExtractor,
    ScientificDocument,
    _stable_id,
    normalize_name,
)

#: 这些词不是实体：冠词、连词、常见动词、论文里的版式词。
TERM_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "this", "that", "these", "those", "we", "our", "it", "its",
        "they", "their", "he", "she", "you", "i", "and", "or", "but", "if", "then",
        "than", "as", "at", "by", "for", "from", "in", "into", "of", "on", "to",
        "with", "without", "via", "per", "all", "any", "both", "each", "more",
        "most", "some", "such", "no", "not", "only", "other", "same", "so", "very",
        "can", "could", "may", "might", "must", "shall", "should", "will", "would",
        "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
        "have", "has", "had", "here", "there", "where", "when", "which", "who",
        "why", "how", "what", "also", "however", "therefore", "thus", "hence",
        "figure", "fig", "table", "tab", "section", "sec", "eq", "equation",
        "et", "al", "eg", "ie", "vs", "ieee", "acm", "doi", "http", "https",
        "abstract", "introduction", "conclusion", "results", "discussion",
        "keywords", "references", "appendix", "supplementary",
    }
)

#: 判断实体类型用的线索词。按"离这个词最近"取第一名。
TYPE_CUES: tuple[tuple[str, str], ...] = (
    (r"datasets?|data\s?sets?|corpora|corpus|benchmarks?|database|数据集|数据库|基准", "DATASET"),
    (r"metrics?|accuracy|error|loss|precision|recall|score|auc|f1|rmse|mae|指标|准确率|误差|分数", "METRIC"),
    (r"models?|networks?|algorithms?|methods?|framework|architecture|encoder|decoder|classifier|模型|网络|算法|方法|框架", "METHOD"),
    (r"tasks?|prediction|classification|detection|segmentation|retrieval|任务|预测|分类|检测|分割", "TASK"),
    (r"limitations?|future\s+work|challenges?|局限|不足|挑战", "LIMITATION"),
    (r"domains?|fields?|领域|学科", "DOMAIN"),
    (r"energ(y|ies)|propert(y|ies)|forces?|band\s?gaps?|性质|能量|性能", "METRIC"),
)

#: 不带触发词也成立的四种句式：(头类型, 尾类型, 中间出现的词, 关系类型, 置信度)。
#: 置信度按句式本身的可靠程度给：`train X on the Y dataset` 这种几乎不会读错，
#: 给 0.7；`for` 这种弱连接给 0.62。都压在接收线（默认 0.72）以下，一律进待复核。
PAIRING_RULES: tuple[tuple[str, str, str, str, float], ...] = (
    ("METHOD", "DATASET", r"\bon\b|\busing\b|\bover\b|\bwith\b|在|基于|使用", "EVALUATES_ON", 0.70),
    ("METHOD", "METRIC", r"achiev|obtain|reach|attain|report|yield|gives?|达到|为|是", "REPORTS", 0.68),
    ("METHOD", "METHOD", r"extend|build(?:s|ing)?\s+(?:up)?on|based\s+on|improve|相比|改进|基于", "EXTENDS", 0.62),
    ("DATASET", "TASK", r"\bfor\b|用于|面向", "BENCHMARKS", 0.62),
)

ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")
PROPER_PHRASE = re.compile(r"\b[A-Z][A-Za-z0-9\-]*(?:\s+[A-Z][A-Za-z0-9\-]*){1,3}\b")
CUE_PHRASE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9\-]*(?:\s+[A-Za-z][A-Za-z0-9\-]*){0,4})\s+"
    r"(datasets?|data\s?sets?|corpora|corpus|benchmarks?|database|"
    r"models?|networks?|algorithms?|methods?|framework|architecture|encoder|decoder|classifier|"
    r"metrics?|accuracy|error|precision|recall|score|auc|f1|rmse|mae|"
    r"tasks?|prediction|classification|detection|segmentation|retrieval)\b",
    re.IGNORECASE,
)
CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,20}")
CJK_CUT = re.compile(
    r"的|了|和|与|在|是|我们|这|那|对|把|被|从|为|上|中|下|个|种|也|都|还|就|又|而|并|或|及|以|于|其|之|此|该|各|每|某"
)

CUE_WINDOW = 60

#: 名词短语前面常跟着的这些词不属于实体本身，挖出来要削掉。
LEAD_JUNK: frozenset[str] = frozenset(
    {
        "we", "our", "this", "that", "these", "those", "the", "a", "an", "on", "in",
        "for", "of", "with", "by", "from", "to", "at", "as", "and", "or", "than",
        "its", "their", "his", "her", "it", "is", "are", "was", "were", "be",
        "train", "trained", "training", "use", "used", "using", "uses", "utilize",
        "report", "reported", "reports", "achieve", "achieved", "achieves", "obtain",
        "obtained", "reach", "reached", "apply", "applied", "applies", "evaluate",
        "evaluated", "evaluates", "compare", "compared", "compares", "build", "built",
        "propose", "proposed", "proposes", "present", "presented", "show", "showed",
        "shown", "test", "tested", "adopt", "adopted", "introduce", "introduced",
        "conclude", "concludes", "concluded", "find", "finds", "found", "suggest",
        "suggests", "observed", "observe", "investigate", "investigated", "study",
        "studies", "paper", "work", "results", "result", "demonstrate", "demonstrated",
        "demonstrates", "indicate", "indicates", "improve", "improves", "improved",
        "reduce", "reduces", "reduced", "increase", "increases", "increased",
        "outperform", "outperforms", "outperformed", "yield", "yields", "cc", "by",
    }
)

#: 这些线索词本身属于指标名的后半截，要拼进去：`mean absolute` + `error`。
METRIC_CUES: frozenset[str] = frozenset(
    {
        "error", "errors", "accuracy", "precision", "recall", "score", "scores",
        "auc", "f1", "rmse", "mae", "loss", "metric", "metrics",
    }
)


def _trim_phrase(text: str) -> str:
    """把名词短语两头的功能词与动词削掉：`train a crystal graph convolutional`
    → `crystal graph convolutional`。"""
    tokens = [token for token in text.split() if token]
    while tokens and tokens[0].casefold().strip(",.;:") in LEAD_JUNK:
        tokens.pop(0)
    while tokens and tokens[-1].casefold().strip(",.;:") in LEAD_JUNK:
        tokens.pop()
    return " ".join(tokens).strip(" -.,;:()[]{}'\"")


#: 名词短语到这里就该断：介词后面是新的一截，动词后面是另一个成分。
PHRASE_BREAK = LEAD_JUNK | frozenset(
    {"of", "on", "in", "for", "with", "at", "by", "to", "from", "than", "versus", "vs"}
)


def _tail_noun_phrase(text: str, *, max_tokens: int = 4) -> str:
    """从句子里切出"离线索词最近的那个名词短语"。

    `descriptor baselines on formation energy` 里真正的短语是 `formation energy`
    ——介词把前面那截切掉了。`angular symmetry functions improve accuracy` 里
    动词 `improve` 右边才是名词短语。做法就是从右往左取，遇到介词或动词就停。
    """
    tokens = [token for token in text.split() if token]
    kept: list[str] = []
    for token in reversed(tokens):
        if token.casefold().strip(",.;:") in PHRASE_BREAK:
            break
        kept.append(token)
        if len(kept) >= max_tokens:
            break
    kept.reverse()
    return _trim_phrase(" ".join(kept))


@dataclass(slots=True)
class MinedTerm:
    canonical: str
    entity_type: str
    pattern: re.Pattern[str]
    occurrences: int = 0
    contexts: list[str] = field(default_factory=list)


def _clean(surface: str) -> str:
    return surface.strip(" -.,;:()[]{}'\"“”‘’")


def _is_meaningful(term: str) -> bool:
    if len(term) < 2 or len(term) > 60:
        return False
    if term.casefold() in TERM_STOPWORDS:
        return False
    if term.isdigit():
        return False
    return True


def _classify(term: str, contexts: list[str]) -> str:
    """按线索词判类型：取离这个词最近的那个线索。"""
    best: tuple[int, str] | None = None
    lowered_term = term.casefold()
    for context in contexts:
        lowered = context.casefold()
        position = lowered.find(lowered_term)
        if position < 0:
            continue
        tail = lowered[position + len(lowered_term) :][:CUE_WINDOW]
        for pattern, entity_type in TYPE_CUES:
            match = re.search(pattern, tail)
            if match and (best is None or match.start() < best[0]):
                best = (match.start(), entity_type)
    return best[1] if best else "FINDING"


def _term_pattern(surface: str) -> re.Pattern[str]:
    escaped = re.escape(surface)
    if surface[:1].isascii():
        return re.compile(r"(?<![A-Za-z0-9])" + escaped + r"(?![A-Za-z0-9])")
    return re.compile(escaped)


def _mine_terms(sentences: list[str], limit: int = 60) -> list[MinedTerm]:
    """从全部句子里挖候选术语。"""
    surfaces: dict[str, str] = {}
    contexts: dict[str, list[str]] = {}
    hints: dict[str, str] = {}

    def remember(surface: str, sentence: str, hint: str = "") -> None:
        cleaned = _tail_noun_phrase(_clean(surface)) if " " in surface.strip() else _trim_phrase(_clean(surface))
        if not cleaned or not _is_meaningful(cleaned):
            return
        key = normalize_name(cleaned)
        if not key:
            return
        surfaces.setdefault(key, cleaned)
        contexts.setdefault(key, []).append(sentence)
        if hint and key not in hints:
            hints[key] = hint

    for sentence in sentences:
        for match in ACRONYM.finditer(sentence):
            remember(match.group(0), sentence)
        for match in PROPER_PHRASE.finditer(sentence):
            remember(match.group(0), sentence)
        for match in CUE_PHRASE.finditer(sentence):
            # 线索词本身决定类型：`... network` 就是 METHOD，`... dataset` 就是 DATASET。
            cue = match.group(2).casefold()
            hint = ""
            for pattern, entity_type in TYPE_CUES:
                if re.fullmatch(pattern, cue) or re.search(pattern, " " + cue):
                    hint = entity_type
                    break
            phrase = match.group(1)
            # 指标类线索词是名字的一部分（mean absolute **error**），拼回去；
            # network / dataset 这类只是类型提示，不算名字的一部分。
            if cue in METRIC_CUES:
                phrase = f"{phrase} {match.group(2)}"
            remember(phrase, sentence, hint)
        for run in CJK_RUN.finditer(sentence):
            for piece in CJK_CUT.split(run.group(0)):
                if 3 <= len(piece) <= 12:
                    remember(piece, sentence)

    kept: list[MinedTerm] = []
    for key, surface in surfaces.items():
        term_contexts = contexts.get(key, [])
        occurrences = len(term_contexts)
        entity_type = hints.get(key) or _classify(surface, term_contexts)
        # 只出现一次的，必须"看着像术语"才收：缩写、专名、或带类型线索的名词短语。
        looks_like_term = (
            surface.isupper()
            or surface[:1].isupper()
            or entity_type != "FINDING"
        )
        if occurrences < 2 and not looks_like_term:
            continue
        kept.append(
            MinedTerm(
                canonical=surface,
                entity_type=entity_type,
                pattern=_term_pattern(surface),
                occurrences=occurrences,
                contexts=term_contexts,
            )
        )
    # 长的先匹配，避免 "graph neural network" 被 "network" 抢走
    kept.sort(key=lambda item: (-len(item.canonical), -item.occurrences))
    return kept[:limit]


def _relation_for(
    extractor: SchemaGuidedExtractor,
    sentence: str,
    source_entity: ExtractedEntity,
    target_entity: ExtractedEntity,
    between: str,
) -> tuple[str, float]:
    """给同一句里的两个实体定关系类型与置信度。"""
    constraints = extractor.relation_constraints

    def allowed(relation_type: str, source_type: str, target_type: str) -> bool:
        rule = constraints.get(relation_type)
        if not rule:
            return True
        return source_type in rule.get("source", []) and target_type in rule.get("target", [])

    # 1) 本体触发词：整句里出现，且类型约束对得上
    for pattern, relation_type in extractor.compiled_triggers:
        if not pattern.search(sentence):
            continue
        if allowed(relation_type, source_entity.entity_type, target_entity.entity_type):
            return relation_type, 0.68
        if allowed(relation_type, target_entity.entity_type, source_entity.entity_type):
            return relation_type, 0.6
    # 2) 不带触发词也成立的常见句式
    for source_type, target_type, connective, relation_type, confidence in PAIRING_RULES:
        if not re.search(connective, between, re.IGNORECASE):
            continue
        if (
            source_entity.entity_type == source_type
            and target_entity.entity_type == target_type
            and allowed(relation_type, source_type, target_type)
        ):
            return relation_type, confidence
    # 3) 兜底：待复核关联
    return "RELATED_TO", 0.3


def extract_documents_generic(
    extractor: SchemaGuidedExtractor,
    documents: Iterable[ScientificDocument],
    *,
    max_entities: int = 60,
    max_relations: int = 80,
) -> ExtractionResult:
    """按"实体名从文本里挖、关系走共享本体"的方式抽一遍。"""
    document_list = list(documents)
    evidence_by_id: dict[str, EvidenceSpan] = {}
    entities: dict[str, ExtractedEntity] = {}
    mentions_by_evidence: dict[str, list[EntityMention]] = {}
    relation_buckets: dict[tuple[str, str, str], ExtractedRelation] = {}
    section_records: list[dict[str, Any]] = []
    sentences: list[str] = []
    located: list[tuple[str, str, int, str]] = []

    for document in document_list:
        content_sections = {"title": document.title, **document.sections}
        for section_id, text in content_sections.items():
            section_records.append(
                {
                    "paper_id": document.paper_id,
                    "section_id": section_id,
                    "parser": document.parser or "unknown",
                    "char_count": len(text),
                    "text_sha256": hashlib.sha256(
                        text.encode("utf-8", errors="replace")
                    ).hexdigest(),
                }
            )
            for sentence_index, (start, _, sentence) in enumerate(
                extractor._sentence_spans(text)
            ):
                evidence_id = (
                    f"evidence:{document.paper_id}:"
                    f"{_stable_id('section', section_id).split(':')[1]}:{sentence_index}"
                )
                evidence_by_id[evidence_id] = EvidenceSpan(
                    evidence_id=evidence_id,
                    paper_id=document.paper_id,
                    section_id=section_id,
                    sentence_index=sentence_index,
                    text=sentence,
                    char_start=start,
                    char_end=start + len(sentence),
                )
                sentences.append(sentence)
                located.append((document.paper_id, evidence_id, sentence_index, sentence))

    terms = _mine_terms(sentences, limit=max_entities)
    papers = [
        {"paper_id": item.paper_id, "title": item.title, "source_url": item.source_url}
        for item in document_list
    ]

    for _, evidence_id, _, sentence in located:
        occupied: list[tuple[int, int]] = []
        found: list[tuple[EntityMention, ExtractedEntity, int, int]] = []
        for term in terms:
            for match in term.pattern.finditer(sentence):
                if any(
                    match.start() < end and begin < match.end()
                    for begin, end in occupied
                ):
                    continue
                entity_id = _stable_id(
                    "entity", term.entity_type, normalize_name(term.canonical)
                )
                entity = entities.setdefault(
                    entity_id,
                    ExtractedEntity(
                        entity_id=entity_id,
                        canonical_name=term.canonical,
                        entity_type=term.entity_type,
                        confidence=min(0.8, 0.35 + 0.05 * min(term.occurrences, 6)),
                    ),
                )
                entity.aliases.add(match.group(0))
                mention = EntityMention(
                    mention_id=_stable_id(
                        "mention",
                        evidence_id,
                        entity_id,
                        str(match.start()),
                        str(match.end()),
                    ),
                    entity_id=entity_id,
                    surface_form=match.group(0),
                    evidence_id=evidence_id,
                    char_start=match.start(),
                    char_end=match.end(),
                )
                entity.mentions.append(mention)
                occupied.append((match.start(), match.end()))
                found.append((mention, entity, match.start(), match.end()))
                break

        if len(found) < 2:
            continue
        mentions_by_evidence[evidence_id] = [item[0] for item in found]
        found.sort(key=lambda item: item[2])
        head = found[0]
        # 一句话里最多取两条关系：第一个实体配后面两个，避免组合爆炸。
        for other in found[1:3]:
            if head[1].entity_id == other[1].entity_id:
                continue
            between = sentence[head[3] : other[2]]
            relation_type, confidence = _relation_for(
                extractor, sentence, head[1], other[1], between
            )
            key = (head[1].entity_id, other[1].entity_id, relation_type)
            relation = relation_buckets.get(key)
            if relation is None:
                relation = ExtractedRelation(
                    relation_id=_stable_id("relation", *key),
                    source_id=head[1].entity_id,
                    target_id=other[1].entity_id,
                    relation_type=relation_type,
                    confidence=confidence,
                    extraction_method="generic-pattern",
                )
                relation_buckets[key] = relation
            if evidence_id not in relation.evidence_ids:
                relation.evidence_ids.append(evidence_id)
            relation.confidence = min(0.68, relation.confidence + 0.02)

    relations = list(relation_buckets.values())[:max_relations]
    extractor._criticize(relations, entities, evidence_by_id)
    extractor._adjudicate(relations)
    communities = extractor._build_communities(relations, entities)
    accepted = sum(relation.status == "accepted" for relation in relations)
    audit = {
        "proposer": {
            "method": "generic-pattern",
            "candidate_relations": len(relations),
            "mined_terms": len(terms),
        },
        "critic": {
            "schema_checked": True,
            "evidence_checked": True,
            "flagged_relations": sum(bool(item.criticisms) for item in relations),
        },
        "judge": {
            "accept_threshold": extractor.accept_threshold,
            "accepted_relations": accepted,
            "review_relations": sum(
                relation.status == "needs_review" for relation in relations
            ),
            "rejected_relations": sum(
                relation.status == "rejected" for relation in relations
            ),
        },
        "quality": {
            "paper_count": len(document_list),
            "parsed_sentence_count": len(evidence_by_id),
            "grounded_evidence_span_count": len(mentions_by_evidence),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "relation_evidence_coverage": round(
                (sum(bool(item.evidence_ids) for item in relations) / len(relations))
                if relations
                else 1.0,
                3,
            ),
            "note": (
                "这篇论文的术语不在内置词表里，用的是通用抽取：实体名从原文里挖，"
                "关系类型仍按共享本体判，候选全部待人复核。"
            ),
        },
    }
    return ExtractionResult(
        schema_version=extractor.schema["version"],
        papers=papers,
        entities=sorted(entities.values(), key=lambda item: item.entity_id),
        relations=sorted(relations, key=lambda item: item.relation_id),
        evidence=sorted(
            (evidence_by_id[index] for index in mentions_by_evidence),
            key=lambda item: item.evidence_id,
        ),
        communities=communities,
        audit=audit,
        sections=section_records,
    )
