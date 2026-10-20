from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from .models import Paper


# PDF 规范允许 %PDF- 落在文件前 1024 字节内的任意位置（前面可以有权属声明之类的垃圾字节），
# 超出这个窗口就不认。2026-10-20 加：PyMuPDF 2.0 起 `pymupdf.open()` 会把 .txt 当文本
# 文档打开（1 页、原文照搬），于是"不是 PDF 就报错"这条行为在升级后悄悄失效了——
# 校验只能自己看文件头，不能指望解析库报错。
PDF_HEADER_WINDOW = 1024
PDF_MAGIC = b"%PDF-"


class NotAPdfError(ValueError):
    """传进来的东西不是 PDF。接口层把它翻成 400，不要当成服务器故障。"""


def looks_like_pdf(head: bytes) -> bool:
    return PDF_MAGIC in head[:PDF_HEADER_WINDOW]


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha1(raw).hexdigest()[:14]}"


def normalize_name(value: str) -> str:
    """返回稳定比较键，同时不破坏中文字符。"""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\s_\-/]+", " ", value)
    value = re.sub(r"[^\w\u4e00-\u9fff ]+", "", value)
    return " ".join(value.split())


# 句末标点：中文全角标点和英文的 ! ? ; 本来就断句；ASCII 句点另走
# ``SchemaGuidedExtractor._period_ends_sentence``，要排掉缩写和小数点。
_STRONG_TERMINATORS = "。！？!?;；"

# 版面折行还原时，行尾出现这些字符就认为这一行本来就说完了，换行保留。
_LINE_END_MARKERS = ".!?;。！？；"

# 英文缩写：这些词后面的句点不是句末。单字母缩写（e.g. / i.e. / U.S. /
# 人名首字母）由长度判断处理，不列在这里。
_ABBREVIATIONS = frozenset(
    {
        "al",
        "approx",
        "cf",
        "ch",
        "chs",
        "ed",
        "eds",
        "eq",
        "eqs",
        "etc",
        "fig",
        "figs",
        "inc",
        "ltd",
        "no",
        "nos",
        "pp",
        "ref",
        "refs",
        "resp",
        "sec",
        "secs",
        "tab",
        "tabs",
        "vol",
        "vols",
        "vs",
    }
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def page_vocabulary(page_texts: Iterable[str]) -> frozenset[str]:
    """收集一批页文本里出现过的英文词形，供断词判定查表。"""
    seen: set[str] = set()
    for text in page_texts:
        seen.update(token.casefold() for token in _TOKEN_PATTERN.findall(text))
    return frozenset(seen)


def unwrap_hard_wrapped_lines(
    text: str,
    vocabulary: frozenset[str] | None = None,
) -> str:
    """把 PDF 版面换行还原成连续正文，同时保留真正的句子边界。

    PDF 解析结果按版面一行一段。行尾换行大多不是句子边界，直接当边界会切出
    半句话的证据跨度：关系触发词留在上一行，实体落在下一行，跨度两头都对不上。
    行尾连字符同样是版面断词（``com-`` / ``prehensive``），接回去时要去掉；但
    ``state-`` / ``of-the-art`` 这种本来就带连字符的复合词要保留。

    规则分两步：
    1. 行尾是句末标点（``.`` ``!`` ``?`` ``;`` 和中文全角）的行本身就是一个句子
       片段，行尾换行保留。其余的行是版面折行，接回上一行。
    2. 接回时看行尾连字符：下一行以小写字母或数字开头时，比对"去掉连字符"和
       "保留连字符"两个词形哪个在本篇出现过；两个都没出现过，按断词处理（PDF
       行尾连字符绝大多数是断词）。``vocabulary`` 为空时一律按断词处理。

    返回值里的 ``\\n`` 就是第 1 步保留下来的句子边界，供 ``_sentence_spans`` 断句；
    折行接回去的位置用空格。这样每个跨度的起止仍然落在页文本上，偏移可以直接
    切回原文。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    sentences: list[str] = []
    current = ""
    for raw_line in normalized.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if current and current.endswith("-"):
            if _line_break_drops_hyphen(current, line, vocabulary):
                # 真断词：去掉行尾连字符再接下一行
                current = current[:-1] + line
            else:
                # 复合词：连字符留着，而且不能再插一个空格进去，
                # 否则会拼出 `state-of- the-art` 这种带空格的复合词。
                current = current + line
        elif current:
            current = f"{current} {line}"
        else:
            current = line
        if current.endswith(_LINE_END_MARKERS):
            sentences.append(current)
            current = ""
    if current:
        sentences.append(current)
    return "\n".join(sentences)


def _line_break_drops_hyphen(
    head: str,
    line: str,
    vocabulary: frozenset[str] | None,
) -> bool:
    piece = re.match(r"[A-Za-z0-9][A-Za-z0-9'\-]*", line)
    if piece is None:
        return False
    following = piece.group(0)
    if following[0].isupper():
        # 下一行以大写字母开头：行尾连字符是复合词的一部分，不是断词。
        return False
    fragment = re.search(r"([A-Za-z][A-Za-z'\-]*)-$", head)
    if fragment is None:
        return False
    # 取"整段复合词"而不是最后一段：`state-of-the-` 要拿 `state-of-the` 去查词表，
    # 只取 `the` 会去比 `theart` / `the-art`，两个都不在词表里，于是把复合词
    # 的连字符当成断词删掉，拼出 `state-ofthe-art`。
    stem = fragment.group(1).casefold()
    if not vocabulary:
        return True
    joined = stem + following.casefold()
    hyphenated = f"{stem}-{following.casefold()}"
    if joined in vocabulary and hyphenated not in vocabulary:
        return True
    if hyphenated in vocabulary and joined not in vocabulary:
        return False
    if joined not in vocabulary and hyphenated not in vocabulary:
        # 两个词形都没在别处出现过：按断词处理，这是行尾连字符的常见情形。
        return True
    # 两个词形都出现过，无法判断，保留连字符。
    return False


def unwrap_pdf_pages(pages: dict[str, str]) -> dict[str, str]:
    """按整篇页文本建词表，再逐页把版面换行接回连续正文。"""
    vocabulary = page_vocabulary(pages.values())
    return {
        section_id: unwrap_hard_wrapped_lines(text, vocabulary)
        for section_id, text in pages.items()
    }


@dataclass(slots=True, frozen=True)
class ScientificDocument:
    paper_id: str
    title: str
    sections: dict[str, str]
    source_url: str = ""
    # 哪个解析器（含版本）产出了 sections。证据偏移是相对 sections 文本算的，
    # 换一个解析器版本重新解析可能整体错位，所以必须跟着记录一起走。
    parser: str = ""

    @classmethod
    def from_paper(cls, paper: Paper) -> "ScientificDocument":
        return cls(
            paper_id=paper.paper_id,
            title=paper.title,
            sections={"abstract": paper.summary},
            source_url=paper.source_url,
            parser="paper-abstract",
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
    # 每篇每节的解析器标识、字符数和文本指纹；证据偏移就是相对这些文本算的，
    # 存下来才能事后核对偏移有没有错位（见 ``KnowledgeGraphStore`` 的 sections 表）。
    sections: list[dict[str, Any]] = field(default_factory=list)
    # 被判定为参考文献区、因而没写进证据表的段落记录（默认关时是空表）。
    # 只进报告，不进库表结构。
    reference_exclusions: list[dict[str, Any]] = field(default_factory=list)

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
            "sections": [dict(item) for item in self.sections],
            "reference_exclusions": [dict(item) for item in self.reference_exclusions],
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
            parser="plain-text",
        )


class PyPDFParser:
    """轻量真实 PDF 解析器，保留页级来源。

    Docling 仍是面向结构的解析器目标；此回退让下载的语料可在 CPU 上立即测试，
    并把每个抽取跨度记录在稳定的 ``page-NNN`` 章节下。页文本先去掉版面硬换行
    （见 ``unwrap_pdf_pages``），否则一条跨度只是版面上的一行而不是一句话，
    证据偏移指向的也是半句话。
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

        with Path(path).open("rb") as handle:
            head = handle.read(PDF_HEADER_WINDOW)
        if not looks_like_pdf(head):
            raise NotAPdfError(f"这个文件不是 PDF：{path}")
        reader = PdfReader(str(path))
        sections = unwrap_pdf_pages(
            {
                f"page-{page_number:03d}": text
                for page_number, page in enumerate(reader.pages, start=1)
                if (text := (page.extract_text() or "").strip())
            }
        )
        return ScientificDocument(
            paper_id=paper_id or path.stem,
            title=title or path.stem,
            sections=sections,
            source_url=source_url or str(path.resolve()),
            parser=PyPDFParser.identity(),
        )

    @staticmethod
    def identity() -> str:
        """解析器标识（含版本）。偏移依赖版本，换版本就可能整体错位。"""
        try:
            import pypdf

            version = getattr(pypdf, "__version__", "unknown")
        except ImportError:  # pragma: no cover - pypdf is the only caller
            version = "unknown"
        return f"pypdf {version}"

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

        if not looks_like_pdf(payload[:PDF_HEADER_WINDOW]):
            raise NotAPdfError("这个文件里找不到 PDF 头（%PDF-），不是 PDF 文件。")
        reader = PdfReader(io.BytesIO(payload))
        sections = unwrap_pdf_pages(
            {
                f"page-{page_number:03d}": text
                for page_number, page in enumerate(reader.pages, start=1)
                if (text := (page.extract_text() or "").strip())
            }
        )
        if not sections:
            raise RuntimeError("PDF 中没有可提取的文本层；扫描版请先 OCR。")
        return ScientificDocument(
            paper_id=paper_id or "uploaded-paper",
            title=title or paper_id or "uploaded-paper",
            sections=sections,
            source_url=source_url or "member-uploaded-pdf",
            parser=PyPDFParser.identity(),
        )


class JatsXmlParser:
    """Europe PMC / PMC 开放获取全文的 JATS XML 解析器。

    只走标准库 ``xml.etree.ElementTree``，不新增第三方依赖。接口与
    ``PyPDFParser`` 一致：``parse(path, *, paper_id, source_url, title)``，
    另给一个不吃文件的 ``parse_text`` 便于测试。

    **确定性页码口径**（XML 没有版面页码，这条口径是定死的，写在代码里也写进
    provenance）：一页 = 一个顶层 ``<sec>``，按文档顺序编号 ``page-001``、
    ``page-002``……。``<body>`` 里排在所有顶层 ``<sec>`` 之前的段落算"正文前言"，
    单独占最先的一页；有前言时第一个顶层 ``<sec>`` 就从 ``page-002`` 起。顶层
    ``<sec>`` 的顺序按文档顺序，一个 ``<sec>`` 只有标题、收不出正文块时不占页
    （页码不留空洞）。每个顶层 ``<sec>`` 的正文收它自己以及它底下所有嵌套
    ``<sec>`` 里的正文块，块之间用一个换行分隔。字符偏移一律相对这一页的文本
    算，与 PDF 那条路（``page-NNN`` 就是 PDF 页）保持一致，证据跨度照样能逐字
    切回原文。

    **每页放进去的正文块**：所有 ``<p>``；小节 ``<title>``；``<list>`` 里的
    ``<list-item>``；``<fig>`` / ``<table-wrap>`` / ``<supplementary-material>``
    的 ``<caption>`` 与 ``<label>`` 各算一块。``<xref>``、``<italic>``、``<bold>``
    这类行内标签只去掉标签、文字保留，一句话不会从中间被切开；``<table-wrap>``
    里的 ``<table>`` 单元格不收（免得把数字网格塞进页文本），表格只靠 caption
    取证。

    **输入底线**：``<body>`` 不存在、一个顶层 ``<sec>`` 都没有、或者整篇只有
    小节标题而没有任何 ``<p>`` 正文，都抛 ``ValueError``，不静默产出空文本。
    ``<body>`` 之外的 ``<back>``（致谢、参考文献等）不进页文本。

    **命名空间**：JATS 有 ``-//NLM//DTD JATS`` 与 ``journalpublishing`` 两套 DTD，
    前缀不同、甚至无前缀。解析时统一用 ``{*}tag`` 匹配，两种都能过。文档类型
    声明里的外部 DTD 不联网取（``ElementTree`` 默认就不取），实体引用只认 XML
    自带的五个；引到没声明的实体就按不合法 XML 处理，抛异常并带出原始报错。
    """

    _PARSER_VERSION = "jats-xml-v1"

    def parse(
        self,
        path: Path,
        *,
        paper_id: str | None = None,
        source_url: str = "",
        title: str = "",
    ) -> ScientificDocument:
        return self.parse_text(
            _read_xml_text(path),
            paper_id=paper_id or path.stem,
            source_url=source_url or str(path.resolve()),
            title=title,
        )

    def parse_text(
        self,
        payload: str,
        *,
        paper_id: str,
        source_url: str = "",
        title: str = "",
    ) -> ScientificDocument:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError(
                f"{paper_id}: JATS XML 不合法，解析失败（{exc}）；"
                "本解析器不猜内容，也不会产出空文本。"
            ) from exc

        sections, has_body_text = self._body_sections(root)
        if not sections:
            raise ValueError(
                f"{paper_id}: 这份 JATS XML 的 <body> 里一个顶层 <sec> 都没有，"
                "也读不到正文前言；拒绝静默产出空文本。"
            )
        if not has_body_text:
            raise ValueError(
                f"{paper_id}: 这份 JATS XML 的 <body> 里只有小节标题，没有任何段落"
                "（<p>）正文；拒绝静默产出空文本。"
            )
        return ScientificDocument(
            paper_id=paper_id,
            title=title or _jats_title(root) or paper_id,
            sections=sections,
            source_url=source_url,
            parser=self.identity(),
        )

    @classmethod
    def identity(cls) -> str:
        """解析器标识（含版本）。页码口径变了就要换版本号。"""
        return cls._PARSER_VERSION

    @classmethod
    def _body_sections(cls, root: ET.Element) -> tuple[dict[str, str], bool]:
        """把 <body> 摊成虚拟页。

        返回 (页字典, 有没有真正的段落正文)。第二项用来判"整篇只有标题、没有
        <p>"这种空壳输入：页字典非空也不该当成功。
        """
        body = _jats_find(root, "body")
        if body is None:
            return {}, False
        top_level = _jats_blocks(body)
        preamble: list[str] = []
        pages: list[list[str]] = []
        has_body_text = False
        for child in top_level:
            if _local_name(child.tag) == "sec":
                blocks, section_has_body = cls._section_blocks(child)
                pages.append(blocks)
                has_body_text = has_body_text or section_has_body
            else:
                # body 直接挂着的 <p> 属于正文前言，单独占最先的一页。
                blocks = _jats_block_texts(child)
                if blocks:
                    preamble.extend(blocks)
                    has_body_text = has_body_text or _has_paragraph_text(child)
        pages = [page for page in pages if page]
        if preamble:
            pages.insert(0, preamble)
        sections = {
            f"page-{number:03d}": "\n".join(blocks)
            for number, blocks in enumerate(pages, start=1)
        }
        return sections, has_body_text

    @classmethod
    def _section_blocks(cls, sec: ET.Element) -> tuple[list[str], bool]:
        """收一个顶层 sec 自己与它所有后代 sec 的正文块，按文档顺序。

        返回 (正文块列表, 有没有段落级正文)。标题、图注、表注不算段落级正文。
        """
        blocks: list[str] = []
        has_body_text = False
        for element in _jats_blocks(sec):
            if _local_name(element.tag) == "sec":
                nested_blocks, nested_has_body = cls._section_blocks(element)
                blocks.extend(nested_blocks)
                has_body_text = has_body_text or nested_has_body
                continue
            blocks.extend(_jats_block_texts(element))
            has_body_text = has_body_text or _has_paragraph_text(element)
        return blocks, has_body_text


def _read_xml_text(path: Path) -> str:
    """读 JATS XML 源文件。多数是 UTF-8；不是就退回 cp1252，不因编码炸掉。"""
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: XML 既不是 UTF-8 也不是 cp1252，无法读取。")


def _local_name(tag: Any) -> str:
    """取标签名，顺手去掉两套 JATS DTD 带来的命名空间前缀。"""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _jats_find(element: ET.Element, name: str) -> ET.Element | None:
    """按标签名找第一个后代。``{*}name`` 对有无命名空间的 XML 都成立。"""
    return element.find(f".//{{*}}{name}")


def _jats_text(element: ET.Element) -> str:
    """取一个元素的全部文字：标签去掉、文字全留，相邻文字块之间补一个空格。

    ``<italic>``、``<xref>`` 这类行内标签不能当分隔点处理，否则会把一句话从
    中间切开，切出来的证据跨度就取不回原文。
    """
    return _join_xml_pieces(_collect_xml_pieces(element))


def _collect_xml_pieces(element: ET.Element) -> list[str]:
    """按文档顺序收一个元素下的全部文字（含后代与 tail），空白的丢掉。"""
    pieces: list[str] = []
    if element.text and element.text.strip():
        pieces.append(element.text)
    for child in element:
        pieces.extend(_collect_xml_pieces(child))
        if child.tail and child.tail.strip():
            pieces.append(child.tail)
    return pieces


def _join_xml_pieces(pieces: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(piece.strip() for piece in pieces)).strip()


_PARAGRAPH_TAGS = frozenset({"p", "list-item", "def", "statement", "disp-quote"})
_CONTAINER_TAGS = frozenset({"list", "fig", "table-wrap", "supplementary-material"})
# 这些标签本身承载正文，整块收；其余认不出的孩子（例如 <table> 的单元格）不收，
# 免得把表格里的数字网格塞进页文本。
_TEXT_BLOCK_TAGS = _PARAGRAPH_TAGS | {"title", "caption", "label"}


def _jats_blocks(element: ET.Element) -> list[ET.Element]:
    """取一个容器的子元素（JATS 里正文块都挂在容器的一层子节点下）。"""
    return list(element)

def _has_paragraph_text(element: ET.Element) -> bool:
    """判断这个元素（含图、表这类容器）底下有没有段落级正文。"""
    if _local_name(element.tag) in _PARAGRAPH_TAGS:
        return bool(_jats_text(element))
    return any(_has_paragraph_text(child) for child in element)


def _jats_block_texts(element: ET.Element) -> list[str]:
    """按文档顺序取出一个容器下的正文块，空的丢掉。

    调用方传进来的可能是段落本身，也可能是装段落、列表、图表的小节容器：
    段落整段算一块（行内标签的文字一起收），小节容器逐个孩子处理。
    """
    if _local_name(element.tag) in _PARAGRAPH_TAGS:
        text = _jats_text(element)
        return _tail_block(element, [text] if text else [])
    blocks: list[str] = []
    if element.text and element.text.strip():
        blocks.append(re.sub(r"\s+", " ", element.text).strip())
    for child in element:
        child_tag = _local_name(child.tag)
        if child_tag in _TEXT_BLOCK_TAGS:
            text = _jats_text(child)
            blocks.extend(_tail_block(child, [text] if text else []))
        elif child_tag in _CONTAINER_TAGS:
            blocks.extend(_jats_block_texts(child))
    return [block for block in blocks if block]


def _tail_block(element: ET.Element, blocks: list[str]) -> list[str]:
    """收完元素本身这一块后，把它的 tail 文字也接上，别丢字。"""
    tail = element.tail
    if tail and tail.strip():
        return [*blocks, re.sub(r"\s+", " ", tail).strip()]
    return blocks


def _jats_title(root: ET.Element) -> str:
    """取文章标题：清单没给 title 时用 JATS 自己的（正文里的小节标题有单独处理）。"""
    for element in root.iter():
        if _local_name(element.tag) in {"article-title", "title"}:
            text = _jats_text(element)
            if text:
                return text
    return ""


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
        document = PlainTextParser().parse_text(
            markdown,
            paper_id=paper_id or path.stem,
            fallback_title=path.stem,
            source_url=str(path.resolve()),
        )
        return replace(document, parser="docling")


# --------------------------------------------------------------------------
# 别名词边界口径
#
# ``_alias_pattern`` 给英文别名加词边界，原来是 ``(?<![A-Za-z0-9])…(?![A-Za-z0-9])``。
# 这个字符类**只覆盖 ASCII**：PDF 里的合字 ``ﬁ`` / ``ﬂ``（U+FB01 / U+FB02）与法语重音
# 字母（``è`` 之类）都不在里面，于是短别名会命中词内部——实测 ``RE`` 命中
# ``reﬁning`` 的开头两个字符、命中 ``manière`` 结尾的 ``re``，``NED`` 命中
# ``deﬁned`` 里 ``ﬁ`` 后面的 ``ned``。
#
# ``unicode`` 口径把边界换成"Unicode 字母或数字"（正则类目 ``[^\W_]``：``\w`` 去掉
# 下划线），合字与重音字母都算作相邻字的组成部分，这类词内匹配不会再出现。
# **默认 ``ascii``**：不传开关时 pattern 与从前逐字一致，基线可复现。
# --------------------------------------------------------------------------

#: 词边界口径。``ascii`` = 从前的行为（默认），``unicode`` = 把合字/重音字母也算作字内。
WORD_BOUNDARY_MODES = ("ascii", "unicode")

#: 两种口径下"算作字的一部分"的字符类（正则类目内部写法，不含方括号）。
_WORD_BOUNDARY_CLASS = {
    "ascii": "[A-Za-z0-9]",
    "unicode": r"[^\W_]",
}

# --------------------------------------------------------------------------
# ``REPORTS`` 的扩展触发词
#
# 本体 ``data/knowledge/extraction_schema.json`` 里 ``REPORTS`` 只有
# ``report / reports / show / shows / 表明 / 发现 / 结果显示`` 这几个触发词，
# 于是"报告某个数值/某个指标"的句子（``achieves 95.4% F1``、``obtains 3.2 points``、
# ``达到 92.3%``）一个都命不中，被判成别的类型或者兜底成 ``RELATED_TO``。
#
# 这份常量**不在本体里改**：本体是共用资产，改它等于改所有下游的口径。开关
# ``reports_triggers="extended"`` 打开时，这些写法追加到 ``REPORTS`` 的触发词后面；
# 默认 ``"schema"``，只用本体里那几条。
# --------------------------------------------------------------------------

#: ``REPORTS`` 的扩展触发词（正则片段）。英文那几条按 ASCII 词边界匹配，中文不加边界。
REPORTS_TRIGGER_EXTRA: tuple[str, ...] = (
    r"report(s|ed|ing)?",
    r"achieve(s|d)?",
    r"obtain(s|ed)?",
    r"reach(es|ed)?",
    r"gain(s|ed)?",
    r"attain(s|ed)?",
    r"outperform(s|ed)?",
    # 动词后面紧跟数值或百分比才算报数：``improves 4.2%``、``improved by 3.1 points``。
    r"improv(e|es|ed)\s+(?:by\s+)?\d+(?:\.\d+)?\s*%?",
    r"shows?\s+(?:that|an?|the)\b",
    "报告",
    "达到",
    "取得",
    "提升到",
    "降至",
    "测得",
)


class SchemaGuidedExtractor:
    """以证据优先的科学实体/关系抽取基线。

    它刻意将抽取、批判与裁决分离，这样后续用 DeepKE/LLM 提出者替换时，
    只需替换提出阶段，而不影响其它环节。

    三处质量修复各有一个开关，**默认全部关着**，不传时与从前逐字一致：

    - ``word_boundary="ascii"|"unicode"``：别名词边界口径。``ascii``（默认）是从前的
      ``[A-Za-z0-9]``；``unicode`` 把 Unicode 字母（含 PDF 合字 ``ﬁ`` / ``ﬂ`` 与重音
      字母）也算作"字的一部分"，短别名不再命中词内部。见上面的口径说明。
    - ``direction_check=False``：确定性批判者里"关系方向是不是写反了"这条检查。
      默认关，关着时连判据函数都不会被调用。
    - ``reports_triggers="schema"|"extended"``：``REPORTS`` 的触发词表用本体里那几条
      （默认），还是把 ``REPORTS_TRIGGER_EXTRA`` 也并进来。本体文件一个字节都不改。

    ``relation_pairing`` 决定"同一段里多个实体怎么配成关系"，**默认 ``"legacy"``**，
    也就是从前的行为一个字节都不动，基线照样可复现：

    - ``"legacy"``：同一段里的实体按出现位置两两组合（``itertools.combinations``），
      命中触发词就用触发的类型，没命中就兜底成 ``RELATED_TO``。一段话里实体一多，
      配对数按 ``实体数 × (实体数 - 1) / 2`` 涨，跟"这段话里有几对真的有关系"无关；
      全文库实测每篇关系数因此到过 167.88 条。
    - ``"trigger_between"``：收紧成两条规则——
      ① **没命中触发词就不生成关系**（去掉 ``RELATED_TO`` 兜底）；
      ② 命中的触发词必须**落在两个实体之间**，或者**紧邻其中一个实体**
         （触发词与那个实体之间的字符数不超过 ``TRIGGER_ADJACENCY_WINDOW``，默认 40），
         否则这一对不生成关系。
      两条规则针对的都是"两两组合会随实体数平方膨胀"这件事：一段话里实体越多，
      两两组合里跟这句话真正在说的关系无关的配对就越多，而这些配对全部会被
      ``_criticize`` 打成 ``generic_relation_requires_review`` 或
      ``schema_type_mismatch``，既进不了接收集，也把待审队列撑大。
    """

    #: ``"trigger_between"`` 模式下"紧邻"的窗口：触发词与实体跨度之间最多隔多少个字符。
    TRIGGER_ADJACENCY_WINDOW = 40

    #: 允许的关系配对模式。
    RELATION_PAIRING_MODES = ("legacy", "trigger_between")

    #: ``REPORTS`` 触发词的两种口径。
    REPORTS_TRIGGER_MODES = ("schema", "extended")

    #: "前向动词"命中的关系类型：主语（头实体）在动词前、宾语（尾实体）在动词后。
    #: 方向检查只对这几类生效——``SUPPORTS`` / ``CONTRADICTS`` / ``BENCHMARKS`` /
    #: ``ADDRESSES`` 的典型句式不是这种语序，判了只会误伤。
    FORWARD_RELATION_TYPES = frozenset(
        {"USES", "ENABLES", "IMPROVES", "EXTENDS", "REPORTS", "EVALUATES_ON"}
    )

    def __init__(
        self,
        schema: dict[str, Any],
        *,
        accept_threshold: float = 0.72,
        relation_pairing: str = "legacy",
        drop_reference_spans: bool = False,
        word_boundary: str = "ascii",
        direction_check: bool = False,
        reports_triggers: str = "schema",
    ) -> None:
        if relation_pairing not in self.RELATION_PAIRING_MODES:
            raise ValueError(
                f"relation_pairing 只能是 {' / '.join(self.RELATION_PAIRING_MODES)}，"
                f"收到 {relation_pairing!r}"
            )
        if word_boundary not in WORD_BOUNDARY_MODES:
            raise ValueError(
                f"word_boundary 只能是 {' / '.join(WORD_BOUNDARY_MODES)}，"
                f"收到 {word_boundary!r}"
            )
        if reports_triggers not in self.REPORTS_TRIGGER_MODES:
            raise ValueError(
                f"reports_triggers 只能是 {' / '.join(self.REPORTS_TRIGGER_MODES)}，"
                f"收到 {reports_triggers!r}"
            )
        self.schema = schema
        self.accept_threshold = accept_threshold
        self.relation_pairing = relation_pairing
        # 默认关：不传这个开关时抽取路径与从前逐字一致（连判据函数都不会被调用）。
        self.drop_reference_spans = drop_reference_spans
        # 下面三个开关默认也全关：默认值与从前逐字一致，量出来的差就是修复本身。
        self.word_boundary = word_boundary
        self.direction_check = direction_check
        self.reports_triggers = reports_triggers
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
            (self._alias_pattern(alias, word_boundary), alias, canonical, entity_type)
            for alias, canonical, entity_type in self.alias_entries
        ]
        # 触发词同样预编译，并按 schema 里的先后顺序保留优先级。
        # ``reports_triggers="extended"`` 时，把扩展触发词接在 ``REPORTS`` 那一条
        # 自己的触发词后面：同一位置命中两种写法时，本体里的写法仍然排在前面。
        self.compiled_triggers: list[tuple[re.Pattern[str], str]] = []
        for pattern in schema["relation_patterns"]:
            for trigger in pattern["triggers"]:
                self.compiled_triggers.append(
                    (self._trigger_pattern(trigger), pattern["relation_type"])
                )
            if (
                reports_triggers == "extended"
                and pattern["relation_type"] == "REPORTS"
            ):
                for source in REPORTS_TRIGGER_EXTRA:
                    self.compiled_triggers.append(
                        (self._extra_trigger_pattern(source), "REPORTS")
                    )

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        accept_threshold: float = 0.72,
        relation_pairing: str = "legacy",
        drop_reference_spans: bool = False,
        word_boundary: str = "ascii",
        direction_check: bool = False,
        reports_triggers: str = "schema",
    ) -> "SchemaGuidedExtractor":
        schema = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            schema,
            accept_threshold=accept_threshold,
            relation_pairing=relation_pairing,
            drop_reference_spans=drop_reference_spans,
            word_boundary=word_boundary,
            direction_check=direction_check,
            reports_triggers=reports_triggers,
        )

    @staticmethod
    def _sentence_spans(text: str) -> Iterable[tuple[int, int, str]]:
        # Markdown 证据卡通常每行一句且没有句末标点。若只用 ``$`` 匹配
        # 只会捕获最后一行，静默丢弃该节其余内容。这里把换行当作句子边界，
        # 同时保留稳定的文档相对偏移。
        #
        # 英文全文还要认 ASCII 句点：原先把 ``.`` 排除在句末标点之外，页文本
        # 一旦把硬换行接回去（见 ``unwrap_hard_wrapped_lines``），整页就会变成
        # 一条跨度，关系触发词和实体被埋在同一个大片段里。缩写和小数点仍然不断句。
        length = len(text)
        cursor = 0
        start = 0
        while cursor < length:
            char = text[cursor]
            cut = -1
            if char == "\n":
                cut = cursor
                cursor += 1
            elif char in _STRONG_TERMINATORS:
                cursor += 1
                while cursor < length and text[cursor] in _STRONG_TERMINATORS:
                    cursor += 1
                cut = cursor
            elif char == ".":
                if SchemaGuidedExtractor._period_ends_sentence(text, cursor):
                    cursor += 1
                    cut = cursor
                else:
                    cursor += 1
            else:
                cursor += 1
            if cut >= 0:
                yield from SchemaGuidedExtractor._trimmed_span(text, start, cut)
                start = cursor
        if start < length:
            yield from SchemaGuidedExtractor._trimmed_span(text, start, length)

    @staticmethod
    def _trimmed_span(text: str, start: int, end: int) -> Iterable[tuple[int, int, str]]:
        raw = text[start:end]
        sentence = raw.strip()
        if sentence:
            leading = len(raw) - len(raw.lstrip())
            yield start + leading, start + leading + len(sentence), sentence

    @staticmethod
    def _period_ends_sentence(text: str, index: int) -> bool:
        """判断页文本里的 ASCII 句点是不是句末（英文全文断句用）。"""
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if next_char and not next_char.isspace():
            # 后面紧跟字符：小数、编号、网址、U.S. 这类内部句点。
            return False
        previous = text[index - 1] if index else ""
        if previous in ".!?":
            # 省略号或重复标点，只在最后一个点上断句。
            return False
        word = re.search(r"([A-Za-z]+)\s*$", text[:index])
        if word is None:
            # 前面不是字母：编号（"3."）、符号、行首句点。
            return False
        token = word.group(1)
        if len(token) == 1:
            # 单个字母：人名缩写（"J. Smith"）、"e.g." / "i.e." / "U.S."。
            return False
        return token.casefold() not in _ABBREVIATIONS

    @staticmethod
    def _alias_pattern(alias: str, word_boundary: str = "ascii") -> re.Pattern[str]:
        """别名的匹配式。英文别名加词边界，``word_boundary`` 决定边界认哪些字符。

        ``ascii``（默认）用 ``[A-Za-z0-9]``，与从前逐字一致；``unicode`` 用 ``[^\\W_]``
        （Unicode 字母或数字，不含下划线），PDF 合字 ``ﬁ`` / ``ﬂ`` 与重音字母都算字内，
        短别名不会再命中词内部。
        """
        escaped = re.escape(alias)
        if re.fullmatch(r"[A-Za-z0-9 _\-/]+", alias):
            boundary = _WORD_BOUNDARY_CLASS[word_boundary]
            escaped = rf"(?<!{boundary}){escaped}(?!{boundary})"
        return re.compile(escaped, re.IGNORECASE)

    @staticmethod
    def _extra_trigger_pattern(source: str) -> re.Pattern[str]:
        """把 ``REPORTS_TRIGGER_EXTRA`` 里的一条（正则片段）编译成 pattern。

        英文那几条按 ASCII 词边界匹配（与本体里的英文触发词同口径）；纯中文的
        不加边界——中文没有词边界，加了等于一条都命中不了。
        """
        pattern = source
        if re.search(r"[A-Za-z]", source):
            pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
        return re.compile(pattern, re.IGNORECASE)

    @staticmethod
    def _trigger_pattern(trigger: str) -> re.Pattern[str]:
        """触发词按词匹配；中文触发词没有词边界，仍按子串匹配。

        原先是 ``trigger in sentence``，于是 ``because`` 里的 ``use`` 会命中
        USES、``focuses`` 里的 ``use`` 同样命中、``evidenced`` 会命中 SUPPORTS。
        英文触发词加词边界；多词触发词（``evaluate on``）里的空格允许换行。
        """
        escaped = re.escape(trigger.strip()).replace("\\ ", r"\s+")
        if re.fullmatch(r"[A-Za-z0-9 _\-/]+", trigger):
            escaped = rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])"
        return re.compile(escaped, re.IGNORECASE)

    def _trigger_spans(self, sentence: str) -> list[tuple[int, int, str]]:
        """一句里所有命中的触发词，按 (起, 止, 关系类型) 返回，顺序就是 schema 里的优先级。

        触发词的位置是"配对该不该生成"的判据：一段话里的实体两两组合之后，
        哪一对是真的由这句话里的触发词管着，得看触发词落在这两个实体的中间还是紧挨着
        其中一个。返回全部命中而不是只返回第一个，是因为一句话里可能有两个触发词，
        分别管着两对不同的实体。
        """
        hits: list[tuple[int, int, str]] = []
        for pattern, relation_type in self.compiled_triggers:
            for match in pattern.finditer(sentence):
                hits.append((match.start(), match.end(), relation_type))
        hits.sort(key=lambda item: (item[0], item[1]))
        return hits

    def _relation_type_for_sentence(self, sentence: str) -> tuple[str, bool]:
        hits = self._trigger_spans(sentence)
        if hits:
            return hits[0][2], True
        return "RELATED_TO", False

    @staticmethod
    def _span_gap(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
        """两段文本之间隔了多少个字符；有重叠或相邻时是 0。"""
        if left_end <= right_start:
            return right_start - left_end
        if right_end <= left_start:
            return left_start - right_end
        return 0

    def _pair_relation_type(
        self,
        first_span: tuple[int, int],
        second_span: tuple[int, int],
        trigger_spans: list[tuple[int, int, str]],
    ) -> str | None:
        """``trigger_between`` 模式：这一对实体该配成哪种关系；配不上就返回 None。

        两条规则（和类 docstring 里写的是同两条）：

        1. **没有触发词就没有关系**（调用方已经保证 ``trigger_spans`` 非空，返回 None
           只可能来自下面第 2 条）；
        2. 触发词必须落在两个实体的跨度之间，或者紧邻其中一个实体——触发词与那个实体
           之间最多隔 ``TRIGGER_ADJACENCY_WINDOW`` 个字符。隔得太远的触发词管的是
           同一段里另外的实体对，不算在这一对头上。

        多个触发词同时满足时取句中出现位置最靠前的那个（与 legacy 模式"取第一个命中
        的触发词"口径一致），schema 里的优先级在 ``_trigger_spans`` 里已经排进顺序。
        """
        ordered = sorted((first_span[0], first_span[1], second_span[0], second_span[1]))
        left_start, left_end, right_start, right_end = ordered
        best: tuple[int, str] | None = None
        for start, end, relation_type in trigger_spans:
            between = left_end <= start and end <= right_start
            touches_left = end <= left_start and left_start - end <= self.TRIGGER_ADJACENCY_WINDOW
            touches_right = right_end <= start and start - right_end <= self.TRIGGER_ADJACENCY_WINDOW
            if not (between or touches_left or touches_right):
                continue
            if best is None or start < best[0]:
                best = (start, relation_type)
        return best[1] if best else None

    def extract_papers(self, papers: Iterable[Paper]) -> ExtractionResult:
        return self.extract_documents(ScientificDocument.from_paper(paper) for paper in papers)

    def extract_documents(self, documents: Iterable[ScientificDocument]) -> ExtractionResult:
        document_list = list(documents)
        evidence_by_id: dict[str, EvidenceSpan] = {}
        entities: dict[str, ExtractedEntity] = {}
        mentions_by_evidence: dict[str, list[EntityMention]] = {}
        relation_buckets: dict[tuple[str, str, str], ExtractedRelation] = {}
        section_records: list[dict[str, Any]] = []
        reference_exclusions: list[dict[str, Any]] = []

        for document in document_list:
            content_sections = {"title": document.title, **document.sections}
            section_records.extend(
                {
                    "paper_id": document.paper_id,
                    "section_id": section_id,
                    "parser": document.parser or "unknown",
                    "char_count": len(text),
                    # 个别 PDF 抽出的文字带落单代理字符，直接 encode 会抛
                    # UnicodeEncodeError；替换成 U+FFFD，指纹照样稳定可复现。
                    "text_sha256": hashlib.sha256(
                        text.encode("utf-8", errors="replace")
                    ).hexdigest(),
                }
                for section_id, text in content_sections.items()
            )
            # 参考文献段识别只在开关打开时跑：关着的时候连判据都不调用，
            # 抽取路径与从前逐字一致。XML（JATS）那条路整篇跳过判定——
            # 参考文献在 <back> 里、解析器本来就没收，判了只会误伤正文页。
            judge_references = self.drop_reference_spans and not (
                parser_skips_reference_judgement(document.parser)
            )
            # 信号 B 要按"这一段在论文后 1/3 里吗"来放行，所以先算一次全篇页数。
            page_total = (
                reference_page_total(content_sections) if judge_references else 0
            )
            for section_id, text in content_sections.items():
                region = (
                    reference_region(
                        text,
                        page_number=reference_page_number(section_id),
                        page_total=page_total,
                    )
                    if judge_references
                    else None
                )
                excluded_span_count = 0
                excluded_evidence_count = 0
                for sentence_index, (start, end, sentence) in enumerate(
                    self._sentence_spans(text)
                ):
                    excluded = region is not None and start >= region.char_start
                    evidence_id = (
                        f"evidence:{document.paper_id}:"
                        f"{_stable_id('section', section_id).split(':')[1]}:{sentence_index}"
                    )
                    seen_mentions: set[tuple[str, int, int]] = set()
                    occupied_spans: list[tuple[int, int]] = []
                    matched: list[tuple[EntityMention, str, str, str]] = []
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
                            matched.append(
                                (
                                    EntityMention(
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
                                    ),
                                    canonical,
                                    entity_type,
                                    match.group(0),
                                )
                            )
                            occupied_spans.append((match.start(), match.end()))
                    if excluded:
                        # 引文区里的跨度不写进证据表：不建证据、不建实体、不配关系。
                        # 但命中的实体先照样数一遍，好让报告说清"排掉了多少条本来会
                        # 进证据表的跨度"，而不是只报"排掉了多少句"。
                        excluded_span_count += 1
                        if matched:
                            excluded_evidence_count += 1
                        continue
                    evidence_by_id[evidence_id] = EvidenceSpan(
                        evidence_id=evidence_id,
                        paper_id=document.paper_id,
                        section_id=section_id,
                        sentence_index=sentence_index,
                        text=sentence,
                        char_start=start,
                        char_end=end,
                    )
                    for mention, canonical, entity_type, surface in matched:
                        entity = entities.setdefault(
                            mention.entity_id,
                            ExtractedEntity(
                                entity_id=mention.entity_id,
                                canonical_name=canonical,
                                entity_type=entity_type,
                            ),
                        )
                        entity.aliases.add(surface)
                        entity.mentions.append(mention)
                        mentions_by_evidence.setdefault(evidence_id, []).append(mention)
                if region is not None:
                    reference_exclusions.append(
                        {
                            "paper_id": document.paper_id,
                            "section_id": section_id,
                            "signal": region.signal,
                            "heading": region.heading,
                            "char_start": region.char_start,
                            "char_end": region.char_end,
                            "sentence_count": region.sentence_count,
                            "citation_sentence_count": region.citation_sentence_count,
                            "citation_share": region.citation_share,
                            "excluded_sentence_count": excluded_span_count,
                            "excluded_evidence_count": excluded_evidence_count,
                        }
                    )

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
            trigger_spans = self._trigger_spans(evidence.text)
            if self.relation_pairing == "trigger_between":
                # 规则①：没命中触发词就不生成关系。legacy 模式在这里兜底成 RELATED_TO，
                # 于是"同一段里碰巧都出现过"也被记成一条关系。
                if not trigger_spans:
                    continue
                relation_type, matched_trigger = trigger_spans[0][2], True
            else:
                relation_type, matched_trigger = self._relation_type_for_sentence(evidence.text)
            ordered_mentions = sorted(first_mentions.values(), key=lambda item: item.char_start)
            for source_mention, target_mention in combinations(ordered_mentions, 2):
                pair_type = relation_type
                if self.relation_pairing == "trigger_between":
                    # 规则②：触发词要落在这两个实体之间，或者紧邻其中一个；配不上就跳过。
                    picked = self._pair_relation_type(
                        (source_mention.char_start, source_mention.char_end),
                        (target_mention.char_start, target_mention.char_end),
                        trigger_spans,
                    )
                    if picked is None:
                        continue
                    pair_type = picked
                source_mention, target_mention = self._orient_pair(
                    source_mention,
                    target_mention,
                    pair_type,
                    entities,
                )
                key = (
                    source_mention.entity_id,
                    target_mention.entity_id,
                    pair_type,
                )
                relation = relation_buckets.setdefault(
                    key,
                    ExtractedRelation(
                        relation_id=_stable_id("relation", *key),
                        source_id=source_mention.entity_id,
                        target_id=target_mention.entity_id,
                        relation_type=pair_type,
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
            sections=section_records,
            reference_exclusions=reference_exclusions,
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
            if self.direction_check:
                # 默认关：不传 direction_check=True 时连这条判据都不算。
                relation.criticisms.extend(
                    self._direction_criticisms(relation, entities, evidence)
                )

    @staticmethod
    def _first_mention_in(
        entities: dict[str, ExtractedEntity],
        entity_id: str,
        evidence_id: str,
    ) -> EntityMention | None:
        """某个实体在这条证据里的第一个提及（与配关系时取的"第一个提及"同口径）。"""
        entity = entities.get(entity_id)
        if entity is None:
            return None
        mentions = [
            mention for mention in entity.mentions if mention.evidence_id == evidence_id
        ]
        if not mentions:
            return None
        return min(mentions, key=lambda item: item.char_start)

    def _direction_criticisms(
        self,
        relation: ExtractedRelation,
        entities: dict[str, ExtractedEntity],
        evidence: dict[str, EvidenceSpan],
    ) -> list[str]:
        """方向检查：前向动词的语序是不是被我们记反了。

        判据只有一条，落在**每条证据自己身上**：这句话里命中了一个"前向动词"
        （``uses / enables / improves / extends / reports / evaluate on`` 及其词形，
        见 ``FORWARD_RELATION_TYPES``），而**尾实体出现在触发词之前、头实体出现在
        触发词之后**——那这句话读下来是"尾实体做动作、头实体挨动作"，与我们记下的
        ``头实体 --类型--> 尾实体`` 正好相反。

        举一个实例（``RN-S-003`` 那条强干扰）：原文 ``We evaluate SCIIE on SCIERC``，
        意思是 ``SCIIE -EVALUATES_ON-> SCIERC``；把它写成 ``SCIERC -EVALUATES_ON->
        SCIIE`` 就是反的。这句话里触发词 ``evaluate on`` 落在 ``SCIIE`` 与 ``SCIERC``
        中间，按语序读出来的方向是"前一个实体指向后一个实体"，反过来写的那条就与
        语序冲突。

        命中时只**降级**（``criticisms`` 里加一条，裁决阶段落到 ``needs_review``），
        不直接丢：被动语态、从句前置、"A, unlike B, uses C" 这些句式都会让语序与
        语义方向对不上，机器判不准的时候交给待复核队列，而不是当成错关系删掉。

        返回的是写给人看的依据串：触发词是哪个、在句内第几个字符，两个实体各在
        第几个字符。同一对实体在另一条证据里语序正常时，这里照样会报——因为只要
        **有一条**证据读出来是反的，这条关系就该人看一眼。
        """
        findings: list[str] = []
        for evidence_id in relation.evidence_ids:
            span = evidence.get(evidence_id)
            if span is None:
                continue
            source_mention = self._first_mention_in(
                entities, relation.source_id, evidence_id
            )
            target_mention = self._first_mention_in(
                entities, relation.target_id, evidence_id
            )
            if source_mention is None or target_mention is None:
                continue
            for start, end, relation_type in self._trigger_spans(span.text):
                if relation_type not in self.FORWARD_RELATION_TYPES:
                    continue
                reversed_order = (
                    target_mention.char_end <= start
                    and end <= source_mention.char_start
                )
                if not reversed_order:
                    continue
                findings.append(
                    "direction_suspect:"
                    f"触发词「{span.text[start:end]}」({relation_type}) 在句内 "
                    f"[{start},{end})，尾实体「{target_mention.surface_form}」在 "
                    f"[{target_mention.char_start},{target_mention.char_end})，"
                    f"头实体「{source_mention.surface_form}」在 "
                    f"[{source_mention.char_start},{source_mention.char_end})；"
                    "尾实体在触发词之前、头实体在触发词之后，与记录的方向相反，"
                    "降级待复核。"
                )
                break
        return findings

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


# --------------------------------------------------------------------------
# 参考文献段识别
#
# 抽取管线原来把论文末尾的参考文献表也当正文收进来：句子里照样有领域名词，
# 于是既算成"证据命中"、又算成一条"独立样本"。这一段给出两个判据，
# 把引文区找出来，交给 ``SchemaGuidedExtractor(drop_reference_spans=True)``
# 决定要不要排除。**默认不排除**，开关在命令行上叫 ``--drop-reference-spans``。
#
# 一句话分工：
#   * 信号 A（段落标题）——稳，只要认出来就一定对；漏在"标题没被解析出来"和
#     "参考文献跨多页、后几页没有标题"这两种情况上。
#   * 信号 B（版式/统计）——兜上面两种漏，代价是可能把正文页里引文多的页误伤。
# 两个信号都命中时以信号 A 的区间为准（标题之前的内容照旧算正文）。
# --------------------------------------------------------------------------

#: 参考文献类标题的写法（大小写不敏感）。命中处还必须落在行首或句末标点之后，
#: 且标题后面不能紧跟小写字母——正文里 "… (2021). References to prior work are …"
#: 这种写法就靠这条挡住。
REFERENCE_HEADINGS: tuple[str, ...] = (
    "references",
    "bibliography",
    "works cited",
    "literature cited",
    "参考文献",
    "引用文献",
)

#: 标题判据。允许前面带小节编号（``7 References`` / ``7. References``，
#: 也允许 PDF 抽出来的页码粘在前面，例如 ``7515 References``——实测
#: ``2020.acl-main.670`` 的参考文献页就是这样），后面跟标点或编号。
REFERENCE_HEADING_PATTERN = re.compile(
    r"(?:^|(?<=[\n。！？；.!?;]))[ \t]*(?:\d{1,4}[.)]?[ \t]+)?"
    r"(references|bibliography|works[ \t]+cited|literature[ \t]+cited|参考文献|引用文献)"
    r"(?:[:：\-—.、]|\s+\d{1,4})?",
    re.IGNORECASE,
)

#: 引文式句子的判据。与 ``scripts/评测/证据独立性.py`` 的 ``looks_like_reference``
#: 同源（年份开头、``姓, 名首字母.``、``[32] 作者,``、``arXiv preprint``、``et al.``、
#: ``[12] 大写字母``），另外补上 ``(20xx)``、``doi``、``https://``、``pp.``、``vol.``
#: 这几条。那一份只用来给报告分类，这一份参与判定，所以写成同一套。
CITATION_STYLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[（(](?:19|20)\d{2}[a-z]?[）)]"),
    re.compile(r"\bet\s+al\b\.?", re.IGNORECASE),
    re.compile(r"\bdoi\b\s*[:：]?\s*10\.", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\bpp?\.\s*\d"),
    re.compile(r"\bvol\.\s*\d", re.IGNORECASE),
    re.compile(r"\barxiv\s+preprint\b", re.IGNORECASE),
    re.compile(r"\[\d{1,3}(?:\s*[,–\-]\s*\d{1,3})*\]"),
    re.compile(r"^\s*[（(]?(?:19|20)\d{2}[a-z]?[.)）]?\s"),
    re.compile(r"^\s*[A-Z][A-Za-z\-']+(?:\s+[A-Z][A-Za-z\-']+){0,3},\s+[A-Z]"),
    re.compile(r"^\s*\[?\d{1,3}\]?\s*[A-Z][A-Za-z\-']+,\s"),
    re.compile(r"\bIn\s+(?:Proceedings|Proc\.)\b"),
    re.compile(r"\b(?:Journal|Conference|Workshop|Symposium)\s+of\b"),
)

#: 信号 B 的阈值：这一段里引文式句子的占比达到多少就整段算引文区。
#:
#: **怎么定的**：拿信号 A 当参照物，在定稿语料（791 条题录 / 510 篇本地全文，
#: 快照 ``.tmp/清单快照_第三轮``）上量的。信号 A 在某一页认出参考文献标题之后，
#: 这一篇后面几页必然是参考文献续表（信号 B 该命中），标题之前各页必然是正文
#: （信号 B 不该命中）。0.30–0.80 各档实测（正文页 4222 页、续表页 1521 页）：
#:
#: | 阈值 | 正文页误伤 | 排掉的跨度 | 其中不像引文 | 抓到的引文式 |
#: |---|---|---|---|---|
#: | 0.50 | 306/4222（7.2%） | 4467 | 899 | 3568 |
#: | 0.60 | 157/4222（3.7%） | 3129 | 458 | 2671 |
#: | 0.70 | 70/4222（1.7%） | 2283 | 327 | 1956 |
#:
#: 0.50 → 0.60 这一档：多抓 897 条引文式跨度，代价是多排 441 条不像引文的；
#: 0.60 → 0.70 这一档：少抓 715 条引文式跨度，只省下 131 条不像引文的。
#: 两条线的斜率在 0.60 换手，所以定在 0.60。"不像引文"这一列还是上界——抽样看了
#: 30 条，其中多数其实是被 PDF 折行切断的参考文献条目（只剩刊名加作者那一截），
#: 不是真正文；人工分类结果写在 ``docs/研发记录/参考文献段排除_2026-10-17.md``。
REFERENCE_CITATION_SHARE = 0.60

#: 信号 B 至少要有这么多句才判。一两句话的短段（PDF 首页页眉、图注段）占比再高
#: 也不足以说明它是参考文献表。
REFERENCE_MIN_SENTENCES = 5

#: 信号 B（版式/统计）只在论文**后 1/3 的页面**里生效；靠前的页面只认信号 A（标题）。
#:
#: **为什么有这一条**（2026-10-17 第二轮，用户判定）：参考文献按定义排在论文末尾，
#: 用位置把"摘要页的版权页眉 + 图注 + 折行引用碎片把占比抬过线"这类误伤挡掉，
#: 同时不动切法（整段判定照旧）。实测的典型是 `scientific-ie-kg` /
#: `2024.naacl-long.131` 的 `page-001`（摘要加引言首页，占比 0.607，刚过 0.60）。
#:
#: **边界口径**：设全篇页数为 N，起始页码 = ``ceil(N × 2/3)``；页码 ≥ 起始页码的
#: 页面才算后 1/3。页码或全篇页数判不出来时（不是 ``page-0NN`` 的段落、或者不知道
#: 全篇多少页）信号 B 不生效——位置判不出来就不用这条风险更大的判据。
REFERENCE_LAYOUT_TAIL_FRACTION = 2 / 3

#: 哪些解析器产出的文档**整篇不做参考文献判定**（信号 A 与信号 B 都不认）。
#: JATS XML（Europe PMC / PMC）那一路的参考文献在 ``<back>`` 里，解析器本来就没收，
#: 信号 A 在那里没有正事可干、信号 B 只会误伤正文页（实测 `single-cell-transcriptomics`
#: / `PMC2954317` 的 `page-001` 整页 Introduction 被占比判据拿掉）。
#: 按前缀匹配，带版本号的解析器标识（``jats-xml-v1``）也认。
REFERENCE_JUDGEMENT_SKIPPED_PARSERS: tuple[str, ...] = ("jats-xml",)

#: 页级段落的写法。PDF 路是真实页码，JATS 路是"一个顶层 <sec> 算一页"的虚拟页码，
#: 两条路都用 ``page-001``、``page-002``……这种编号（见两个解析器的 docstring）。
_PAGE_SECTION_PATTERN = re.compile(r"^page-(\d+)$")


def looks_like_citation_style(text: str) -> bool:
    """这句话是不是引文式写法（参考文献条目或正文里的引用标记）。

    只回答"像不像"，不区分"参考文献条目"还是"正文里的 (Smith et al., 2021)"——
    信号 B 数的是后者也占的占比，这个口径的代价写在任务记录里。
    """
    body = (text or "").strip()
    if not body:
        return False
    return any(pattern.search(body) for pattern in CITATION_STYLE_PATTERNS)


@dataclass(frozen=True, slots=True)
class ReferenceRegion:
    """一段文本里的引文区区间。"""

    char_start: int
    char_end: int
    #: ``title`` / ``layout`` / ``title+layout``
    signal: str
    heading: str = ""
    sentence_count: int = 0
    citation_sentence_count: int = 0
    citation_share: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_start": self.char_start,
            "char_end": self.char_end,
            "signal": self.signal,
            "heading": self.heading,
            "sentence_count": self.sentence_count,
            "citation_sentence_count": self.citation_sentence_count,
            "citation_share": round(self.citation_share, 4),
        }


def citation_style_sentence_share(text: str) -> tuple[int, int, float]:
    """返回 (引文式句子数, 句子总数, 占比)。空文本返回 (0, 0, 0.0)。

    句子怎么切与抽取时完全一致（``SchemaGuidedExtractor._sentence_spans``），
    否则"占了几成"和"排掉几句"会对不上。
    """
    sentences = [sentence for _, _, sentence in SchemaGuidedExtractor._sentence_spans(text)]
    if not sentences:
        return 0, 0, 0.0
    flagged = sum(1 for sentence in sentences if looks_like_citation_style(sentence))
    return flagged, len(sentences), flagged / len(sentences)


def reference_page_number(section_id: str) -> int | None:
    """``page-0NN`` 段落的页码；不是页级段落（``title`` / ``body`` / 小节名）返回 None。"""
    match = _PAGE_SECTION_PATTERN.match(str(section_id or "").strip())
    return int(match.group(1)) if match else None


def reference_page_total(section_ids: Iterable[str]) -> int:
    """全篇页数：这些段落里最大的 ``page-0NN`` 页码；没有页级段落时返回 0。

    取最大页码而不是段落条数：解析器会跳过抽不出文字的页，页码本身才对应版面页号
    （见 ``PyPDFParser`` 的 ``page-NNN`` 口径）。末尾是空页时这个数会偏小，
    那一头只会让位置约束更宽松，不会更严。
    """
    numbers = [
        number
        for number in (reference_page_number(item) for item in section_ids)
        if number
    ]
    return max(numbers) if numbers else 0


def reference_layout_page_floor(page_total: int) -> int:
    """后 1/3 的起始页码：``ceil(总页数 × 2/3)``；总页数 ≤ 0 时返回 1。

    整数算法，不走浮点：``ceil(total * 2 / 3)`` 与 ``-(-total * 2 // 3)`` 相等。
    """
    total = int(page_total)
    if total <= 0:
        return 1
    return max(1, -(-total * 2 // 3))


def layout_signal_applies(page_number: int | None, page_total: int | None) -> bool:
    """信号 B 在这一段上生不生效：只认论文后 1/3 的页面。

    页码或全篇页数不明时返回 ``False``——位置判不出来就不用这条风险更大的判据，
    靠前的页面只认信号 A。区间起点与阈值都不动，动的只是"这段算不算数"。
    """
    if page_number is None or page_total is None or int(page_total) <= 0:
        return False
    return int(page_number) >= reference_layout_page_floor(page_total)


def reference_judgement_skipped_family(parser: str) -> str:
    """跳过判定时报告里用的解析器族名（``jats-xml``）；不跳过返回空串。

    判据是前缀匹配：解析器标识带版本号（``jats-xml-v1``）也认，
    报告里按族名归类，不会因为版本号变了就多出一个键。
    """
    name = str(parser or "").strip().casefold()
    for family in REFERENCE_JUDGEMENT_SKIPPED_PARSERS:
        if name.startswith(family):
            return family
    return ""


def parser_skips_reference_judgement(parser: str) -> bool:
    """这个解析器产出的文档要不要整篇跳过参考文献判定。

    跳过的理由见 ``REFERENCE_JUDGEMENT_SKIPPED_PARSERS``：XML 路的参考文献根本
    不在解析器收进来的正文里，判定只会误伤。
    """
    return bool(reference_judgement_skipped_family(parser))


def _reference_heading_match(text: str) -> re.Match[str] | None:
    """找第一个像参考文献标题的位置；找不到返回 None。"""
    for match in REFERENCE_HEADING_PATTERN.finditer(text):
        if match.end() < len(text) and text[match.end()].isalnum():
            # 粘在词里（``ReferencesAhmed``），不是标题。
            continue
        following = text[match.end():].lstrip(" \t\n")
        if following and (
            following[0].islower() or following[0] in ")]}）】,;:\"'”’、"
        ):
            # 后面紧跟着小写字母或右括号：这是正文里的用法
            # （``References to prior work`` / ``(e.g. references)``），不是标题。
            continue
        return match
    return None


def reference_region(
    text: str,
    *,
    page_number: int | None = None,
    page_total: int | None = None,
) -> ReferenceRegion | None:
    """输入一段文本，返回其中的引文区区间；判不出来返回 None。

    两个信号（判据与阈值理由见上面各常量的注释）：

    * **信号 A（标题）**：文本里出现参考文献类标题，标题**之后**的内容算引文区，
      标题**之前**的内容照旧算正文。PDF 路把一页当一段，参考文献标题常常落在
      页面中部（这一页上半截还是正文），所以区间起点取标题位置而不是 0。
      这一条**不分位置**，靠前的页面也认——它只看有没有标题，误判面很小。
    * **信号 B（占比）**：整段的引文式句子占比 ≥ ``REFERENCE_CITATION_SHARE``、
      句子数 ≥ ``REFERENCE_MIN_SENTENCES``，**并且**这一段落在论文后 1/3 的页面里
      （``page_number`` / ``page_total`` 按 ``page-0NN`` 的序号算，边界见
      ``REFERENCE_LAYOUT_TAIL_FRACTION``）时，整段算引文区。它是给"标题没解析出来"
      和"参考文献续表页"兜底的。

    ``page_number`` / ``page_total`` 只影响信号 B：不传（或传 0）时信号 B 不生效，
    靠前的页面与不知道页码的段落只按信号 A 判。调抽取器的那条路会自己把
    ``page-0NN`` 的页码与全篇页数传进来（见 ``SchemaGuidedExtractor.extract_documents``）。

    两个信号都命中时区间仍以信号 A 为准（保住标题之前的正文），``signal`` 记成
    ``title+layout``，好让报告能分开数两个信号各排掉了多少。
    """
    if not text or not text.strip():
        return None
    flagged, total, share = citation_style_sentence_share(text)
    layout_hit = (
        total >= REFERENCE_MIN_SENTENCES
        and share >= REFERENCE_CITATION_SHARE
        and layout_signal_applies(page_number, page_total)
    )
    heading = _reference_heading_match(text)
    if heading is not None:
        return ReferenceRegion(
            char_start=heading.start(1),
            char_end=len(text),
            signal="title+layout" if layout_hit else "title",
            heading=heading.group(1),
            sentence_count=total,
            citation_sentence_count=flagged,
            citation_share=share,
        )
    if layout_hit:
        return ReferenceRegion(
            char_start=0,
            char_end=len(text),
            signal="layout",
            heading="",
            sentence_count=total,
            citation_sentence_count=flagged,
            citation_share=share,
        )
    return None
