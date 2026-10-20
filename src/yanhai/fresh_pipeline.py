"""Fresh-paper end-to-end pipeline, shared by the labs and the FastAPI backend.

Runs a single pasted paper through structure parsing, rule extraction, learner
diagnosis, the three decision agents and personalized resource generation, and
returns every intermediate stage for transparent inspection.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .agents import (
    CriticAgent,
    DiagnosisAgent,
    JudgeAgent,
    ProposerAgent,
    ResourceAgent,
)
from .extraction import PlainTextParser, SchemaGuidedExtractor, ScientificDocument
from .fresh_extraction import extract_documents_generic
from .fresh_kb import FreshPaperKB
from .llm_decision import LLMCritic, LLMJudge, UsageAccumulator
from .models import LearnerProfile
from .providers import ProviderConfig, create_provider


def load_schema(schema_path: Path) -> dict[str, Any]:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _resolve_decision_layer(
    provider_config: ProviderConfig | None,
    decision_mode: str = "auto",
) -> tuple[Any, Any, str, UsageAccumulator]:
    """按 `decision_mode` 组装批判者与裁判，与编排器 `_resolve_decision_layer` 同一套约定。

    `decision_mode="auto"`（默认）即原行为：非 mock provider 时批判者和裁判一起换成
    LLM 版，否则两个都用规则版。`"hybrid"` 让批判者用模型、裁判保持规则版——裁判那
    一侧仍会跑 `hard_guard`，保持和 `LLMJudge` 一致的硬护栏。
    """
    if decision_mode not in ("auto", "rules", "llm", "hybrid"):
        raise ValueError(f"未知的 decision_mode：{decision_mode}")
    is_remote = provider_config is not None and provider_config.provider != "mock"
    if decision_mode == "auto":
        decision_mode = "llm" if is_remote else "rules"
    if decision_mode != "rules" and not is_remote:
        raise ValueError(
            f"decision_mode={decision_mode!r} 需要非 mock 的 provider_config。"
        )
    if decision_mode == "rules":
        return CriticAgent(), JudgeAgent(), "rules", UsageAccumulator()
    assert provider_config is not None
    stats = UsageAccumulator()
    provider = create_provider(provider_config)
    if decision_mode == "hybrid":
        return LLMCritic(provider, stats=stats), JudgeAgent(), "hybrid", stats
    critic = LLMCritic(provider, stats=stats)
    judge = LLMJudge(provider, stats=stats)
    return critic, judge, decision_mode, stats


def run_fresh_document_pipeline(
    *,
    document: ScientificDocument,
    profile: LearnerProfile,
    schema_path: Path,
    accept_threshold: float = 0.72,
    provider_config: ProviderConfig | None = None,
    decision_mode: str = "auto",
) -> dict[str, Any]:
    """Run the full pipeline on an already-parsed document (text or PDF pages)."""
    schema = load_schema(schema_path)
    extractor = SchemaGuidedExtractor.from_path(
        schema_path, accept_threshold=accept_threshold
    )
    extraction = extractor.extract_documents([document]).to_dict()

    # 内置词表只认那 188 个概念，用户自己的研究方向十天里有九天命中不了。
    # 一条关系都没抽出来时，改用通用抽取：实体名从这篇论文自己的文字里挖，
    # 关系类型仍按共享本体判。换的是"认不认识这个词"，不是"判得松不松"——
    # 候选置信度压在接收线以下，全部进待复核队列。
    extractor_used = "schema-guided-pattern"
    if not extraction.get("relations"):
        fallback = extract_documents_generic(extractor, [document])
        fallback_payload = fallback.to_dict()
        if fallback_payload.get("relations"):
            extraction = fallback_payload
            extractor_used = "generic-pattern"
        else:
            # 两条路都抽不出关系：保留原来那份（至少句子与审计数还在），
            # 但把"为什么没有"写进审计，界面照实显示。
            extraction.setdefault("audit", {}).setdefault("quality", {})[
                "note"
            ] = "内置词表与通用抽取都没有从这篇论文里抽出关系，正文可能太短或缺少实体与谓词。"

    kb = FreshPaperKB(extraction, schema)
    paper = kb.paper_by_id[document.paper_id]

    diagnosis = DiagnosisAgent().diagnose(profile)

    # 三智能体裁决层：默认 auto 与原行为相同；显式 decision_mode="hybrid" 时
    # 批判者用模型、裁判保持规则版。见 `_resolve_decision_layer`。
    critic, judge, decision_mode, decision_stats = _resolve_decision_layer(
        provider_config, decision_mode
    )

    started = time.perf_counter()
    claims = ProposerAgent().propose(kb, [paper])
    proposer_ms = (time.perf_counter() - started) * 1000
    proposed_claims = [claim.to_dict() for claim in claims]

    started = time.perf_counter()
    claims = critic.critique(claims, kb)
    critic_ms = (time.perf_counter() - started) * 1000
    critiqued_claims = [claim.to_dict() for claim in claims]

    started = time.perf_counter()
    claims = judge.adjudicate(claims, kb)
    judge_ms = (time.perf_counter() - started) * 1000
    adjudicated_claims = [claim.to_dict() for claim in claims]

    resources = ResourceAgent().generate(profile, diagnosis, claims, kb)

    accepted = [claim for claim in claims if claim.status == "accepted"]
    accepted_without_evidence = [claim for claim in accepted if not claim.evidence_ids]
    text_char_count = sum(len(text) for text in document.sections.values())

    # Real multi-agent trace: every summary below is derived from the actual
    # staged outputs (claim criticisms, judge reasons and score breakdowns),
    # never from hardcoded narration.
    flagged_claims = [
        claim for claim in claims if any("缺少" in note or "绝对化" in note for note in claim.criticisms)
    ]
    issue_kinds: dict[str, int] = {}
    for claim in claims:
        for note in claim.criticisms:
            key = note[:12]
            issue_kinds[key] = issue_kinds.get(key, 0) + 1
    top_issues = "、".join(
        f"{key}×{count}" for key, count in sorted(issue_kinds.items(), key=lambda item: -item[1])[:3]
    ) or "无阻断性问题"
    agent_trace = [
        {
            "agent": "ProposerAgent",
            "role": "关联提出",
            "status": "completed",
            "summary": (
                f"基于 {len(extraction['entities'])} 个实体与 "
                f"{len(extraction['relations'])} 条关系候选，提出 {len(claims)} 条命题。"
            ),
            "details": {"proposed": len(claims)},
            "duration_ms": round(proposer_ms, 2),
        },
        {
            "agent": critic.name,
            "role": "反证与约束",
            "status": "completed",
            "summary": (
                f"完成证据交叉检查，标记 {len(flagged_claims)} 条高风险命题；"
                f"主要问题：{top_issues}。"
            ),
            "details": {
                "flagged": len(flagged_claims),
                "issue_breakdown": issue_kinds,
            },
            "duration_ms": round(critic_ms, 2),
        },
        {
            "agent": judge.name,
            "role": "置信裁决",
            "status": "completed",
            "summary": (
                f"通过 {sum(c.status == 'accepted' for c in claims)} 条、"
                f"待复核 {sum(c.status == 'needs_review' for c in claims)} 条、"
                f"拒绝 {sum(c.status == 'rejected' for c in claims)} 条；"
                "无证据强断言未进入资源。"
            ),
            "details": {
                "accepted": sum(c.status == "accepted" for c in claims),
                "needs_review": sum(c.status == "needs_review" for c in claims),
                "rejected": sum(c.status == "rejected" for c in claims),
            },
            "duration_ms": round(judge_ms, 2),
        },
    ]
    specialist_agent_trace = [
        {
            "agent": "结构解析",
            "role": "章节切分",
            "status": "completed",
            "summary": (
                f"切分 {len(document.sections)} 个章节，共 {text_char_count} 字符。"
            ),
            "details": {"sections": list(document.sections.keys())},
        },
        {
            "agent": "SchemaGuidedExtractor",
            "role": "实体/关系/证据抽取",
            "status": "completed",
            "summary": (
                f"抽取 {len(extraction['entities'])} 个实体、"
                f"{len(extraction['relations'])} 条关系候选、"
                f"{len(extraction['evidence'])} 条证据跨度。"
            ),
            "details": {
                "entities": len(extraction["entities"]),
                "relations": len(extraction["relations"]),
                "evidence": len(extraction["evidence"]),
            },
        },
        {
            "agent": "DiagnosisAgent",
            "role": "学情诊断",
            "status": "completed",
            "summary": (
                f"准备度 {diagnosis['readiness_score']}，目标难度 "
                f"L{diagnosis['target_difficulty']}；识别盲区 "
                f"{len(diagnosis['blind_spots'])} 项。"
            ),
            "details": {
                "readiness_score": diagnosis["readiness_score"],
                "target_difficulty": diagnosis["target_difficulty"],
                "blind_spots": diagnosis["blind_spots"],
            },
        },
    ]
    return {
        "run_id": uuid.uuid4().hex,
        "fingerprint": {
            "paper_id": document.paper_id,
            "title": document.title,
            "text_char_count": text_char_count,
            "accept_threshold": accept_threshold,
            "profile_id": profile.profile_id,
            "schema_version": extraction["schema_version"],
        },
        "document": {
            "paper_id": document.paper_id,
            "title": document.title,
            "sections": document.sections,
        },
        "extraction": extraction,
        "diagnosis": diagnosis,
        "proposed_claims": proposed_claims,
        "critiqued_claims": critiqued_claims,
        "adjudicated_claims": adjudicated_claims,
        "agent_trace": agent_trace,
        "specialist_agent_trace": specialist_agent_trace,
        "resources": resources,
        "decision_layer": {
            "mode": decision_mode,
            "provider": (
                provider_config.public_dict()
                if provider_config is not None
                else None
            ),
            "usage": decision_stats.snapshot(),
        },
        "summary": {
            "entity_count": len(extraction["entities"]),
            "candidate_relation_count": len(extraction["relations"]),
            "claim_count": len(claims),
            "accepted_count": len(accepted),
            "rejected_count": sum(c.status == "rejected" for c in claims),
            "needs_review_count": sum(c.status == "needs_review" for c in claims),
            "accepted_without_evidence_count": len(accepted_without_evidence),
            "extractor": extractor_used,
        },
    }


def run_fresh_paper_pipeline(
    *,
    paper_id: str,
    title: str,
    text: str,
    profile: LearnerProfile,
    schema_path: Path,
    accept_threshold: float = 0.72,
    provider_config: ProviderConfig | None = None,
    decision_mode: str = "auto",
) -> dict[str, Any]:
    """Run the full pipeline on one pasted paper and return staged intermediates."""
    document = PlainTextParser().parse_text(
        text,
        paper_id=paper_id,
        fallback_title=title or paper_id,
        source_url="member-pasted-text",
    )
    return run_fresh_document_pipeline(
        document=document,
        profile=profile,
        schema_path=schema_path,
        accept_threshold=accept_threshold,
        provider_config=provider_config,
        decision_mode=decision_mode,
    )
