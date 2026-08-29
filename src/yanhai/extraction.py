from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from .models import Paper


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha1(raw).hexdigest()[:14]}"


def normalize_name(value: str) -> str:
    """返回稳定比较键，同时不破坏中文字符。"""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\s_\-/]+", " ", value)
    value = re.sub(r"[^\w\u4e00-\u9fff ]+", "", value)
    return " ".join(value.split())


@dataclass(slots=True, frozen=True)
class ScientificDocument:
    paper_id: str
    title: str
    sections: dict[str, str]
    source_url: str = ""

    @classmethod
    def from_paper(cls, paper: Paper) -> "ScientificDocument":
        return cls(
            paper_id=paper.paper_id,
            title=paper.title,
            sections={"abstract": paper.summary},
            source_url=paper.source_url,
        )


@dataclass(slots=True, frozen=True)
class EvidenceSpan:
    evidence_id: str
    paper_id: str
    section_id: str
    sentence_index: int
    text: str
    char_start: int
    char_end: int


@dataclass(slots=True, frozen=True)
class EntityMention:
    mention_id: str
    entity_id: str
    surface_form: str
    evidence_id: str
    char_start: int
    char_end: int


@dataclass(slots=True)
class ExtractedEntity:
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: set[str] = field(default_factory=set)
    mentions: list[EntityMention] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "aliases": sorted(self.aliases, key=str.casefold),
            "mentions": [asdict(mention) for mention in self.mentions],
            "confidence": round(self.confidence, 3),
        }


@dataclass(slots=True)
class ExtractedRelation:
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "proposed"
    criticisms: list[str] = field(default_factory=list)
    extraction_method: str = "schema-guided-pattern"

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "evidence_ids": list(self.evidence_ids),
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "criticisms": list(self.criticisms),
            "extraction_method": self.extraction_method,
        }


@dataclass(slots=True)
class ExtractionResult:
    schema_version: str
    papers: list[dict[str, Any]]
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    evidence: list[EvidenceSpan]
    communities: list[dict[str, Any]]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        graph_nodes = [
            {
                "id": entity.entity_id,
                "label": entity.canonical_name,
                "kind": entity.entity_type.lower(),
                "confidence": round(entity.confidence, 3),
            }
            for entity in self.entities
        ]
        graph_nodes.extend(
            {
                "id": f"paper:{paper['paper_id']}",
                "label": paper["title"],
                "kind": "paper",
                "source_url": paper["source_url"],
            }
            for paper in self.papers
        )
        graph_nodes.extend(
            {
                "id": evidence.evidence_id,
                "label": evidence.text,
                "kind": "evidence",
                "paper_id": evidence.paper_id,
                "section_id": evidence.section_id,
                "char_start": evidence.char_start,
                "char_end": evidence.char_end,
            }
            for evidence in self.evidence
        )

        graph_edges: list[dict[str, Any]] = []
        for relation in self.relations:
            graph_edges.append(
                {
                    "id": relation.relation_id,
                    "source": relation.source_id,
                    "target": relation.target_id,
                    "label": relation.relation_type,
                    "status": relation.status,
                    "confidence": round(relation.confidence, 3),
                    "evidence_ids": list(relation.evidence_ids),
                }
            )
        for evidence in self.evidence:
            graph_edges.append(
                {
                    "id": _stable_id(
                        "edge", evidence.paper_id, evidence.evidence_id, "CONTAINS"
                    ),
                    "source": f"paper:{evidence.paper_id}",
                    "target": evidence.evidence_id,
                    "label": "CONTAINS",
                    "status": "accepted",
                    "confidence": 1.0,
                    "evidence_ids": [evidence.evidence_id],
                }
            )
        for entity in self.entities:
            for mention in entity.mentions:
                graph_edges.append(
                    {
                        "id": _stable_id(
                            "edge", mention.evidence_id, entity.entity_id, "MENTIONS"
                        ),
                        "source": mention.evidence_id,
                        "target": entity.entity_id,
                        "label": "MENTIONS",
                        "status": "accepted",
                        "confidence": 1.0,
                        "evidence_ids": [mention.evidence_id],
                    }
                )

        return {
            "schema_version": self.schema_version,
            "papers": self.papers,
            "entities": [entity.to_dict() for entity in self.entities],
            "relations": [relation.to_dict() for relation in self.relations],
            "evidence": [asdict(item) for item in self.evidence],
            "communities": self.communities,
            "audit": self.audit,
            "graph": {"nodes": graph_nodes, "edges": graph_edges},
        }


class PlainTextParser:
    """把纯文本/Markdown 解析为统一的科学文档契约。"""

    _heading = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")

    def parse(
        self,
        path: Path,
        *,
        paper_id: str | None = None,
        source_url: str = "",
    ) -> ScientificDocument:
        text = path.read_text(encoding="utf-8")
        return self.parse_text(
            text,
            paper_id=paper_id or path.stem,
            fallback_title=path.stem,
            source_url=source_url or str(path.resolve()),
        )

    def parse_text(
        self,
        text: str,
        *,
        paper_id: str,
        fallback_title: str,
        source_url: str = "",
    ) -> ScientificDocument:
        sections: dict[str, list[str]] = {"body": []}
        current = "body"
        title = fallback_title
        for line in text.splitlines():
            match = self._heading.match(line)
            if match:
                heading = match.group(1).strip()
                if title == fallback_title:
                    title = heading
                current = normalize_name(heading).replace(" ", "-") or "body"
                sections.setdefault(current, [])
            else:
                sections[current].append(line)
        return ScientificDocument(
            paper_id=paper_id,
            title=title,
            sections={
                key: "\n".join(lines).strip()
                for key, lines in sections.items()
                if "\n".join(lines).strip()
            },
            source_url=source_url,
        )


class PyPDFParser:
    """轻量真实 PDF 解析器，保留页级来源。

    Docling 仍是面向结构的解析器目标；此回退让下载的语料可在 CPU 上立即测试，
    并把每个抽取跨度记录在稳定的 ``page-NNN`` 章节下。
    """

    def parse(
        self,
        path: Path,
        *,
        paper_id: str | None = None,
        source_url: str = "",
        title: str = "",
    ) -> ScientificDocument:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - optional integration
            raise RuntimeError(
                "pypdf is not installed. Install the optional 'documents' "
                "dependency before parsing local PDF files."
            ) from exc

        reader = PdfReader(str(path))
        sections = {
            f"page-{page_number:03d}": text
            for page_number, page in enumerate(reader.pages, start=1)
            if (text := (page.extract_text() or "").strip())
        }
        return ScientificDocument(
            paper_id=paper_id or path.stem,
            title=title or path.stem,
            sections=sections,
            source_url=source_url or str(path.resolve()),
        )

    def parse_bytes(
        self,
        payload: bytes,
        *,
        paper_id: str | None = None,
        source_url: str = "",
        title: str = "",
    ) -> ScientificDocument:
        """Parse an uploaded PDF from memory; keeps page-level provenance."""
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - optional integration
            raise RuntimeError(
                "pypdf is not installed. Install the optional 'documents' "
                "dependency before parsing PDF files."
            ) from exc
        import io

        reader = PdfReader(io.BytesIO(payload))
        sections = {
            f"page-{page_number:03d}": text
            for page_number, page in enumerate(reader.pages, start=1)
            if (text := (page.extract_text() or "").strip())
        }
        if not sections:
            raise RuntimeError("PDF 中没有可提取的文本层；扫描版请先 OCR。")
        return ScientificDocument(
            paper_id=paper_id or "uploaded-paper",
            title=title or paper_id or "uploaded-paper",
            sections=sections,
            source_url=source_url or "member-uploaded-pdf",
        )


class DoclingParser:
    """可选的 Docling 适配器；轻量基线不强依赖它。"""

    def parse(self, path: Path, *, paper_id: str | None = None) -> ScientificDocument:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - optional integration
            raise RuntimeError(
                "Docling is not installed. Install the optional 'documents' dependency "
                "before parsing PDF/DOCX files."
            ) from exc

        result = DocumentConverter().convert(str(path))
        markdown = result.document.export_to_markdown()
        return PlainTextParser().parse_text(
            markdown,
            paper_id=paper_id or path.stem,
            fallback_title=path.stem,
            source_url=str(path.resolve()),
        )


class SchemaGuidedExtractor:
    """以证据优先的科学实体/关系抽取基线。

    它刻意将抽取、批判与裁决分离，这样后续用 DeepKE/LLM 提出者替换时，
    只需替换提出阶段，而不影响其它环节。
    """

    def __init__(self, schema: dict[str, Any], *, accept_threshold: float = 0.72) -> None:
        self.schema = schema
        self.accept_threshold = accept_threshold
        self.entity_types = set(schema["entity_types"])
        self.relation_types = set(schema["relation_types"])
        self.relation_constraints = schema.get("relation_constraints", {})
        self.alias_entries: list[tuple[str, str, str]] = []
        for concept in schema["concepts"]:
            aliases = {concept["canonical"], *concept["aliases"]}
            for alias in aliases:
                self.alias_entries.append(
                    (alias, concept["canonical"], concept["entity_type"])
                )
        self.alias_entries.sort(key=lambda item: len(item[0]), reverse=True)
        # Pre-compile alias regexes once instead of re-compiling per sentence.
        self.compiled_aliases: list[tuple[re.Pattern[str], str, str, str]] = [
            (self._alias_pattern(alias), alias, canonical, entity_type)
            for alias, canonical, entity_type in self.alias_entries
        ]

    @classmethod
    def from_path(cls, path: Path, *, accept_threshold: float = 0.72) -> "SchemaGuidedExtractor":
        schema = json.loads(path.read_text(encoding="utf-8"))
        return cls(schema, accept_threshold=accept_threshold)

    @staticmethod
    def _sentence_spans(text: str) -> Iterable[tuple[int, int, str]]:
        # Markdown 证据卡通常每行一句且没有句末标点。若只用 ``$`` 匹配
        # 只会捕获最后一行，静默丢弃该节其余内容。这里把换行当作句子边界，
        # 同时保留稳定的文档相对偏移。
        for match in re.finditer(
            r"[^\n。！？!?;；]+(?:[。！？!?;；]+|(?=\n)|$)",
            text,
        ):
            sentence = match.group(0).strip()
            if sentence:
                leading = len(match.group(0)) - len(match.group(0).lstrip())
                start = match.start() + leading
                yield start, start + len(sentence), sentence

    @staticmethod
    def _alias_pattern(alias: str) -> re.Pattern[str]:
        escaped = re.escape(alias)
        if re.fullmatch(r"[A-Za-z0-9 _\-/]+", alias):
            escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        return re.compile(escaped, re.IGNORECASE)

    def _relation_type_for_sentence(self, sentence: str) -> tuple[str, bool]:
        lowered = sentence.casefold()
        for pattern in self.schema["relation_patterns"]:
            if any(trigger.casefold() in lowered for trigger in pattern["triggers"]):
                return pattern["relation_type"], True
        return "RELATED_TO", False

    def extract_papers(self, papers: Iterable[Paper]) -> ExtractionResult:
        return self.extract_documents(ScientificDocument.from_paper(paper) for paper in papers)

    def extract_documents(self, documents: Iterable[ScientificDocument]) -> ExtractionResult:
        document_list = list(documents)
        evidence_by_id: dict[str, EvidenceSpan] = {}
        entities: dict[str, ExtractedEntity] = {}
        mentions_by_evidence: dict[str, list[EntityMention]] = {}
        relation_buckets: dict[tuple[str, str, str], ExtractedRelation] = {}

        for document in document_list:
            content_sections = {"title": document.title, **document.sections}
            for section_id, text in content_sections.items():
                for sentence_index, (start, end, sentence) in enumerate(
                    self._sentence_spans(text)
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
                        char_end=end,
                    )
                    seen_mentions: set[tuple[str, int, int]] = set()
                    occupied_spans: list[tuple[int, int]] = []
                    for pattern, alias, canonical, entity_type in self.compiled_aliases:
                        for match in pattern.finditer(sentence):
                            if any(
                                match.start() < occupied_end
                                and occupied_start < match.end()
                                for occupied_start, occupied_end in occupied_spans
                            ):
                                continue
                            entity_id = _stable_id(
                                "entity", entity_type, normalize_name(canonical)
                            )
                            mention_key = (entity_id, match.start(), match.end())
                            if mention_key in seen_mentions:
                                continue
                            seen_mentions.add(mention_key)
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
                            entity = entities.setdefault(
                                entity_id,
                                ExtractedEntity(
                                    entity_id=entity_id,
                                    canonical_name=canonical,
                                    entity_type=entity_type,
                                ),
                            )
                            entity.aliases.add(match.group(0))
                            entity.mentions.append(mention)
                            mentions_by_evidence.setdefault(evidence_id, []).append(mention)
                            occupied_spans.append((match.start(), match.end()))

        for entity in entities.values():
            distinct_evidence = {mention.evidence_id for mention in entity.mentions}
            entity.confidence = min(0.99, 0.78 + 0.04 * (len(distinct_evidence) - 1))

        for evidence_id, mentions in mentions_by_evidence.items():
            evidence = evidence_by_id[evidence_id]
            first_mentions: dict[str, EntityMention] = {}
            for mention in sorted(mentions, key=lambda item: item.char_start):
                first_mentions.setdefault(mention.entity_id, mention)
            if len(first_mentions) < 2:
                continue
            relation_type, matched_trigger = self._relation_type_for_sentence(evidence.text)
            ordered_mentions = sorted(first_mentions.values(), key=lambda item: item.char_start)
            for source_mention, target_mention in combinations(ordered_mentions, 2):
                source_mention, target_mention = self._orient_pair(
                    source_mention,
                    target_mention,
                    relation_type,
                    entities,
                )
                key = (
                    source_mention.entity_id,
                    target_mention.entity_id,
                    relation_type,
                )
                relation = relation_buckets.setdefault(
                    key,
                    ExtractedRelation(
                        relation_id=_stable_id("relation", *key),
                        source_id=source_mention.entity_id,
                        target_id=target_mention.entity_id,
                        relation_type=relation_type,
                        confidence=0.78 if matched_trigger else 0.62,
                    ),
                )
                if evidence_id not in relation.evidence_ids:
                    relation.evidence_ids.append(evidence_id)
                relation.confidence = min(
                    0.96,
                    relation.confidence + 0.03 * (len(relation.evidence_ids) - 1),
                )

        relations = list(relation_buckets.values())
        self._criticize(relations, entities, evidence_by_id)
        self._adjudicate(relations)
        communities = self._build_communities(relations, entities)
        accepted = sum(relation.status == "accepted" for relation in relations)
        audit = {
            "proposer": {
                "method": "schema-guided-pattern",
                "candidate_relations": len(relations),
            },
            "critic": {
                "schema_checked": True,
                "evidence_checked": True,
                "flagged_relations": sum(bool(item.criticisms) for item in relations),
            },
            "judge": {
                "accept_threshold": self.accept_threshold,
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
                    (
                        sum(bool(relation.evidence_ids) for relation in relations)
                        / len(relations)
                    )
                    if relations
                    else 1.0,
                    3,
                ),
            },
        }
        return ExtractionResult(
            schema_version=self.schema["version"],
            papers=[
                {
                    "paper_id": document.paper_id,
                    "title": document.title,
                    "source_url": document.source_url,
                }
                for document in document_list
            ],
            entities=sorted(entities.values(), key=lambda item: item.entity_id),
            relations=sorted(relations, key=lambda item: item.relation_id),
            # 图谱只保存至少支撑一个已抽取实体的证据跨度；
            # 未命中 schema 的解析句仅计入解析审计数，不虚增可见溯源图谱。
            evidence=sorted(
                (
                    evidence_by_id[evidence_id]
                    for evidence_id in mentions_by_evidence
                ),
                key=lambda item: item.evidence_id,
            ),
            communities=communities,
            audit=audit,
        )

    def _orient_pair(
        self,
        source: EntityMention,
        target: EntityMention,
        relation_type: str,
        entities: dict[str, ExtractedEntity],
    ) -> tuple[EntityMention, EntityMention]:
        constraints = self.relation_constraints.get(relation_type)
        if not constraints:
            return source, target
        source_type = entities[source.entity_id].entity_type
        target_type = entities[target.entity_id].entity_type
        if (
            source_type in constraints.get("source", [])
            and target_type in constraints.get("target", [])
        ):
            return source, target
        if (
            target_type in constraints.get("source", [])
            and source_type in constraints.get("target", [])
        ):
            return target, source
        return source, target

    def _criticize(
        self,
        relations: list[ExtractedRelation],
        entities: dict[str, ExtractedEntity],
        evidence: dict[str, EvidenceSpan],
    ) -> None:
        for relation in relations:
            if relation.source_id == relation.target_id:
                relation.criticisms.append("source_equals_target")
            if relation.source_id not in entities or relation.target_id not in entities:
                relation.criticisms.append("unknown_endpoint")
            if relation.relation_type not in self.relation_types:
                relation.criticisms.append("out_of_schema_relation")
            constraints = self.relation_constraints.get(relation.relation_type)
            if constraints:
                source_type = entities[relation.source_id].entity_type
                target_type = entities[relation.target_id].entity_type
                if (
                    source_type not in constraints.get("source", [])
                    or target_type not in constraints.get("target", [])
                ):
                    relation.criticisms.append("schema_type_mismatch")
            if not relation.evidence_ids:
                relation.criticisms.append("missing_evidence")
            elif any(evidence_id not in evidence for evidence_id in relation.evidence_ids):
                relation.criticisms.append("unknown_evidence")
            if relation.relation_type == "RELATED_TO":
                relation.criticisms.append("generic_relation_requires_review")

    def _adjudicate(self, relations: list[ExtractedRelation]) -> None:
        fatal = {
            "source_equals_target",
            "unknown_endpoint",
            "out_of_schema_relation",
            "missing_evidence",
            "unknown_evidence",
            "schema_type_mismatch",
        }
        for relation in relations:
            if fatal.intersection(relation.criticisms):
                relation.status = "rejected"
            elif relation.confidence >= self.accept_threshold and not relation.criticisms:
                relation.status = "accepted"
            else:
                relation.status = "needs_review"

    @staticmethod
    def _build_communities(
        relations: list[ExtractedRelation],
        entities: dict[str, ExtractedEntity],
    ) -> list[dict[str, Any]]:
        adjacency: dict[str, set[str]] = {entity_id: set() for entity_id in entities}
        for relation in relations:
            if relation.status != "accepted":
                continue
            adjacency[relation.source_id].add(relation.target_id)
            adjacency[relation.target_id].add(relation.source_id)

        communities: list[dict[str, Any]] = []
        unseen = set(adjacency)
        while unseen:
            seed = min(unseen)
            stack = [seed]
            members: set[str] = set()
            while stack:
                node = stack.pop()
                if node in members:
                    continue
                members.add(node)
                unseen.discard(node)
                stack.extend(sorted(adjacency[node] - members, reverse=True))
            labels = sorted(entities[node].canonical_name for node in members)
            communities.append(
                {
                    "community_id": _stable_id("community", *sorted(members)),
                    "member_ids": sorted(members),
                    "summary": "、".join(labels),
                    "size": len(members),
                }
            )
        return sorted(communities, key=lambda item: (-item["size"], item["community_id"]))
