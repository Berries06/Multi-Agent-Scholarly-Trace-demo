"""AI 组会：把提出者—批判者—裁判的判定过程排成一段可以读的对话。

为什么要有这一层：三个智能体的辩论原来只体现在 `claim.criticisms` 这种字段里，
用户看不到"机器是怎么挑关系的"，只看到 700 条候选让他逐条判——这既不像 AI 产品，
也把工作量全压在人身上。这个模块**不改任何判定逻辑**，只把已有的结构化输出
（提案、批判意见、分数拆解、裁决状态）翻译成三段一句的对话。

诚实边界：判定层是规则代码时，发言是模板生成的，界面必须标「规则裁判」；
配上模型（`LLMCritic` / `LLMJudge`）时发言才是模型给的。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .models import Claim

PROPOSER = "提出者"
CRITIC = "批判者"
JUDGE = "裁判"
CHAIR = "组会"

STATUS_WORD = {
    "accepted": "采纳",
    "needs_review": "转人工",
    "rejected": "驳回",
}

MODE_WORD = {
    "rules": "规则裁判",
    "llm": "模型裁判",
    "hybrid": "模型批判 + 规则裁判",
    "auto": "自动",
}


@dataclass(slots=True)
class PanelMessage:
    seq: int
    agent: str
    kind: str
    text: str
    relation_id: str = ""
    status: str = ""
    confidence: float = 0.0
    evidence_id: str = ""
    paper_id: str = ""
    section_id: str = ""
    char_start: int = 0
    char_end: int = 0
    evidence_text: str = ""
    checks: list[str] = field(default_factory=list)
    score: dict[str, float] = field(default_factory=dict)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "agent": self.agent,
            "kind": self.kind,
            "text": self.text,
            "relation_id": self.relation_id,
            "status": self.status,
            "confidence": round(self.confidence, 3),
            "evidence_id": self.evidence_id,
            "paper_id": self.paper_id,
            "section_id": self.section_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "evidence_text": self.evidence_text,
            "checks": list(self.checks),
            "score": {key: round(value, 3) for key, value in self.score.items()},
            "truncated": self.truncated,
        }


def claims_from_relations(
    relations: Iterable[dict[str, Any]],
    *,
    evidence_papers: dict[str, str] | None = None,
) -> list[Claim]:
    """把项目里的候选关系行转成 Claim，交给原来的批判者与裁判。

    `evidence_papers` 只用于把证据 ID 归类到论文，不参与判定。
    """
    claims: list[Claim] = []
    for index, relation in enumerate(relations, start=1):
        claims.append(
            Claim(
                claim_id=str(relation.get("relation_id") or f"P{index:03d}"),
                source=str(relation.get("source_name") or ""),
                relation=str(relation.get("relation_type") or "").lower(),
                target=str(relation.get("target_name") or ""),
                relation_type=str(relation.get("relation_type") or ""),
                base_confidence=float(relation.get("confidence") or 0),
                source_type=str(relation.get("source_type") or ""),
                target_type=str(relation.get("target_type") or ""),
                evidence_ids=list(relation.get("evidence_ids") or []),
                proposal_reason="来自项目里的候选关系",
                model_route="user-import",
                status=str(relation.get("machine_status") or "needs_review"),
            )
        )
    return claims


def _short(text: str, limit: int = 120) -> tuple[str, bool]:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned, False
    return cleaned[: limit - 1] + "…", True


def _critic_line(criticisms: list[str]) -> str:
    """批判者只说一到两句，不再把九条清单全倒出来。"""
    if not criticisms:
        return "没意见。证据能对上关系两端，类型与方向都没问题。"
    first = criticisms[0]
    if len(criticisms) == 1:
        return first
    return f"{first}另外还有 {len(criticisms) - 1} 条次要意见。"


def _shown_score(score_breakdown: dict[str, float], judge_score: float) -> float:
    """要显示给用户的分数：按拆解把真实值算回来。

    判定层（`agents.py`）会用 `max(0.0, …)` 把负分截到 0，于是界面上就成了一屏
    「综合分 0.00」，看着像没算。2026-10-20 用户就是这么问的。这里用拆解求和还原：
    基础分 + 各项奖励 − 风险惩罚，是多少显示多少（可能是负数，比如 −0.03）。
    没有拆解时退回判定层给的值。
    """
    if not score_breakdown:
        return judge_score
    return sum(float(value or 0) for value in score_breakdown.values())


def _judge_line(status: str, score_breakdown: dict[str, float], judge_score: float) -> str:
    """裁判给一句人话，不复述公式。"""
    if status == "accepted":
        return f"综合分 {judge_score:.2f}，接收条件全过，采纳。"
    if status == "needs_review":
        return f"综合分 {judge_score:.2f}，还没到直接采纳的线，转人工复核。"
    penalty = abs(float(score_breakdown.get("risk_penalty") or 0))
    if penalty >= 0.3:
        return f"综合分 {judge_score:.2f}，卡在一条硬条件上，驳回。"
    return f"综合分 {judge_score:.2f}，证据或分数不够，驳回。"


def compose_panel(
    claims: list[Claim],
    *,
    evidence_index: dict[str, dict[str, Any]],
    mode: str = "rules",
    limit: int = 20,
    total_available: int = 0,
) -> dict[str, Any]:
    """把一批已经判过的 claim 排成对话。

    `claims` 必须是**已经过批判者与裁判**的对象（`criticisms`、`status`、
    `judge_score`、`score_breakdown` 都已填好）。
    """
    messages: list[PanelMessage] = []
    seq = 0
    verdicts: list[dict[str, Any]] = []

    def push(**kwargs: Any) -> None:
        nonlocal seq
        seq += 1
        messages.append(PanelMessage(seq=seq, **kwargs))

    for claim in claims[:limit]:
        span = (evidence_index.get(claim.evidence_ids[0]) if claim.evidence_ids else None) or {}
        text, truncated = _short(span.get("text") or "", 160)
        push(
            agent=PROPOSER,
            kind="提案",
            text=f"{claim.source} —{claim.relation_type}→ {claim.target}",
            relation_id=claim.claim_id,
            confidence=claim.base_confidence,
            evidence_id=str(span.get("evidence_id") or ""),
            paper_id=str(span.get("paper_id") or ""),
            section_id=str(span.get("section_id") or ""),
            char_start=int(span.get("char_start") or 0),
            char_end=int(span.get("char_end") or 0),
            evidence_text=text,
            truncated=truncated,
            checks=[],
        )
        push(
            agent=CRITIC,
            kind="质疑",
            text=_critic_line(list(claim.criticisms)),
            relation_id=claim.claim_id,
            checks=list(claim.criticisms),
        )
        shown = _shown_score(dict(claim.score_breakdown), claim.judge_score)
        push(
            agent=JUDGE,
            kind="裁决",
            text=_judge_line(claim.status, dict(claim.score_breakdown), shown),
            relation_id=claim.claim_id,
            status=claim.status,
            confidence=shown,
            score=dict(claim.score_breakdown),
        )
        verdicts.append(
            {
                "relation_id": claim.claim_id,
                "status": claim.status,
                "verdict": STATUS_WORD.get(claim.status, claim.status),
                "judge_score": round(shown, 3),
                "judge_score_clamped": round(claim.judge_score, 3),
                "source": claim.source,
                "relation_type": claim.relation_type,
                "target": claim.target,
                "confidence": round(claim.base_confidence, 3),
                "evidence_count": len(claim.evidence_ids),
                "paper_id": str(span.get("paper_id") or ""),
            }
        )

    counts = {"accepted": 0, "needs_review": 0, "rejected": 0}
    for verdict in verdicts:
        counts[verdict["status"]] = counts.get(verdict["status"], 0) + 1
    covered = len(verdicts)
    summary = (
        f"这次过 {covered} 条：采纳 {counts['accepted']}、转人工 {counts['needs_review']}、"
        f"驳回 {counts['rejected']}。"
    )
    if total_available > covered:
        summary += f"队列里还有 {total_available - covered} 条，下一轮再看。"
    push(agent=CHAIR, kind="汇总", text=summary, checks=[])

    return {
        "mode": mode,
        "mode_label": MODE_WORD.get(mode, mode),
        "messages": [message.to_dict() for message in messages],
        "verdicts": verdicts,
        "counts": {"processed": covered, "remaining": max(0, total_available - covered), **counts},
    }
