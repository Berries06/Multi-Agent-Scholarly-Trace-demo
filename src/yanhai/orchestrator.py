from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import (
    EvidenceGraphAgent,
    LearnerPlanningAgent,
    PersonalizedTeachingAgent,
)
from .config import LEGACY, SystemConfig, get_preset
from .knowledge import KnowledgeBase
from .live_research import LiveResearchService
from .models import AgentTrace, Claim, LearnerProfile
from .probes import PerformanceProbe
from .providers import ProviderConfig, create_provider
from .quality import QualityGate


DEFAULT_QUERY = "多智能体科研推理如何通过证据溯源降低幻觉并发现研究蓝海？"


class ScholarlyTraceOrchestrator:
    """Dependency-free research pipeline with isolated experimental switches."""

    def __init__(
        self,
        project_root: Path | None = None,
        config: SystemConfig | str | None = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.config = self._resolve_config(config) if config is not None else LEGACY
        self.kb = KnowledgeBase(self.project_root / "data" / "knowledge")
        profile_path = self.project_root / "data" / "profiles" / "profiles.json"
        raw_profiles = json.loads(profile_path.read_text(encoding="utf-8"))
        self.profiles = {
            profile.profile_id: profile
            for profile in (LearnerProfile.from_dict(item) for item in raw_profiles)
        }
        self.learner_agent = LearnerPlanningAgent()
        self.evidence_agent = EvidenceGraphAgent()
        self.teaching_agent = PersonalizedTeachingAgent()
        self.quality_gate = QualityGate()

    @staticmethod
    def _resolve_config(config: SystemConfig | str | None) -> SystemConfig:
        if config is None:
            return LEGACY
        if isinstance(config, str):
            return get_preset(config)
        return config

    def list_profiles(self) -> list[dict[str, Any]]:
        return [profile.public_dict() for profile in self.profiles.values()]

    @staticmethod
    def _trace(
        traces: list[AgentTrace],
        probe: PerformanceProbe,
        stage: str,
        agent: str,
        role: str,
        summary: str,
        input_count: int = 0,
        output_count: int = 0,
    ) -> None:
        traces.append(
            AgentTrace(
                agent=agent,
                role=role,
                status="completed",
                summary=summary,
                duration_ms=probe.duration(stage),
                input_count=input_count,
                output_count=output_count,
            )
        )

    def run(
        self,
        profile_id: str,
        query: str = DEFAULT_QUERY,
        difficulty_adjustment: int = 0,
        config: SystemConfig | str | None = None,
        *,
        feedback: str | None = None,
        prior_knowledge_state: dict[str, Any] | None = None,
        concept_feedback: dict[str, Any] | None = None,
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        active = self._resolve_config(config) if config is not None else self.config
        flags = active.flags
        profile = self.profiles[profile_id]
        probe = PerformanceProbe(flags.performance_probes)
        traces: list[AgentTrace] = []

        with probe.measure("learner_planning"):
            learner_output = self.learner_agent.plan(
                profile,
                difficulty_adjustment,
                feedback=feedback,
                enable_knowledge_tracing=(
                    flags.knowledge_tracing
                    or feedback is not None
                    or bool(concept_feedback)
                    or bool(questionnaire)
                ),
                prior_state=prior_knowledge_state,
                concept_feedback=concept_feedback,
                questionnaire=questionnaire,
            )
        diagnosis = learner_output["diagnosis"]
        knowledge_state = learner_output["knowledge_state"]
        traces.append(
            AgentTrace(
                agent=self.learner_agent.name,
                role="学情诊断与学习规划",
                status="completed",
                summary=(
                    f"定位 {len(diagnosis['blind_spots'])} 个知识盲区，"
                    f"目标难度 L{diagnosis['target_difficulty']}，"
                    f"形成 {len(diagnosis['learning_path'])} 步学习路径。"
                ),
                duration_ms=probe.duration("learner_planning"),
                input_count=len(profile.knowledge_scores),
                output_count=len(diagnosis["learning_path"]),
            )
        )

        with probe.measure("evidence_collection"):
            evidence_output = self.evidence_agent.collect(
                self.kb,
                query,
                profile,
                diagnosis,
                active,
            )
        papers = evidence_output["papers"]
        claims = evidence_output["claims"]

        with probe.measure("quality_gate"):
            quality_assessment = self.quality_gate.assess_and_admit(
                claims,
                self.kb,
                acceptance_threshold=active.acceptance_threshold,
                review_threshold=active.review_threshold,
                calibrated=flags.calibrated_judge,
                abstention=flags.abstention,
                enforce=flags.judge,
            )

        with probe.measure("evidence_discovery"):
            discovery_output = self.evidence_agent.discover(
                papers,
                claims,
                active,
            )
        discovery = discovery_output["discovery"]
        hypotheses = discovery_output["hypotheses"]
        accepted = sum(claim.status == "accepted" for claim in claims)
        rejected = sum(claim.status == "rejected" for claim in claims)
        abstained = sum(claim.status == "abstained" for claim in claims)
        traces.append(
            AgentTrace(
                agent=self.evidence_agent.name,
                role="证据检索与知识图谱构建",
                status="completed",
                summary=(
                    f"召回 {len(papers)} 篇来源并提出 {len(claims)} 条命题；"
                    f"内部启用 {len(evidence_output['strategies'])} 项策略，"
                    f"质量门控放行 {accepted} 条。"
                ),
                duration_ms=(
                    probe.duration("evidence_collection")
                    + probe.duration("evidence_discovery")
                ),
                input_count=len(self.kb.papers),
                output_count=len(claims),
            )
        )

        with probe.measure("personalized_teaching"):
            resources = self.teaching_agent.teach(
                profile,
                diagnosis,
                claims,
                self.kb,
                knowledge_state=knowledge_state,
                hypotheses=hypotheses,
                discovery=discovery,
            )
        traces.append(
            AgentTrace(
                agent=self.teaching_agent.name,
                role="个性化教学与反馈",
                status="completed",
                summary=(
                    "使用通过质量门控的知识生成导读、实操、测评，"
                    "并附带 Demo 反馈问卷。"
                ),
                duration_ms=probe.duration("personalized_teaching"),
                input_count=accepted,
                output_count=3,
            )
        )

        with probe.measure("graph_construction"):
            claim_dicts = [claim.to_dict() for claim in claims]
            graph = self.kb.graph_for_claims(
                claim_dicts,
                include_provenance=flags.sentence_provenance,
            )
        metrics = self._metrics(profile, diagnosis, claims, resources)
        quality_assessment = self.quality_gate.evaluate_result(
            quality_assessment,
            profile,
            diagnosis,
            claims,
            resources,
            questionnaire,
        )
        report = {
            "blind_spots": diagnosis["blind_spots"],
            "strengths": diagnosis["strengths"],
            "difficulty_curve": diagnosis["difficulty_curve"],
            "learning_path": diagnosis["learning_path"],
            "resource_match_score": diagnosis["resource_match_score"],
            "feedback_adjustment": difficulty_adjustment,
            "knowledge_state": knowledge_state,
        }

        probe.set_counter("papers_in_knowledge_base", len(self.kb.papers))
        probe.set_counter("papers_retrieved", len(papers))
        probe.set_counter("claims_proposed", len(claims))
        probe.set_counter("claims_accepted", accepted)
        probe.set_counter("claims_rejected", rejected)
        probe.set_counter("claims_abstained", abstained)
        probe.set_counter(
            "evidence_spans", sum(len(claim.evidence_spans) for claim in claims)
        )
        probe.set_counter(
            "falsification_rounds",
            sum(len(claim.falsification_steps) for claim in claims),
        )
        probe.set_counter("graph_nodes", len(graph["nodes"]))
        probe.set_counter("graph_edges", len(graph["edges"]))
        probe.set_counter("hypothesis_candidates", len(hypotheses))

        innovations = {
            "knowledge_state": knowledge_state,
            "discovery": discovery,
            "hypotheses": hypotheses,
            "falsification": {
                "rounds": sum(
                    len(claim.falsification_steps) for claim in claims
                ),
                "failed": sum(
                    step["outcome"] == "failed"
                    for claim in claims
                    for step in claim.falsification_steps
                ),
                "unresolved": sum(
                    step["outcome"] == "unresolved"
                    for claim in claims
                    for step in claim.falsification_steps
                ),
            },
            "debate_view_count": sum(
                len(claim.debate_views) for claim in claims
            ),
            "internal_strategies": evidence_output["strategies"],
        }
        return {
            "project": "研海寻踪",
            "query": query,
            "system_config": active.to_dict(),
            "profile": profile.public_dict(),
            "diagnosis": diagnosis,
            "agent_trace": [trace.to_dict() for trace in traces],
            "papers": [paper.to_dict() for paper in papers],
            "claims": claim_dicts,
            "graph": graph,
            "resources": resources,
            "innovations": innovations,
            "quality_assessment": quality_assessment,
            "report": report,
            "metrics": metrics,
            "performance": probe.snapshot(),
        }

    def run_with_feedback(
        self,
        profile_id: str,
        feedback: str,
        query: str = DEFAULT_QUERY,
        config: SystemConfig | str | None = None,
        *,
        prior_knowledge_state: dict[str, Any] | None = None,
        concept_feedback: dict[str, Any] | None = None,
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adjustments = {"too_hard": -1, "suitable": 0, "too_easy": 1}
        if feedback not in adjustments:
            raise ValueError(f"Unknown feedback: {feedback}")
        result = self.run(
            profile_id,
            query,
            adjustments[feedback],
            config,
            feedback=feedback,
            prior_knowledge_state=prior_knowledge_state,
            concept_feedback=concept_feedback,
            questionnaire=questionnaire,
        )
        result["feedback"] = {
            "signal": feedback,
            "decision": {
                "too_hard": "降低解释维度，补充概念示例。",
                "suitable": "保持当前路径，继续证据追踪。",
                "too_easy": "提升难度，加入消融与蓝海挑战。",
            }[feedback],
        }
        return result

    def run_with_provider(
        self,
        profile_id: str,
        query: str,
        provider_config: ProviderConfig,
        config: SystemConfig | str | None = None,
        *,
        difficulty_adjustment: int = 0,
        feedback: str | None = None,
        prior_knowledge_state: dict[str, Any] | None = None,
        concept_feedback: dict[str, Any] | None = None,
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the preserved offline baseline or an evidence-grounded live LLM path.

        API keys remain inside ``provider_config`` for the duration of this call.
        They are never attached to the returned result or stored on the orchestrator.
        """

        result = self.run(
            profile_id,
            query,
            difficulty_adjustment,
            config,
            feedback=feedback,
            prior_knowledge_state=prior_knowledge_state,
            concept_feedback=concept_feedback,
            questionnaire=questionnaire,
        )
        if provider_config.provider == "mock":
            result["provider_run"] = {
                **provider_config.public_dict(),
                "mode": "offline_mock",
                "source_mode": "local_mock",
                "calls": [],
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "llm_duration_ms": 0.0,
                "retrieval_duration_ms": next(
                    (
                        stage["duration_ms"]
                        for stage in result["performance"]["stages"]
                        if stage["name"] == "evidence_collection"
                    ),
                    0.0,
                ),
                "warnings": [],
                "api_key_persisted": False,
            }
            return result

        provider = create_provider(provider_config)
        service = LiveResearchService(
            provider,
            provider_config,
            self.kb,
        )
        live = service.run(
            query,
            self.profiles[profile_id],
            result["diagnosis"],
        )
        baseline_summary = {
            "preset": result["system_config"]["name"],
            "paper_count": len(result["papers"]),
            "claim_count": len(result["claims"]),
            "preserved_as_provider": "mock",
        }
        result.update(
            {
                "answer": live["answer"],
                "answer_sections": live["answer_sections"],
                "papers": live["papers"],
                "claims": live["claims"],
                "resources": live["resources"],
                "graph": live["graph"],
                "provider_run": live["provider_run"],
                "mock_baseline": baseline_summary,
                "quality_assessment": live.get("quality_assessment", result["quality_assessment"]),
            }
        )
        ratings = [
            float(value)
            for value in (questionnaire or {}).values()
            if isinstance(value, (int, float)) and 1 <= float(value) <= 5
        ]
        if ratings:
            feedback_score = round(20 * sum(ratings) / len(ratings), 1)
            quality = result["quality_assessment"]
            quality["scores"]["user_feedback"] = feedback_score
            quality["scores"]["overall_quality"] = round(
                0.35 * quality["scores"].get("evidence_grounding", 0.0)
                + 0.25 * quality["scores"].get("profile_fit", 0.0)
                + 0.20 * quality["scores"].get("knowledge_coverage", 0.0)
                + 0.20 * feedback_score,
                1,
            )
            quality["questionnaire"] = {
                "received": True,
                "response_count": len(ratings),
                "scope": "demo_in_memory",
            }
        result["agent_trace"] = self._live_trace(
            result["agent_trace"],
            live["provider_run"],
            len(live["papers"]),
            len(live["claims"]),
        )
        result["metrics"] = self._live_metrics(result)
        result["performance"]["live_llm_ms"] = live["provider_run"]["llm_duration_ms"]
        result["performance"]["live_retrieval_ms"] = live["provider_run"][
            "retrieval_duration_ms"
        ]
        result["innovations"] = self._live_innovations(result)
        return result

    @staticmethod
    def _live_trace(
        baseline_trace: list[dict[str, Any]],
        provider_run: dict[str, Any],
        paper_count: int,
        claim_count: int,
    ) -> list[dict[str, Any]]:
        learner = dict(baseline_trace[0]) if baseline_trace else {
            "agent": "学情诊断与学习规划 Agent",
            "role": "学情诊断与学习规划",
            "status": "completed",
            "summary": "已形成结构化学习计划。",
            "duration_ms": 0.0,
            "input_count": 1,
            "output_count": 1,
        }
        calls = provider_run.get("calls", [])
        call_by_role = {str(call.get("role")): call for call in calls}
        evidence_duration = provider_run.get("retrieval_duration_ms", 0.0)
        for role in ("检索规划", "证据提出"):
            evidence_duration += float(call_by_role.get(role, {}).get("duration_ms", 0.0))
        evidence_status = (
            "abstained"
            if provider_run.get("evidence_status") == "insufficient"
            else (
                "degraded"
                if provider_run.get("source_mode") == "local_fallback"
                else "completed"
            )
        )
        teaching_call = call_by_role.get("个性化教学与反馈", {})
        return [
            learner,
            {
                "agent": "证据检索与知识图谱 Agent",
                "role": "证据检索与知识图谱构建",
                "status": evidence_status,
                "summary": (
                    f"检索 {paper_count} 篇来源并形成 {claim_count} 条候选命题；"
                    "批判、反证和来源核验作为内部策略执行。"
                ),
                "duration_ms": round(float(evidence_duration), 3),
                "input_count": len(provider_run.get("search_queries", [])),
                "output_count": claim_count,
            },
            {
                "agent": "个性化教学与反馈 Agent",
                "role": "个性化教学与反馈",
                "status": "completed" if teaching_call else "abstained",
                "summary": (
                    "使用通过质量准入的知识生成导读、实操、测评和反馈问卷。"
                    if teaching_call
                    else "当前证据不足，未生成未经支持的教学资源。"
                ),
                "duration_ms": float(teaching_call.get("duration_ms", 0.0)),
                "input_count": claim_count,
                "output_count": 3 if teaching_call else 0,
            },
        ]

    @staticmethod
    def _live_metrics(result: dict[str, Any]) -> dict[str, Any]:
        claims = result["claims"]
        accepted = [claim for claim in claims if claim["status"] == "accepted"]
        supported = [
            claim
            for claim in claims
            if claim["evidence_ids"] and claim["evidence_spans"]
        ]
        unsupported_accepted = [
            claim for claim in accepted if not claim["evidence_ids"]
        ]
        hallucination_proxy = (
            100 * len(unsupported_accepted) / len(accepted) if accepted else 0.0
        )
        evidence_coverage = 100 * len(supported) / len(claims) if claims else 0.0
        baseline = dict(result["metrics"])
        baseline.update(
            {
                "hallucination_proxy_rate": round(hallucination_proxy, 1),
                "accepted_claims": len(accepted),
                "review_claims": sum(
                    claim["status"] == "review" for claim in claims
                ),
                "rejected_claims": sum(
                    claim["status"] == "rejected" for claim in claims
                ),
                "abstained_claims": 0,
                "evidence_id_coverage": round(evidence_coverage, 1),
                "sentence_provenance_coverage": round(evidence_coverage, 1),
                "metric_scope": (
                    "实时召回摘要的工程证据约束指标；不等同于专家核验后的事实准确率。"
                ),
            }
        )
        return baseline

    @staticmethod
    def _live_innovations(result: dict[str, Any]) -> dict[str, Any]:
        papers = result["papers"]
        claims = result["claims"]
        blue_ocean = result["resources"]["blue_ocean"]
        return {
            "knowledge_state": result["report"].get("knowledge_state", {}),
            "discovery": {
                "timeline": [
                    {
                        "year": paper["year"],
                        "paper_id": paper["paper_id"],
                        "milestone": paper["summary"],
                    }
                    for paper in sorted(papers, key=lambda item: item["year"])
                ],
                "controversies": [
                    {
                        "topic": claim["target"],
                        "reason": "模型批判者要求进一步复核。",
                        "claim_id": claim["claim_id"],
                        "evidence_ids": claim["evidence_ids"],
                    }
                    for claim in claims
                    if claim["status"] == "review"
                ],
                "research_gaps": [
                    {
                        "topic": blue_ocean["hypothesis"],
                        "gap_type": "llm_hypothesis_not_fact",
                        "priority": None,
                        "evidence_ids": blue_ocean["evidence_ids"],
                    }
                ],
                "method": "LLM 基于实时召回摘要提出，确定性代码验证来源 ID。",
            },
            "hypotheses": [
                {
                    "candidate_id": "LH01",
                    "hypothesis": blue_ocean["hypothesis"],
                    "score": None,
                    "evidence_ids": blue_ocean["evidence_ids"],
                    "status": "hypothesis_not_fact",
                    "rank": 1,
                    "pairwise_wins": 0,
                }
            ],
            "falsification": {
                "rounds": len(claims),
                "failed": sum(
                    claim["status"] == "rejected" for claim in claims
                ),
                "unresolved": sum(
                    claim["status"] == "review" for claim in claims
                ),
            },
            "debate_view_count": sum(
                len(claim["criticisms"]) for claim in claims
            ),
        }

    def _metrics(
        self,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        claims: list[Claim],
        resources: dict[str, Any],
    ) -> dict[str, Any]:
        accepted = [claim for claim in claims if claim.status == "accepted"]
        unsupported = [claim for claim in accepted if not claim.evidence_ids]
        hallucination_proxy = (
            100 * len(unsupported) / len(accepted) if accepted else 100.0
        )
        adaptation_accuracy = max(
            0,
            100
            - 20
            * abs(
                diagnosis["target_difficulty"] - profile.expected_difficulty
            ),
        )
        covered_text = " ".join(resources["covered_concepts"]).lower()
        covered_count = sum(
            concept.lower() in covered_text for concept in profile.required_concepts
        )
        coverage_rate = (
            100 * covered_count / len(profile.required_concepts)
            if profile.required_concepts
            else 100.0
        )
        valid_evidence_claims = [
            claim
            for claim in claims
            if claim.evidence_ids
            and all(paper_id in self.kb.paper_by_id for paper_id in claim.evidence_ids)
        ]
        evidence_coverage = (
            100 * len(valid_evidence_claims) / len(claims) if claims else 100.0
        )
        provenance_claims = [
            claim for claim in claims if claim.evidence_ids and claim.evidence_spans
        ]
        provenance_coverage = (
            100 * len(provenance_claims) / len(valid_evidence_claims)
            if valid_evidence_claims
            else 0.0
        )
        return {
            "hallucination_proxy_rate": round(hallucination_proxy, 1),
            "adaptation_accuracy": round(adaptation_accuracy, 1),
            "knowledge_coverage_rate": round(coverage_rate, 1),
            "accepted_claims": len(accepted),
            "review_claims": sum(claim.status == "review" for claim in claims),
            "rejected_claims": sum(
                claim.status == "rejected" for claim in claims
            ),
            "abstained_claims": sum(
                claim.status == "abstained" for claim in claims
            ),
            "evidence_id_coverage": round(evidence_coverage, 1),
            "sentence_provenance_coverage": round(provenance_coverage, 1),
            "metric_scope": (
                "离线工程代理指标；正式论文结论仍需独立金标准、领域专家盲审"
                "和统计显著性检验。"
            ),
        }
