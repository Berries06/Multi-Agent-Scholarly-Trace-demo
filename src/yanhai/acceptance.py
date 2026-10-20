"""接收一条关系的可验证条件（用来替代 ``confidence`` 折算出来的状态位）。

为什么要有这个模块（2026-10-17 定的）：题目集上系统判 ``accepted`` 的关系里，
60.0% 不被它自己引用的那段原文支持，而判 ``needs_review`` 的只有 35.1%——
状态位不但分不开好坏，方向还是反的。根因是我们把几个规则加分相加当"置信度"，
再拿两个写死的门槛折算成状态。这条路已经证明走不通（``confidence`` 只有 3 到 7
个取值，阈值怎么提都压不到目标错误率）。

这里换一套判法：**不看分数相加，看四条能不能分别验证的条件**。

==========  ==========================================================
条件        怎么判
==========  ==========================================================
证据有效    这一段是不是一段可读的完整陈述（不是参考文献条目、目录、
            表格数值碎片、断在半句）
实体定位    头、尾实体（含别名）都能在这一段里定位到，且各自位置明确
类型与方向  头尾实体类型落在本体 ``relation_constraints`` 允许的范围里；
            被动语态之类反向线索不指向反方向
谓词在场    两个实体之间存在关系触发词（本体触发词 + 报数扩展词），
            或明确的连接词（用 / 基于 / for / by / using / based on）
==========  ==========================================================

四条全过 → ``accepted``；证据无效 → ``rejected``；其余 → ``needs_review``。
这一档 ``needs_review`` 的含义也跟着改了：它不是"等人看"，而是"机制判断
证据还不够"，这正好对上指南里 ``INSUFFICIENT`` 的说法。

**这个模块只判"这一段够不够"，不判"这个结论对不对"**——与人工打分指南
的口径一致。它也不替人做判断：给出的每一条原因都要能指回片段里的位置。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "data" / "knowledge" / "extraction_schema.json"

# 判定值。与库里的 relations.status 用同一套词。
ACCEPTED = "accepted"
NEEDS_REVIEW = "needs_review"
REJECTED = "rejected"

#: 报数类触发词（与 ``extraction.REPORTS_TRIGGER_EXTRA`` 同源，这里只留词干）。
REPORT_TRIGGER_STEMS: tuple[str, ...] = (
    "report", "achiev", "obtain", "reach", "gain", "attain", "outperform",
    "报告", "达到", "取得", "提升到", "降至", "测得",
)

#: 通用连接词：没有本体触发词时，两个实体之间出现这些词也算"关系在场"。
LINK_PATTERN = re.compile(
    r"(?:\b(?:by|for|using|use|used|uses|via|with|on|from|based\s+on|trained\s+on|"
    r"applied\s+to|combined\s+with|compared\s+with|than|over)\b|"
    r"使用|采用|基于|用于|针对|结合|相比|优于)",
    re.IGNORECASE,
)

#: 版式痕迹：参考文献编号、图表标题、小节标题。
LAYOUT_MARK_PATTERN = re.compile(
    r"(?:\breferences?\b|\bbibliograph|\bworks\s+cited\b|参考文献|引用文献|"
    r"\btable\s+\d|\bfigure\s+\d|\bfig\.\s*\d|\bsection\s+\d|\bappendix\b)",
    re.IGNORECASE,
)

#: 引用标记：``[12]``、``(Smith et al., 2020)``、``et al.``。
CITATION_PATTERN = re.compile(
    r"(?:\[\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\]"
    r"|\([A-Z][^()]{0,60}\b(?:19|20)\d{2}[a-z]?\)"
    r"|\((?:19|20)\d{2}[a-z]?\)"
    r"|\bet\s+al\.)",
    re.IGNORECASE,
)

#: 结尾这些词说明句子没说完（PDF 截断或换行被切断）。
TRUNCATED_TAILS: tuple[str, ...] = (
    "using", "such as", "in", "the", "of", "and", "or", "for", "to", "with", "by",
    "is", "are", "was", "were", "a", "an", "as", "that", "which", "from",
    "用", "和", "与", "在", "把", "被",
)

#: 反向线索：出现 "is/are/was/were ... by <尾实体>" 这类被动结构时提醒一下。
PASSIVE_PATTERN = re.compile(r"\b(?:is|are|was|were|be|been|being)\b[^.;]{0,80}?\bby\b",
                             re.IGNORECASE)

MIN_SPAN_CHARS = 20
MAX_SYMBOL_RATIO = 0.45
#: 引用标记占比的阈值。**怎么定的**：在打分包 180 条真实片段上量过分布，
#: 中位数 0.0、p90 9.1%、p95 16.7%、p99 31.9%——0.30 只把最靠尾的那 1% 抓出来，
#: 正文句子里一两个引用标记远达不到这个比例，所以不会误伤正常段落。
MAX_CITATION_SHARE = 0.30

#: 句子边界：句号/问号/感叹号后跟空白与大写或括号。``et al.``、``Fig. 3`` 这类
#: 常见的缩写点会在切分后被并回去（见 ``sentence_bounds``）。
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[]|[\u4e00-\u9fff])")
ABBREVIATION_TAIL = re.compile(r"(?:\bet\s+al|\bFig|\bEq|\bTab|\bSec|\bNo|\bi\.e|\be\.g|"
                               r"\bvs|\bcf|\bref|\bAl)\.$", re.IGNORECASE)

#: 两种判法。``strict`` 要求两个实体之间出现**关系专属**触发词且同句；
#: ``loose`` 允许通用连接词（用/基于/for/by/using…）也算关系在场。
MODE_STRICT = "strict"
MODE_LOOSE = "loose"
MODES = (MODE_STRICT, MODE_LOOSE)


class SchemaError(RuntimeError):
    """本体文件读不出来或不完整。"""


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """读本体：关系类型 -> 头尾实体类型允许范围、各关系的触发词。"""
    target = Path(path) if path is not None else SCHEMA_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as error:  # pragma: no cover - 仓库里一定有这个文件
        raise SchemaError(f"找不到本体文件：{target}") from error
    constraints = data.get("relation_constraints")
    if not isinstance(constraints, Mapping):
        raise SchemaError("本体里缺 relation_constraints")
    triggers: dict[str, tuple[tuple[str, ...], ...]] = {}
    for item in data.get("relation_patterns") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("relation_type") or "").strip()
        words = tuple(str(word) for word in (item.get("triggers") or ()) if str(word).strip())
        if name and words:
            triggers[name] = (words,)
    return {
        "relation_constraints": {str(k): v for k, v in constraints.items()},
        "triggers": {name: tuple(pack[0]) for name, pack in triggers.items()},
    }


def normalize(text: str) -> str:
    """把合字、全角、连续空白拉平，便于定位。**不改变字符数以外的长度关系**：
    只做一对一的兼容分解与空白压缩，切片位置仍在归一化后的文本上算，
    因此调用方要用返回的文本去取位置。"""
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized)


def name_pattern(name: str) -> re.Pattern[str] | None:
    """按名字造定位用的正则：ASCII 词边界，中文不边界。"""
    cleaned = normalize(name).strip()
    if not cleaned:
        return None
    escaped = re.escape(cleaned)
    head, tail = cleaned[0], cleaned[-1]
    left = r"(?<![A-Za-z0-9])" if head.isascii() and head.isalnum() else ""
    right = r"(?![A-Za-z0-9])" if tail.isascii() and tail.isalnum() else ""
    return re.compile(left + escaped + right, re.IGNORECASE)


def locate(text: str, names: Iterable[str]) -> list[tuple[int, int, str]]:
    """在文本里找出这些名字的全部出现位置，按起点排序，去重叠。"""
    hits: list[tuple[int, int, str]] = []
    for name in names:
        pattern = name_pattern(name)
        if pattern is None:
            continue
        for match in pattern.finditer(text):
            hits.append((match.start(), match.end(), name))
    hits.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str]] = []
    for hit in hits:
        if kept and hit[0] < kept[-1][1]:
            continue
        kept.append(hit)
    return kept


def _symbol_ratio(text: str) -> float:
    if not text:
        return 1.0
    symbols = sum(1 for char in text if not (char.isalpha() or char.isspace()))
    return symbols / len(text)


def _citation_share(text: str) -> float:
    """引用标记覆盖的字符占全文比例。参考文献页会很高。"""
    if not text:
        return 0.0
    covered = sum(match.end() - match.start() for match in CITATION_PATTERN.finditer(text))
    return covered / len(text)


def evidence_quality(span: str) -> dict[str, Any]:
    """这一段是不是可用的证据。返回判据明细，调用方据此给理由。"""
    text = normalize(span or "")
    reasons: list[str] = []
    if len(text) < MIN_SPAN_CHARS:
        reasons.append("太短，不足以构成陈述")
    tail = text.rstrip(" .;:,、，。").split(" ")[-1].lower() if text else ""
    if tail and any(tail == word.lower() or text.lower().rstrip().endswith(word)
                    for word in TRUNCATED_TAILS):
        reasons.append("结尾停在连接词上，句子没说完")
    symbol_ratio = _symbol_ratio(text)
    if symbol_ratio > MAX_SYMBOL_RATIO:
        reasons.append(f"符号占比 {symbol_ratio:.0%}，像表格或图注碎片")
    citation_share = _citation_share(text)
    if citation_share > MAX_CITATION_SHARE:
        reasons.append(f"引用标记占 {citation_share:.0%}，像参考文献页")
    layout = LAYOUT_MARK_PATTERN.search(text)
    if layout:
        reasons.append(f"含版式标记「{layout.group(0)}」")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "symbol_ratio": round(symbol_ratio, 3),
        "citation_share": round(citation_share, 3),
    }


def type_ok(constraints: Mapping[str, Any], relation_type: str,
            head_type: str, tail_type: str) -> tuple[bool, str]:
    """头尾实体类型是否落在本体允许的范围里。"""
    rule = constraints.get(relation_type)
    if not isinstance(rule, Mapping):
        return True, "本体没有这条关系的类型约束（按不限制处理）"
    allowed_head = [str(item).upper() for item in (rule.get("source") or ())]
    allowed_tail = [str(item).upper() for item in (rule.get("target") or ())]
    head_up, tail_up = str(head_type).upper(), str(tail_type).upper()
    problems: list[str] = []
    if allowed_head and head_up not in allowed_head:
        problems.append(f"头实体类型 {head_up} 不在 {allowed_head}")
    if allowed_tail and tail_up not in allowed_tail:
        problems.append(f"尾实体类型 {tail_up} 不在 {allowed_tail}")
    if problems:
        return False, "；".join(problems)
    return True, "类型在允许范围内"


def sentence_bounds(text: str) -> list[tuple[int, int]]:
    """切句，返回每句的 [起, 止)。缩写点（``et al.`` 之类）不算句末。"""
    cuts: list[int] = []
    cursor = 0
    for match in SENTENCE_BREAK.finditer(text):
        head = text[cursor:match.start()]
        if ABBREVIATION_TAIL.search(head):
            continue
        cuts.append(match.end())
        cursor = match.end()
    bounds: list[tuple[int, int]] = []
    start = 0
    for cut in cuts:
        bounds.append((start, cut))
        start = cut
    bounds.append((start, len(text)))
    return bounds


def same_sentence(text: str, first: tuple[int, int, str], second: tuple[int, int, str]) -> bool:
    """两个位置是否落在同一句里。切句失败时按"不同句"处理（保守做法）。"""
    left, right = sorted((first[0], second[0]))
    for start, end in sentence_bounds(text):
        if start <= left and right < end:
            return True
    return False


def trigger_between(text: str, head_hit: tuple[int, int, str],
                    tail_hit: tuple[int, int, str],
                    triggers: Sequence[str], *,
                    allow_link: bool = True) -> tuple[bool, str]:
    """两个实体之间有没有触发词（或连接词）。只看两者之间那一段。

    ``allow_link=False``（严格判法）时通用连接词不算数：只认关系专属触发词
    与报数类动词。原因是"用/基于/for/by"这类词在两段并列句里到处都是，
    把它们当关系在场等于没判。
    """
    start = min(head_hit[1], tail_hit[1])
    end = max(head_hit[0], tail_hit[0])
    if end <= start:
        return False, "两个实体紧挨着，中间没有内容"
    between = text[start:end]
    lowered = between.lower()
    for word in triggers:
        needle = str(word).lower()
        if not needle:
            continue
        if needle.isascii():
            if re.search(r"(?<![a-z0-9])" + re.escape(needle), lowered):
                return True, f"中间有触发词「{word}」"
        elif needle in between:
            return True, f"中间有触发词「{word}」"
    for word in REPORT_TRIGGER_STEMS:
        if str(word).lower() in lowered:
            return True, f"中间有报数类动词「{word}」"
    if allow_link:
        link = LINK_PATTERN.search(between)
        if link:
            return True, f"中间只有通用连接词「{link.group(0)}」"
    return False, "两个实体之间没有关系触发词" if not allow_link else "两个实体之间既没有触发词也没有连接词"


def direction_hint(text: str, head_hit: tuple[int, int, str],
                   tail_hit: tuple[int, int, str]) -> str | None:
    """粗看一下被动语态：如果有 ``is/are ... by`` 且 by 在尾实体之前，给个提醒。

    这里只提醒，不改判定——真正的方向要靠人工或模型验证。"""
    if head_hit[0] > tail_hit[0]:
        return "头实体出现在尾实体之后（语序反了）"
    between_start = head_hit[1]
    between_end = tail_hit[0]
    chunk = text[between_start:between_end]
    if PASSIVE_PATTERN.search(chunk):
        return "中间出现被动结构（is/are ... by），方向可能被写反"
    return None


@dataclass(frozen=True)
class Decision:
    """一条关系的接收结论。``checks`` 里逐条留痕，方便复核与统计。"""

    status: str
    checks: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED


def decide(
    *,
    span: str,
    head_name: str,
    head_type: str,
    tail_name: str,
    tail_type: str,
    relation_type: str,
    head_aliases: Sequence[str] = (),
    tail_aliases: Sequence[str] = (),
    schema: Mapping[str, Any] | None = None,
    mode: str = MODE_STRICT,
    require_same_sentence: bool = True,
) -> Decision:
    """按四条条件给一条关系定状态。缺参数不许猜，直接进 ``needs_review``。"""
    if mode not in MODES:
        raise ValueError(f"mode 只能是 {MODES}，收到 {mode!r}")
    relations = schema or load_schema()
    constraints = relations["relation_constraints"]
    triggers = tuple(relations["triggers"].get(str(relation_type).upper(), ()))

    text = normalize(span or "")
    quality = evidence_quality(text)
    head_hits = locate(text, [head_name, *head_aliases])
    tail_hits = locate(text, [tail_name, *tail_aliases])
    checks: dict[str, Any] = {
        "evidence": quality,
        "head_hits": len(head_hits),
        "tail_hits": len(tail_hits),
        "mode": mode,
    }
    reasons: list[str] = []

    # 条件 1：证据有效。无效直接拒，不再往下判——这是指南里"证据不可用"那一档。
    if not quality["ok"]:
        checks["type"] = {"ok": None, "reason": "证据无效，未判类型"}
        checks["trigger"] = {"ok": None, "reason": "证据无效，未判谓词"}
        return Decision(REJECTED, checks, tuple(quality["reasons"]))

    # 条件 2：实体定位。一个都找不到 -> 拒；找得到但位置有歧义 -> 等人看。
    if not head_hits or not tail_hits:
        missing = []
        if not head_hits:
            missing.append(f"头实体「{head_name}」")
        if not tail_hits:
            missing.append(f"尾实体「{tail_name}」")
        checks["type"] = {"ok": None, "reason": "实体缺失，未判类型"}
        checks["trigger"] = {"ok": None, "reason": "实体缺失，未判谓词"}
        return Decision(REJECTED, checks, (f"这一段里没有出现{'、'.join(missing)}",))
    if len(head_hits) > 1 or len(tail_hits) > 1:
        reasons.append(
            f"实体定位不唯一（头 {len(head_hits)} 处、尾 {len(tail_hits)} 处）"
        )

    # 条件 3：类型与方向。
    ok_type, type_reason = type_ok(constraints, str(relation_type).upper(), head_type, tail_type)
    checks["type"] = {"ok": ok_type, "reason": type_reason}
    if not ok_type:
        reasons.append(type_reason)

    head_hit = head_hits[0]
    tail_hit = tail_hits[0]
    hint = direction_hint(text, head_hit, tail_hit)
    checks["direction"] = {"ok": hint is None, "reason": hint or "未发现反向线索"}
    if hint:
        reasons.append(hint)

    same = same_sentence(text, head_hit, tail_hit)
    checks["sentence"] = {"ok": same, "reason": "同句" if same else "两个实体不在同一句"}
    if require_same_sentence and not same:
        reasons.append("两个实体不在同一句（跨句关系要另判）")

    # 条件 4：谓词在场。
    ok_trigger, trigger_reason = trigger_between(
        text, head_hit, tail_hit, triggers, allow_link=(mode == MODE_LOOSE)
    )
    checks["trigger"] = {"ok": ok_trigger, "reason": trigger_reason}
    if not ok_trigger:
        reasons.append(trigger_reason)

    all_ok = (
        ok_type
        and ok_trigger
        and hint is None
        and not (len(head_hits) > 1 or len(tail_hits) > 1)
        and (same or not require_same_sentence)
    )
    if all_ok:
        return Decision(ACCEPTED, checks, ())
    return Decision(NEEDS_REVIEW, checks, tuple(reasons))


def decide_for_spans(
    *,
    spans: Sequence[str],
    head_name: str,
    head_type: str,
    tail_name: str,
    tail_type: str,
    relation_type: str,
    head_aliases: Sequence[str] = (),
    tail_aliases: Sequence[str] = (),
    schema: Mapping[str, Any] | None = None,
    mode: str = MODE_STRICT,
    require_same_sentence: bool = True,
) -> Decision:
    """一条关系挂多段证据时：**任何一段能满足条件就接收**（与指标口径一致）。

    全部不满足时，取"最不坏"的那一段的结论——有 ``needs_review`` 就报
    ``needs_review``，全是证据无效才报 ``rejected``。
    """
    relations = schema or load_schema()
    decisions = [
        decide(
            span=span,
            head_name=head_name,
            head_type=head_type,
            tail_name=tail_name,
            tail_type=tail_type,
            relation_type=relation_type,
            head_aliases=head_aliases,
            tail_aliases=tail_aliases,
            schema=relations,
            mode=mode,
            require_same_sentence=require_same_sentence,
        )
        for span in spans
    ]
    if not decisions:
        return Decision(NEEDS_REVIEW, {"evidence": {"ok": None, "reasons": ["没有挂证据"]}},
                        ("这条关系没有挂任何证据",))
    for decision in decisions:
        if decision.accepted:
            return decision
    for decision in decisions:
        if decision.status == NEEDS_REVIEW:
            return decision
    return decisions[0]
