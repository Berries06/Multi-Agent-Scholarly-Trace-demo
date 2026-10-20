from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .agents import CriticAgent, JudgeAgent
from .knowledge import KnowledgeBase
from .models import Claim
from .semantic_check import check_semantic_strength


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


# 「单智能体一次跑完」对照用的两个常量。
#
# 判定规则刻意分成两层，好让这个对照只和 `_evidence_triad` 差一件事：
#   1. `_BLOCKING_CRITICISM_MARKERS` 照抄裁判在 `JudgeAgent.adjudicate`
#      （`src/yanhai/agents.py:448-458`）里当成阻断项的那几类批判。也就是说
#      “哪条检查算严重、哪条只算限制”这件事两组完全一致，不是新变体自己放水。
#   2. 接收门槛沿用裁判的 0.78。
# 去掉的只有裁判角色的加减分（证据奖励 / 交叉来源奖励 / A 级证据奖励 / 风险惩罚）
# 和“批判者—裁判”这道分工：新变体由同一个智能体在同一遍里做完检查就下判定。
_BLOCKING_CRITICISM_MARKERS = (
    "缺少可追溯证据",
    "不存在",
    "绝对化",
    "不匹配",
    "没有同时覆盖",
)
_SINGLE_AGENT_ACCEPT_THRESHOLD = 0.78


# ---------------------------------------------------------------------------
# 候选置信度的机制化计算
#
# 旧基准 `data/evaluation/decision_benchmark.json` 的每条案例自带一个
# `base_confidence`，那是人写进去的常量（看板「Track A 基准的候选置信度是人工常量」
# 记的就是这件事）。下面这套计算让 `base_confidence` 改由机制产生：输入只有
# 这条案例自己带的证据跨度、断言的实体对与关系类型、以及项目现成的 schema，
# **不看 gold_supported**，也不是拟合成绩调出来的。
#
# 用到的现成判定：
#   ① 证据跨度是否存在 —— `KnowledgeBase.evidence_is_valid`（`knowledge.py:367`）；
#   ② 跨度有没有同时覆盖关系两端 —— 和批判者第三条检查同一件事
#      （`agents.py:367-377`，底层是 `KnowledgeBase.entity_mentioned_in_evidence`，
#      `knowledge.py:415`）；
#   ③ 关系谓词模式有没有命中 —— 和 `SchemaGuidedExtractor._relation_type_for_sentence`
#      同一套 `relation_patterns`（`extraction.py:408-413`，schema 在
#      `data/knowledge/extraction_schema.json:1787-1901`）；
#   ④ 实体类型符不符合 schema —— 和 `SchemaGuidedExtractor._criticize` 里的
#      `schema_type_mismatch` 同一套 `relation_constraints`（`extraction.py:634-642`，
#      schema 在 `extraction_schema.json:1694-1786`），也等价于
#      `KnowledgeBase.relation_types_are_valid`（`knowledge.py:450-462`）；
#   ⑤ 表述强度 —— `semantic_check.check_semantic_strength`（`semantic_check.py:48`），
#      承接批判者「绝对化 / 未完成体」两条。
#
# 算式（`_mechanism_base_confidence`）：
#     基准 0.80
#     - 跨度没有同时覆盖两端        -0.08
#     - 命中模式的关系类型 ≠ 断言类型 -0.10
#     - 实体类型约束不满足          -0.08
#     - 表述被标为危险/警示/hedged  -0.04   （只扣一次）
#   → 落在 [0.60, 0.99]，四舍五入到 3 位。
# 参照点：四项全过 = 0.80；扣一项 = 0.62…0.72；四类各扣一次 = 0.60。
#         0.7 是批判者的低置信线（`agents.py:378`），
#         0.78 是裁判与单智能体变体的接收线（`agents.py:459`、本文件 `_SINGLE_AGENT_ACCEPT_THRESHOLD`）。
# 也就是说：这套机制在干净情形下给到 0.80（刚好过 0.78 线），
# 只要有一项不过就落到 0.70 以下——这是刻意的，四类判定各自都能单独否掉一条候选。
_MECHANISM_BASE = 0.80
_MECHANISM_MISSING_ENDPOINTS = 0.08
_MECHANISM_PATTERN_MISMATCH = 0.10
_MECHANISM_TYPE_MISMATCH = 0.08
_MECHANISM_WEAK_STRENGTH = 0.04
_MECHANISM_FLOOR = 0.60
_MECHANISM_CEILING = 0.99
_WORD_IN_TEXT = re.compile(r"[a-z0-9]+")


def _as_payload(value: Any) -> dict[str, Any]:
    """把 `to_dict()` 结果或 dataclass 本身统一成可读字典。"""
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {
        "canonical_name": getattr(value, "canonical_name", None),
        "text": getattr(value, "text", None),
        "char_start": getattr(value, "char_start", None),
        "char_end": getattr(value, "char_end", None),
    }


def _word_in_order(needle: str, haystack: str) -> bool:
    """按词序判断 needle 的词是否依次出现在 haystack 里。

    直接子串匹配会漏掉两种真实情况：
    ① 谓词被实体名隔开——原文 `We evaluate SCIIE on SCIERC` 里 `evaluate` 与 `on`
       之间插着 `SCIIE`，`evaluation.py` 那条"在数据集上评测"的触发词 `evaluate on`
       按子串永远匹配不上；
    ② 断词——`outper-` 这种行尾断开，`outperforms` 这样的触发词只剩前半。
    所以这里先做子串匹配，不中再按词序匹配；词序匹配对断词天然宽容（`outper`
    是 `outper-` 去掉连字符后的词形）。
    """
    needle_words = _WORD_IN_TEXT.findall(needle.casefold())
    if not needle_words:
        return False
    haystack_words = _WORD_IN_TEXT.findall(haystack.casefold())
    cursor = 0
    for word in needle_words:
        try:
            cursor = haystack_words.index(word, cursor) + 1
        except ValueError:
            return False
    return True


def _relation_pattern_for_text(
    kb: KnowledgeBase,
    text: str,
) -> tuple[str, bool]:
    """按 schema 的 `relation_patterns` 定序返回 (关系类型, 是否命中)。

    即 `extraction.py:408-413` 的同一套扫描，只是对整段证据文本做一次，
    触发词匹配放宽为"子串或按词序"（理由见 `_word_in_order`）。
    """
    for pattern in kb.schema.get("relation_patterns", []):
        if any(_word_in_order(trigger, text) for trigger in pattern["triggers"]):
            return str(pattern["relation_type"]), True
    return "RELATED_TO", False


def _evidence_registry_from_benchmark(
    benchmark: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """把评测集里的证据跨度做成一份按 evidence_id 索引的登记表。

    做这个是因为项目目前只有两套证据源：`outputs/vertical-knowledge.db` 的 47 条
    自撰释义句（`KnowledgeBase` 默认能查到的就是这一套），和
    `outputs/fulltext-knowledge.db` 里的真原文证据（`KnowledgeBase` 查不到）。
    新评测集的证据是后者的原文片段，原样落在评测文件里（照抄、带页码与偏移），
    所以这里按 case 里的 `evidence_id` / `evidence_text` 建登记表，
    让 `evidence_is_valid` / `evidence_details` / `entity_mentioned_in_evidence`
    这三条现成判定在真原文上也能跑，而不必去读那两个库。
    """
    registry: dict[str, dict[str, Any]] = {}
    for item in benchmark.get("cases", []):
        evidence_id = item.get("evidence_id")
        text = item.get("evidence_text")
        if not evidence_id or not isinstance(text, str):
            continue
        registry[str(evidence_id)] = {
            "evidence_id": str(evidence_id),
            "paper_id": str(item.get("paper_id", "")),
            "section_id": str(item.get("page", "")),
            "sentence_index": int(item.get("sentence_index", 0) or 0),
            "text": text,
            "char_start": int(item.get("char_start", 0) or 0),
            "char_end": int(item.get("char_end", 0) or 0),
        }
    return registry


def _register_case_aliases(
    kb: KnowledgeBase,
    benchmark: dict[str, Any],
) -> None:
    """把评测集为每条案例声明的实体写法与类型登记进附加层。

    只登记案例自己写明 `source_type` / `target_type` 的那些案例；旧基准没有这两个
    字段，也就不会被登记，`entity_type_for_name` 仍走 schema concepts 那条老路。

    同一个名字在多个案例里出现时，别名取并集（`SCIREX` / `S CIREX` 这种解析断词
    会分散在不同案例里）；实体类型取第一次声明的那个——同一篇论文里同一个系统名
    只能是同一类实体，一条案例把它写成另一类就是那条案例自己的问题，
    由 `_mechanism_base_confidence` 的类型约束那项算出来，不在这里悄悄抹平。
    """
    for item in benchmark.get("cases", []):
        for side in ("source", "target"):
            name = item.get(side)
            entity_type = item.get(f"{side}_type")
            if not name or not entity_type:
                continue
            key = str(name).casefold()
            aliases = {
                str(alias).casefold()
                for alias in (item.get(f"{side}_aliases") or [name])
                if str(alias).strip()
            }
            aliases.add(key)
            existing = kb.entity_alias_overlay.get(key)
            if existing is None:
                kb.entity_alias_overlay[key] = (str(entity_type), aliases)
            else:
                kb.entity_alias_overlay[key] = (
                    existing[0],
                    existing[1] | aliases,
                )


def _mechanism_base_confidence(
    claim: Claim,
    kb: KnowledgeBase,
    evidence: list[dict[str, Any]],
) -> tuple[float, dict[str, float], str]:
    """按上面第 18-60 行写的那套判定算候选置信度，并返回算式各项与一句人读的理由。"""
    strong = check_semantic_strength(evidence[0].get("text", "") if evidence else "")
    text = " ".join(str(item.get("text", "")) for item in evidence)
    mention_ids = {
        str(item.get("evidence_id", ""))
        for item in evidence
    }
    covers_both = any(
        kb.entity_mentioned_in_evidence(claim.source, evidence_id)
        and kb.entity_mentioned_in_evidence(claim.target, evidence_id)
        for evidence_id in mention_ids
        if evidence_id
    )
    pattern_type, pattern_hit = _relation_pattern_for_text(kb, text)
    pattern_matches = pattern_hit and pattern_type == claim.relation_type
    constraints = kb.schema.get("relation_constraints", {})
    if constraints.get(claim.relation_type):
        constraints_ok = kb.relation_types_are_valid(
            claim.relation_type,
            claim.source_type,
            claim.target_type,
        )
    else:
        constraints_ok = claim.relation_type in kb.schema.get("relation_types", {})
    weak_strength = strong["verdict"] in {"danger", "warning", "info"}
    score = _MECHANISM_BASE
    if not covers_both:
        score -= _MECHANISM_MISSING_ENDPOINTS
    if not pattern_matches:
        score -= _MECHANISM_PATTERN_MISMATCH
    if not constraints_ok:
        score -= _MECHANISM_TYPE_MISMATCH
    if weak_strength:
        score -= _MECHANISM_WEAK_STRENGTH
    score = round(max(_MECHANISM_FLOOR, min(_MECHANISM_CEILING, score)), 3)
    # `Claim.score_breakdown` 在 `models.py:156-158` 是按数值四舍五入的，
    # 所以这里只放数值项，模式类型与措辞判定放进人读的理由串。
    reason = (
        f"候选置信度由机制算出 {score:.2f}（基准 {_MECHANISM_BASE:.2f}；"
        f"跨度同时覆盖两端 {covers_both}；"
        f"命中关系模式 {pattern_type}"
        f"{'（与断言一致）' if pattern_matches else '（与断言不一致）'}；"
        f"实体类型合规 {constraints_ok}；"
        f"表述判定 {strong['verdict']}）。"
    )
    return (
        score,
        {
            "covers_both_endpoints": float(covers_both),
            "pattern_matches_claim": float(pattern_matches),
            "constraints_ok": float(constraints_ok),
            "weak_strength": float(weak_strength),
        },
        reason,
    )


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float]:
    """返回二项 Wilson 95% 置信区间，不假装 n 足够大。"""
    if total <= 0:
        return [0.0, 0.0]
    estimate = successes / total
    denominator = 1 + (z * z / total)
    centre = estimate + (z * z / (2 * total))
    margin = z * math.sqrt(
        (estimate * (1 - estimate) / total)
        + (z * z / (4 * total * total))
    )
    return [
        round(max(0.0, (centre - margin) / denominator), 3),
        round(min(1.0, (centre + margin) / denominator), 3),
    ]


class DecisionAblation:
    """在同一冻结候选池上做 Track-A 对比。

    这有意设计为确定性 demo 基准：用于验证对比与轨迹流水线可用，
    不替代 LLM 或专家标注的公开基准。

    `include_single_agent_control` 默认 False：默认暴露的仍是实验协议里那四个变体。
    打开它才会多出一组「单智能体一次跑完九条检查」对照——那组是给研究者拆
    “职责分开 / 检查项更多”用的，不属于 `tests/experiments/` 里定下来的协议。

    `evidence_registry` 默认 None。传进来一份 `{evidence_id: 跨度}` 时，它会挂到
    `KnowledgeBase.evidence_registry` 上，作为附加层参与 `evidence_is_valid` /
    `evidence_details` / `entity_mentioned_in_evidence`；旧基准不传，行为一字不变。
    新评测集（`data/evaluation/decision_benchmark_real_v1.json`）走这条路：它的证据是
    真原文片段，库里查不到，但片段本身就在评测文件里。
    """

    def __init__(
        self,
        project_root: Path,
        knowledge_base: KnowledgeBase,
        benchmark: dict[str, Any] | None = None,
        include_single_agent_control: bool = False,
        evidence_registry: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.project_root = project_root
        self.kb = knowledge_base
        if benchmark is not None:
            self.benchmark = benchmark
        else:
            benchmark_path = (
                project_root / "data" / "evaluation" / "decision_benchmark.json"
            )
            self.benchmark = (
                json.loads(benchmark_path.read_text(encoding="utf-8"))
                if benchmark_path.is_file()
                else {"cases": [], "missing_benchmark": str(benchmark_path)}
            )
        self.include_single_agent_control = include_single_agent_control
        if evidence_registry:
            knowledge_base.evidence_registry.update(evidence_registry)
        _register_case_aliases(knowledge_base, self.benchmark)
        self.critic = CriticAgent()
        self.judge = JudgeAgent()

    def run(self) -> dict[str, Any]:
        variants: list[tuple[str, str, Callable[[list[Claim]], list[Claim]]]] = [
            (
                "rule_program",
                "普通规则程序",
                self._rule_program,
            ),
            (
                "single_pass",
                "单次判定",
                self._single_pass,
            ),
            (
                "homogeneous_vote",
                "同质三路投票",
                self._homogeneous_vote,
            ),
            (
                "evidence_triad",
                "提出—批判—裁判",
                self._evidence_triad,
            ),
        ]
        if self.include_single_agent_control:
            variants.append(
                (
                    "single_agent_all_checks",
                    "单智能体一次跑完九条检查",
                    self._single_agent_all_checks,
                )
            )
        results = []
        for variant_id, label, runner in variants:
            claims = self._claims()
            predicted = runner(claims)
            results.append(
                {
                    "variant_id": variant_id,
                    "label": label,
                    "metrics": self._metrics(predicted),
                    "cases": [self._case_result(item) for item in predicted],
                }
            )
        triad = next(
            item for item in results if item["variant_id"] == "evidence_triad"
        )
        # `single_agent_all_checks` 是拿来拆“职责分开 / 检查项更多”的对照，它和三智能体
        # 共用同一套检查，不是朴素基线；把它算进最强基线会让这段差值恒等于 0，失去意义。
        # 所以这里仍只在三个朴素基线里挑最强的一个，和加对照之前一致。
        _not_a_naive_baseline = {"evidence_triad", "single_agent_all_checks"}
        strongest_baseline = max(
            (
                item
                for item in results
                if item["variant_id"] not in _not_a_naive_baseline
            ),
            key=lambda item: (
                item["metrics"]["accepted_precision"],
                item["metrics"]["gold_recall"],
            ),
        )
        return {
            "benchmark_id": self.benchmark["benchmark_id"],
            "domain": self.benchmark["domain"],
            "frozen_on": self.benchmark["frozen_on"],
            "scope": self.benchmark["scope"],
            "case_count": len(self.benchmark["cases"]),
            "noise_protocol": self.benchmark.get("noise_protocol", {}),
            "variants": results,
            "comparison": {
                "strongest_baseline": strongest_baseline["variant_id"],
                "accepted_precision_gain_pp": round(
                    100
                    * (
                        triad["metrics"]["accepted_precision"]
                        - strongest_baseline["metrics"]["accepted_precision"]
                    ),
                    1,
                ),
                "unsupported_acceptance_reduction_pp": round(
                    100
                    * (
                        strongest_baseline["metrics"]["unsupported_acceptance_rate"]
                        - triad["metrics"]["unsupported_acceptance_rate"]
                    ),
                    1,
                ),
                "gold_recall_change_pp": round(
                    100
                    * (
                        triad["metrics"]["gold_recall"]
                        - strongest_baseline["metrics"]["gold_recall"]
                    ),
                    1,
                ),
            },
            "warning": (
                "结果来自 24 条分层压力测试，含低置信真阳性和有效 ID 语义错配；"
                "95% 区间很宽，只能用于暴露机制与失败案例。关系证据覆盖率是"
                "“无证据不入图”的结构性护栏，不是抽取正确率。提交论文前仍须在"
                "独立双人标注金标准和真实模型输出上重跑。"
            ),
            "metric_notes": {
                "accepted_precision": "估计性指标；必须同时报告 TP/accepted 与 Wilson 95% 区间。",
                "gold_recall": "估计性指标；needs_review 与 rejected 均按未保留计算。",
                "unsupported_acceptance_rate": "估计性风险指标；越低越好。",
                "evidence_coverage": (
                    "结构性不变量：裁判禁止无有效 evidence_id 的命题进入 accepted；"
                    "100% 只表示有引用，不表示引用语义正确。"
                ),
            },
        }

    def _claims(self) -> list[Claim]:
        """把基准里的案例转成命题。

        置信度有两条来源，按案例里有没有 `evidence_text` 决定：
        - 旧基准（24 条）只有人工写的 `base_confidence`，照旧直接读，一个数不变；
        - 新基准（真原文）带 `evidence_text`，置信度按 `_mechanism_base_confidence`
          那套机制算，`base_confidence` 键即使写着也不采纳。
        """
        claims: list[Claim] = []
        for item in self.benchmark["cases"]:
            source_type = item.get("source_type") or self.kb.entity_type_for_name(
                item["source"]
            )
            target_type = item.get("target_type") or self.kb.entity_type_for_name(
                item["target"]
            )
            evidence_text = item.get("evidence_text")
            case_evidence = (
                [self.kb.evidence_registry[str(item["evidence_id"])]]
                if evidence_text is not None
                and str(item.get("evidence_id", "")) in self.kb.evidence_registry
                else []
            )
            if evidence_text is None:
                base_confidence = float(item["base_confidence"])
                confidence_breakdown: dict[str, Any] = {"source": 0.0}
                confidence_reason = "候选置信度取自基准文件里人工写的常量。"
            else:
                (
                    base_confidence,
                    confidence_breakdown,
                    confidence_reason,
                ) = _mechanism_base_confidence(
                    Claim(
                        claim_id=item["claim_id"],
                        source=item["source"],
                        relation=item["relation"],
                        target=item["target"],
                        relation_type=item["relation_type"],
                        base_confidence=0.0,
                        source_type=source_type,
                        target_type=target_type,
                        evidence_ids=list(item["evidence_ids"]),
                    ),
                    self.kb,
                    case_evidence,
                )
                confidence_breakdown = {
                    "source": 1.0,
                    **confidence_breakdown,
                }
            claims.append(
                Claim(
                    claim_id=item["claim_id"],
                    source=item["source"],
                    relation=item["relation"],
                    target=item["target"],
                    relation_type=item["relation_type"],
                    base_confidence=base_confidence,
                    source_type=source_type,
                    target_type=target_type,
                    evidence_ids=list(item["evidence_ids"]),
                    proposal_reason=(
                        "评测集里的统一输入；候选置信度由机制算出。"
                        if evidence_text is not None
                        else "冻结候选池中的统一输入。"
                    ),
                    judge_reason=confidence_reason,
                    model_route=(
                        "real-paper-evidence-candidate"
                        if evidence_text is not None
                        else "frozen-track-a-candidate"
                    ),
                    score_breakdown=confidence_breakdown,
                )
            )
        return claims

    @staticmethod
    def _rule_program(claims: list[Claim]) -> list[Claim]:
        for claim in claims:
            claim.status = (
                "accepted" if claim.base_confidence >= 0.78 else "rejected"
            )
            claim.judge_score = claim.base_confidence
            claim.judge_reason = "只按候选置信度阈值 0.78 决策。"
        return claims

    def _single_pass(self, claims: list[Claim]) -> list[Claim]:
        for claim in claims:
            evidence_ok = any(
                self.kb.evidence_is_valid(item) for item in claim.evidence_ids
            )
            claim.status = (
                "accepted"
                if evidence_ok and claim.base_confidence >= 0.72
                else "rejected"
            )
            claim.judge_score = claim.base_confidence if evidence_ok else 0.0
            claim.judge_reason = "单次策略只检查证据 ID 是否存在，不做独立反证。"
        return claims

    def _homogeneous_vote(self, claims: list[Claim]) -> list[Claim]:
        thresholds = (0.70, 0.72, 0.74)
        for claim in claims:
            evidence_ok = any(
                self.kb.evidence_is_valid(item) for item in claim.evidence_ids
            )
            votes = [
                evidence_ok and claim.base_confidence >= threshold
                for threshold in thresholds
            ]
            claim.status = "accepted" if sum(votes) >= 2 else "rejected"
            claim.judge_score = sum(votes) / len(votes)
            claim.judge_reason = (
                f"三个同质策略投票 {sum(votes)}:3；它们共享证据检查盲点。"
            )
            claim.score_breakdown = {
                **claim.score_breakdown,
                "vote_1": float(votes[0]),
                "vote_2": float(votes[1]),
                "vote_3": float(votes[2]),
            }
        return claims

    def _evidence_triad(self, claims: list[Claim]) -> list[Claim]:
        return self.judge.adjudicate(
            self.critic.critique(claims, self.kb),
            self.kb,
        )

    def _single_agent_all_checks(self, claims: list[Claim]) -> list[Claim]:
        """一个智能体一次跑完批判者那 9 条检查，并在同一遍里自己下判定。

        检查内容直接调用 `CriticAgent.critique`，所以和 `_evidence_triad` 的第一段
        （提出者—批判者）逐条相同：9 条 claim 级检查，外加按来源做的引用核验与
        设计层级两条（`agents.py:380-390`）。与三智能体的差别只剩两点：
        ① 不再有独立的裁判角色，判定和检查在同一个智能体、同一遍里出；
        ② 没有裁判那套加减分，判定直接落在“有无阻断性批判 + 候选置信度阈值”上。
        """
        for claim in self.critic.critique(claims, self.kb):
            evidence_ok = any(
                self.kb.evidence_is_valid(item) for item in claim.evidence_ids
            )
            blocking_hits = [
                criticism
                for criticism in claim.criticisms
                if any(
                    marker in criticism
                    for marker in _BLOCKING_CRITICISM_MARKERS
                )
            ]
            claim.status = (
                "accepted"
                if evidence_ok
                and not blocking_hits
                and claim.base_confidence >= _SINGLE_AGENT_ACCEPT_THRESHOLD
                else "rejected"
            )
            claim.judge_score = claim.base_confidence if evidence_ok else 0.0
            claim.judge_reason = (
                "单智能体一次跑完各条检查后自行判定："
                f"阻断性检查 {len(blocking_hits)} 条，"
                f"候选置信度 {claim.base_confidence:.2f}，输出 {claim.status}。"
            )
            claim.score_breakdown = {
                **claim.score_breakdown,
                "base_confidence": claim.base_confidence,
                "criticism_count": float(len(claim.criticisms)),
                "blocking_criticism_count": float(len(blocking_hits)),
            }
        return claims

    def _metrics(self, claims: list[Claim]) -> dict[str, Any]:
        gold = {
            item["claim_id"]: bool(item["gold_supported"])
            for item in self.benchmark["cases"]
        }
        accepted = [item for item in claims if item.status == "accepted"]
        tp = sum(gold[item.claim_id] for item in accepted)
        fp = len(accepted) - tp
        supported = sum(gold.values())
        unsupported = len(gold) - supported
        fn = supported - tp
        precision = _safe_divide(tp, tp + fp)
        recall = _safe_divide(tp, tp + fn)
        f1 = _safe_divide(2 * precision * recall, precision + recall)
        evidence_complete = sum(
            bool(item.evidence_ids)
            and all(self.kb.evidence_is_valid(ref) for ref in item.evidence_ids)
            for item in accepted
        )
        paper_count = len(
            {
                self.kb.paper_id_for_evidence(ref)
                for item in accepted
                if gold[item.claim_id]
                for ref in item.evidence_ids
            }
        )
        precision_total = tp + fp
        return {
            "accepted_precision": round(precision, 3),
            "accepted_precision_ci95": _wilson_interval(tp, precision_total),
            "gold_recall": round(recall, 3),
            "gold_recall_ci95": _wilson_interval(tp, supported),
            "f1": round(f1, 3),
            "unsupported_acceptance_rate": round(
                _safe_divide(fp, unsupported),
                3,
            ),
            "unsupported_acceptance_rate_ci95": _wilson_interval(
                fp,
                unsupported,
            ),
            "evidence_coverage": round(
                _safe_divide(evidence_complete, len(accepted)),
                3,
            ),
            "evidence_coverage_ci95": _wilson_interval(
                evidence_complete,
                len(accepted),
            ),
            "evidence_coverage_kind": "structural_guardrail",
            "verified_triple_yield": round(
                _safe_divide(tp, paper_count),
                3,
            ),
            "accepted_count": len(accepted),
            "needs_review_count": sum(
                item.status == "needs_review" for item in claims
            ),
            "rejected_count": sum(item.status == "rejected" for item in claims),
            "gold_supported_count": supported,
            "gold_unsupported_count": unsupported,
            "true_positive_count": tp,
            "false_positive_count": fp,
            "false_negative_count": fn,
        }

    def _case_result(self, claim: Claim) -> dict[str, Any]:
        gold_case = next(
            item
            for item in self.benchmark["cases"]
            if item["claim_id"] == claim.claim_id
        )
        return {
            **deepcopy(claim.to_dict()),
            "gold_supported": gold_case["gold_supported"],
            "error_type": gold_case["error_type"],
            "correct": (
                (claim.status == "accepted")
                == bool(gold_case["gold_supported"])
            ),
        }
