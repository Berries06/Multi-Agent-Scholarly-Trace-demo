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
from .storage import LocalPaperLibrary


DEFAULT_QUERY = "多智能体科研推理如何通过证据溯源降低幻觉？"


class ScholarlyTraceOrchestrator:
    """Dependency-free research pipeline with isolated experimental switches."""

    def __init__(
        self,
        project_root: Path | None = None,
        config: SystemConfig | str | None = None,
        repository: Any | None = None,
    ) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.config = self._resolve_config(config) if config is not None else LEGACY
        self.repository = repository
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
        profile_override: LearnerProfile | None = None,
        prior_knowledge_state: dict[str, Any] | None = None,
        concept_feedback: dict[str, Any] | None = None,
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if profile_override is None and profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        active = self._resolve_config(config) if config is not None else self.config
        flags = active.flags
        profile = profile_override or self.profiles[profile_id]
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
                query,
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
        diagnosis["resource_match_score"] = metrics["adaptation_accuracy"]
        quality_assessment = self.quality_gate.evaluate_result(
            quality_assessment,
            profile,
            diagnosis,
            claims,
            resources,
            questionnaire,
            metrics,
        )
        report = {
            "blind_spots": diagnosis["blind_spots"],
            "strengths": diagnosis["strengths"],
            "difficulty_curve": diagnosis["difficulty_curve"],
            "learning_path": diagnosis["learning_path"],
            "resource_match_score": metrics["adaptation_accuracy"],
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
        profile_override: LearnerProfile | None = None,
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
            profile_override=profile_override,
            prior_knowledge_state=prior_knowledge_state,
            concept_feedback=concept_feedback,
            questionnaire=questionnaire,
        )
        if provider_config.provider == "mock":
            result["provider_run"] = {
                **provider_config.public_dict(),
                "mode": "offline_mock",
                "source_mode": "local_mock",
                "source_counts": {"local_knowledge_base": len(result["papers"])},
                "selected_paper_count": len(result["papers"]),
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
            local_library=(
                LocalPaperLibrary(self.repository)
                if self.repository is not None
                else None
            ),
        )
        active_profile = profile_override or self.profiles[profile_id]
        live = service.run(
            query,
            active_profile,
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
        hypothesis_terms = (
            "蓝海",
            "研究空白",
            "研究假设",
            "创新方向",
            "research gap",
            "hypothesis",
        )
        hypothesis_enabled = bool(
            result["system_config"]["flags"].get("hypothesis_tournament")
            and any(term in query.lower() for term in hypothesis_terms)
        )
        blue_ocean = result["resources"].setdefault("blue_ocean", {})
        blue_ocean["enabled"] = hypothesis_enabled
        if not hypothesis_enabled:
            blue_ocean.update(
                {
                    "hypothesis": "",
                    "caveat": "当前问题未触发研究假设生成。",
                    "evidence_ids": [],
                    "tournament_score": None,
                }
            )
        result["agent_trace"] = self._live_trace(
            result["agent_trace"],
            live["provider_run"],
            len(live["papers"]),
            len(live["claims"]),
        )
        result["metrics"] = self._live_metrics(result)
        result["diagnosis"]["resource_match_score"] = result["metrics"]["adaptation_accuracy"]
        result["report"]["resource_match_score"] = result["metrics"]["adaptation_accuracy"]
        quality_scores = result["quality_assessment"]["scores"]
        quality_scores["profile_fit"] = result["metrics"]["adaptation_accuracy"]
        quality_scores["knowledge_coverage"] = result["metrics"]["knowledge_coverage_rate"]
        feedback_score = quality_scores.get("user_feedback")
        if feedback_score is None:
            quality_scores["overall_quality"] = round(
                0.5 * quality_scores.get("evidence_grounding", 0.0)
                + 0.3 * quality_scores["profile_fit"]
                + 0.2 * quality_scores["knowledge_coverage"],
                1,
            )
        else:
            quality_scores["overall_quality"] = round(
                0.35 * quality_scores.get("evidence_grounding", 0.0)
                + 0.25 * quality_scores["profile_fit"]
                + 0.20 * quality_scores["knowledge_coverage"]
                + 0.20 * float(feedback_score),
                1,
            )
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
    def _evidence_risk_metrics(claims: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
        admitted = [
            claim for claim in claims if claim.get("status") in {"accepted", "review"}
        ]
        if not admitted:
            return 100.0, {
                "assessed_claims": 0,
                "single_source_claims": 0,
                "review_claims": 0,
                "unsupported_claims": 0,
                "formula": "对进入回答或待复核的命题，综合来源数量、置信度、强断言和批判意见估计残余证据风险。",
            }
        risk_values: list[float] = []
        single_source = 0
        unsupported = 0
        review_count = 0
        for claim in admitted:
            evidence_count = len(claim.get("evidence_ids", []))
            score = float(claim.get("judge_score", 0.0))
            relation = str(claim.get("relation", "")).lower()
            criticism_text = " ".join(claim.get("criticisms", []))
            if evidence_count == 0:
                risk = 0.70
                unsupported += 1
            elif evidence_count == 1:
                risk = 0.18
                single_source += 1
            else:
                risk = 0.04
            if not claim.get("evidence_spans"):
                risk += 0.08
            risk += 0.25 * max(0.0, 1.0 - score)
            if claim.get("status") == "review":
                risk += 0.20
                review_count += 1
            if relation in {"guarantees", "proves", "必然", "保证", "证明"}:
                risk += 0.20
            if any(
                marker in criticism_text
                for marker in ("缺少", "单一", "绝对", "低于", "反证", "不足", "不确定")
            ):
                risk += 0.08
            risk_values.append(min(1.0, risk))
        rate = 100 * sum(risk_values) / len(risk_values)
        return round(rate, 1), {
            "assessed_claims": len(admitted),
            "single_source_claims": single_source,
            "review_claims": review_count,
            "unsupported_claims": unsupported,
            "formula": "对进入回答或待复核的命题，综合来源数量、置信度、强断言和批判意见估计残余证据风险。",
        }

    @staticmethod
    def _personalization_metrics(
        profile: dict[str, Any],
        diagnosis: dict[str, Any],
        resources: dict[str, Any],
    ) -> tuple[float, float, dict[str, Any]]:
        blind_spots = list(diagnosis.get("blind_spots", []))
        required = list(profile.get("required_concepts", []))
        expected_concepts = list(dict.fromkeys(required + blind_spots))
        resource_text = json.dumps(resources, ensure_ascii=False).lower()
        covered = [
            concept
            for concept in expected_concepts
            if str(concept).lower() in resource_text
        ]
        coverage = (
            100 * len(covered) / len(expected_concepts)
            if expected_concepts
            else 100.0
        )
        expected_difficulty = int(profile.get("expected_difficulty", 3))
        target_difficulty = int(diagnosis.get("target_difficulty", 3))
        difficulty_fit = max(
            0.0,
            100.0 - 25.0 * abs(target_difficulty - expected_difficulty),
        )
        covered_blind_spots = [
            concept for concept in blind_spots if str(concept).lower() in resource_text
        ]
        blind_spot_fit = (
            100 * len(covered_blind_spots) / len(blind_spots)
            if blind_spots
            else 100.0
        )
        interests = list(profile.get("interests", []))
        goal = str(profile.get("goal", "")).strip().lower()
        if goal and goal in resource_text:
            goal_alignment = 100.0
        elif interests:
            goal_alignment = 100 * sum(
                str(item).lower() in resource_text for item in interests
            ) / len(interests)
        else:
            goal_alignment = 100.0
        adaptation = (
            0.45 * difficulty_fit
            + 0.30 * blind_spot_fit
            + 0.25 * goal_alignment
        )
        details = {
            "difficulty_fit": round(difficulty_fit, 1),
            "blind_spot_fit": round(blind_spot_fit, 1),
            "goal_alignment": round(goal_alignment, 1),
            "covered_concepts": covered,
            "expected_concepts": expected_concepts,
            "coverage_numerator": len(covered),
            "coverage_denominator": len(expected_concepts),
            "adaptation_formula": "难度匹配 45% + 薄弱点响应 30% + 学习目标相关性 25%。",
            "coverage_formula": "本轮资源实际覆盖的概念 / 画像必需概念与薄弱概念的并集。",
        }
        return round(adaptation, 1), round(coverage, 1), details

    @classmethod
    def _live_metrics(cls, result: dict[str, Any]) -> dict[str, Any]:
        claims = result["claims"]
        risk_rate, _ = cls._evidence_risk_metrics(claims)
        adaptation, coverage, _ = cls._personalization_metrics(
            result["profile"],
            result["diagnosis"],
            result["resources"],
        )
        supported = [
            claim
            for claim in claims
            if claim["evidence_ids"] and claim["evidence_spans"]
        ]
        evidence_coverage = 100 * len(supported) / len(claims) if claims else 0.0
        baseline = dict(result["metrics"])
        baseline.update(
            {
                "hallucination_proxy_rate": risk_rate,
                "adaptation_accuracy": adaptation,
                "knowledge_coverage_rate": coverage,
                "accepted_claims": sum(
                    claim["status"] == "accepted" for claim in claims
                ),
                "review_claims": sum(claim["status"] == "review" for claim in claims),
                "rejected_claims": sum(
                    claim["status"] == "rejected" for claim in claims
                ),
                "abstained_claims": sum(
                    claim["status"] == "abstained" for claim in claims
                ),
                "evidence_id_coverage": round(evidence_coverage, 1),
                "sentence_provenance_coverage": round(evidence_coverage, 1),
                "metric_scope": (
                    "实时摘要上的工程风险与匹配指标；证据风险不是人工核验后的真实幻觉率。"
                ),
            }
        )
        return baseline
    @staticmethod
    def _live_innovations(result: dict[str, Any]) -> dict[str, Any]:
        papers = result["papers"]
        claims = result["claims"]
        blue_ocean = result["resources"]["blue_ocean"]
        hypothesis_enabled = bool(blue_ocean.get("enabled"))
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
                "research_gaps": (
                    [
                        {
                            "topic": blue_ocean["hypothesis"],
                            "gap_type": "llm_hypothesis_not_fact",
                            "priority": None,
                            "evidence_ids": blue_ocean["evidence_ids"],
                        }
                    ]
                    if hypothesis_enabled
                    else []
                ),
                "method": "LLM 基于实时召回摘要提出，确定性代码验证来源 ID。",
            },
            "hypotheses": (
                [
                    {
                        "candidate_id": "LH01",
                        "hypothesis": blue_ocean["hypothesis"],
                        "score": None,
                        "evidence_ids": blue_ocean["evidence_ids"],
                        "status": "hypothesis_not_fact",
                        "rank": 1,
                        "pairwise_wins": 0,
                    }
                ]
                if hypothesis_enabled
                else []
            ),
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
        claim_dicts = [claim.to_dict() for claim in claims]
        risk_rate, _ = self._evidence_risk_metrics(claim_dicts)
        adaptation, coverage, _ = self._personalization_metrics(
            profile.public_dict(),
            diagnosis,
            resources,
        )
        accepted = [claim for claim in claims if claim.status == "accepted"]
        valid_evidence_claims = [
            claim
            for claim in claims
            if claim.evidence_ids
            and all(paper_id in self.kb.paper_by_id for paper_id in claim.evidence_ids)
        ]
        evidence_coverage = (
            100 * len(valid_evidence_claims) / len(claims) if claims else 0.0
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
            "hallucination_proxy_rate": risk_rate,
            "adaptation_accuracy": adaptation,
            "knowledge_coverage_rate": coverage,
            "accepted_claims": len(accepted),
            "review_claims": sum(claim.status == "review" for claim in claims),
            "rejected_claims": sum(claim.status == "rejected" for claim in claims),
            "abstained_claims": sum(claim.status == "abstained" for claim in claims),
            "evidence_id_coverage": round(evidence_coverage, 1),
            "sentence_provenance_coverage": round(provenance_coverage, 1),
            "metric_scope": (
                "离线工程风险与匹配指标；证据风险不是人工核验后的真实幻觉率，"
                "正式结论仍需独立金标准和专家盲审。"
            ),
        }
