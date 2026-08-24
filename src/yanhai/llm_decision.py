"""LLM-backed critic and judge for the three-agent decision layer.

Each role keeps the same duck-typed contract as the rule baseline
(``critique(claims, kb)`` / ``adjudicate(claims, kb)``), so they can be swapped
into the pipeline or into comparison experiments one by one. On any provider
failure the role falls back to the deterministic rule baseline, and a
model-independent hard guard always runs last so "no evidence -> accepted"
can never happen regardless of what a model says.
"""

from __future__ import annotations

import json
from typing import Any

from .agents import CriticAgent, JudgeAgent
from .models import Claim
from .providers import BaseProvider, ProviderError

CRITIC_SYSTEM = """你是"研海寻踪"的批判者 Agent。你的职责是查找候选命题的错误，而不是证明它正确。
对每条候选命题，对照证据原文与 schema 约束逐项检查，输出一个 JSON 对象。

检查维度：
1. evidence_valid：证据 ID 是否真实存在且有效（无效或缺失是阻断项）；
2. span_covers_both：证据文本是否同时提及关系两端实体（按表面形式/别名判断，
   不要只认英文规范名；中文别名也算命中）；
3. type_constraints_ok：关系类型是否符合 schema 的源/目标类型约束；
4. overclaim：是否使用绝对化谓词（guarantees/proves/必然/一定），
   或把"进行中/尝试做某事"写成"已完成某事"（时态/体误判）；
5. generic_cooccurrence：是否只是同句共现、不足以证明语义关系；
6. counter_evidence：证据中是否存在削弱该命题的内容。

输出 JSON 格式（不要输出任何其他文字）：
{
  "evidence_valid": true,
  "span_covers_both": true,
  "type_constraints_ok": true,
  "overclaim": false,
  "generic_cooccurrence": false,
  "counter_evidence_found": false,
  "criticisms": ["中文批判项"],
  "confidence": 0.0
}
规则：criticisms 里的每条批评必须引用具体证据或字段；没有问题的维度不要硬凑批评。"""

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_valid": {"type": "boolean"},
        "span_covers_both": {"type": "boolean"},
        "type_constraints_ok": {"type": "boolean"},
        "overclaim": {"type": "boolean"},
        "generic_cooccurrence": {"type": "boolean"},
        "counter_evidence_found": {"type": "boolean"},
        "criticisms": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": [
        "evidence_valid",
        "span_covers_both",
        "type_constraints_ok",
        "overclaim",
        "generic_cooccurrence",
        "counter_evidence_found",
        "criticisms",
        "confidence",
    ],
}

JUDGE_SYSTEM = """你是"研海寻踪"的裁判 Agent。你独立裁决，只看命题、证据与批判项的事实，
不受批判者措辞影响，也不偏向提出者。

输出 JSON 格式（不要输出任何其他文字）：
{
  "status": "accepted | needs_review | rejected",
  "score": 0.0,
  "breakdown": {"base": 0.0, "evidence_bonus": 0.0, "risk_penalty": 0.0},
  "reason": "中文裁决理由"
}
硬规则：
1. 没有任何有效证据 → status 必须是 rejected；
2. 绝对化/过度声明（guarantees/proves 等）→ 必须 rejected；
3. 证据有效且无阻断问题 → 可 accepted；
4. 有证据但存在单一来源/共现等限制 → needs_review；
5. score 取值 0.00 到 0.99，保留两位小数。"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["accepted", "needs_review", "rejected"]},
        "score": {"type": "number"},
        "breakdown": {
            "type": "object",
            "properties": {
                "base": {"type": "number"},
                "evidence_bonus": {"type": "number"},
                "risk_penalty": {"type": "number"},
            },
            "required": ["base", "evidence_bonus", "risk_penalty"],
        },
        "reason": {"type": "string"},
    },
    "required": ["status", "score", "breakdown", "reason"],
}


class UsageAccumulator:
    """Aggregates provider calls so experiments can report cost and latency."""

    def __init__(self) -> None:
        self.calls = 0
        self.failed_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.duration_ms = 0.0

    def record(self, response: Any) -> None:
        self.calls += 1
        usage = getattr(response, "usage", {}) or {}
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))
        self.duration_ms += float(getattr(response, "duration_ms", 0.0))

    def snapshot(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "failed_calls": self.failed_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": round(self.duration_ms, 1),
        }


def _claim_prompt(claim: Claim, kb: Any) -> str:
    evidence = kb.evidence_details(claim.evidence_ids)
    lines = [
        f"候选命题：{claim.source} -{claim.relation}-> {claim.target}",
        f"关系类型：{claim.relation_type}；源类型：{claim.source_type}；目标类型：{claim.target_type}",
        f"候选置信度：{claim.base_confidence}",
        "证据原文：",
    ]
    for item in evidence:
        lines.append(f"- [{item['evidence_id']}] {item['text']}")
    if not evidence:
        lines.append("- （没有任何有效证据）")
    return "\n".join(lines)


def hard_guard(claim: Claim, kb: Any) -> None:
    """Model-independent final gate. Runs AFTER any critic/judge output."""
    valid = [eid for eid in claim.evidence_ids if kb.evidence_is_valid(eid)]
    if not valid:
        claim.status = "rejected"
        claim.judge_reason = "护栏：没有任何有效证据，禁止进入 accepted。"
        if "缺少可追溯证据" not in claim.criticisms:
            claim.criticisms.append("缺少可追溯证据，不能进入最终资源。")
        return
    if claim.relation.casefold() in {"guarantees", "proves"}:
        claim.status = "rejected"
        claim.judge_reason = "护栏：绝对化谓词，结论强度超过现有证据。"
        return


class LLMCritic:
    """LLM 版批判者；失败时回退规则批判者。"""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        fallback_to_rules: bool = True,
        stats: UsageAccumulator | None = None,
    ) -> None:
        self.provider = provider
        self.fallback_to_rules = fallback_to_rules
        self.stats = stats or UsageAccumulator()
        self._rule = CriticAgent()

    def critique(self, claims: list[Claim], kb: Any) -> list[Claim]:
        for claim in claims:
            claim.criticisms = []
            try:
                payload, response = self.provider.complete_json(
                    CRITIC_SYSTEM,
                    _claim_prompt(claim, kb),
                    schema_name="critic_verdict",
                    schema=CRITIC_SCHEMA,
                    max_tokens=1024,
                )
                self.stats.record(response)
                claim.criticisms = self._map_criticisms(payload)
            except (ProviderError, ValueError, KeyError) as exc:
                self.stats.failed_calls += 1
                if self.fallback_to_rules:
                    self._rule.critique([claim], kb)
                else:
                    claim.criticisms.append(
                        f"批判者模型调用失败，转人工复核：{str(exc)[:200]}"
                    )
        return claims

    @staticmethod
    def _map_criticisms(payload: dict[str, Any]) -> list[str]:
        criticisms: list[str] = []
        if not bool(payload.get("evidence_valid", True)):
            criticisms.append("证据 ID 缺失或不存在。")
        if not bool(payload.get("span_covers_both", True)):
            criticisms.append("证据跨度没有同时覆盖关系两端实体。")
        if not bool(payload.get("type_constraints_ok", True)):
            criticisms.append("关系类型约束不匹配。")
        if bool(payload.get("overclaim", False)):
            criticisms.append("使用绝对化谓词或把进行中/尝试误写为已完成。")
        if bool(payload.get("generic_cooccurrence", False)):
            criticisms.append("同句共现不能直接证明语义关系，需要人工复核。")
        if bool(payload.get("counter_evidence_found", False)):
            criticisms.append("证据中存在削弱该命题的内容。")
        criticisms.extend(
            str(item)
            for item in (payload.get("criticisms") or [])
            if str(item) not in criticisms
        )
        if not criticisms:
            criticisms.append("证据与命题结构一致，未发现阻断性问题。")
        return criticisms


class LLMJudge:
    """LLM 版裁判；失败时回退规则裁判。"""

    def __init__(
        self,
        provider: BaseProvider,
        *,
        fallback_to_rules: bool = True,
        stats: UsageAccumulator | None = None,
    ) -> None:
        self.provider = provider
        self.fallback_to_rules = fallback_to_rules
        self.stats = stats or UsageAccumulator()
        self._rule = JudgeAgent()

    def adjudicate(self, claims: list[Claim], kb: Any) -> list[Claim]:
        for claim in claims:
            try:
                prompt = (
                    _claim_prompt(claim, kb)
                    + "\n批判者给出的结构化批判项：\n"
                    + json.dumps(claim.criticisms, ensure_ascii=False)
                )
                payload, response = self.provider.complete_json(
                    JUDGE_SYSTEM,
                    prompt,
                    schema_name="judge_verdict",
                    schema=JUDGE_SCHEMA,
                    max_tokens=1024,
                )
                self.stats.record(response)
                claim.status = str(payload["status"])
                claim.judge_score = max(0.0, min(0.99, float(payload["score"])))
                breakdown = payload.get("breakdown") or {}
                claim.score_breakdown = {
                    "base": round(float(breakdown.get("base", claim.base_confidence)), 3),
                    "evidence_bonus": round(float(breakdown.get("evidence_bonus", 0.0)), 3),
                    "risk_penalty": round(float(breakdown.get("risk_penalty", 0.0)), 3),
                }
                claim.judge_reason = str(payload.get("reason", ""))[:500]
            except (ProviderError, ValueError, KeyError) as exc:
                self.stats.failed_calls += 1
                if self.fallback_to_rules:
                    self._rule.adjudicate([claim], kb)
                else:
                    claim.status = "needs_review"
                    claim.judge_reason = f"裁判模型调用失败，转人工复核：{str(exc)[:200]}"
            hard_guard(claim, kb)
        return claims
