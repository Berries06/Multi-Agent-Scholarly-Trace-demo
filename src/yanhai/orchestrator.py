from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import (
    CriticAgent,
    DiagnosisAgent,
    DiverseDebateAgent,
    HypothesisTournamentAgent,
    JudgeAgent,
    KnowledgeTracingAgent,
    ProposerAgent,
    ResourceAgent,
    RetrievalAgent,
    SequentialFalsificationAgent,
    TemporalDiscoveryAgent,
)
from .config import LEGACY, SystemConfig, get_preset
from .knowledge import KnowledgeBase
from .models import AgentTrace, Claim, LearnerProfile
from .probes import PerformanceProbe


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
        self.diagnoser = DiagnosisAgent()
        self.knowledge_tracer = KnowledgeTracingAgent()
        self.retriever = RetrievalAgent()
        self.proposer = ProposerAgent()
        self.critic = CriticAgent()
        self.debate_agent = DiverseDebateAgent()
        self.falsifier = SequentialFalsificationAgent()
        self.judge = JudgeAgent()
        self.discovery_agent = TemporalDiscoveryAgent()
        self.tournament_agent = HypothesisTournamentAgent()
        self.resource_agent = ResourceAgent()

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
    ) -> dict[str, Any]:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        active = self._resolve_config(config) if config is not None else self.config
        flags = active.flags
        profile = self.profiles[profile_id]
        probe = PerformanceProbe(flags.performance_probes)
        traces: list[AgentTrace] = []

        with probe.measure("diagnosis"):
            diagnosis = self.diagnoser.diagnose(profile, difficulty_adjustment)
        self._trace(
            traces,
            probe,
            "diagnosis",
            self.diagnoser.name,
            "画像分析",
            (
                f"准备度 {diagnosis['readiness_score']}，定位 "
                f"{len(diagnosis['blind_spots'])} 个知识盲区，"
                f"目标难度 L{diagnosis['target_difficulty']}。"
            ),
            input_count=len(profile.knowledge_scores),
            output_count=len(diagnosis["blind_spots"]),
        )

        knowledge_state: dict[str, Any] = {}
        if flags.knowledge_tracing:
            with probe.measure("knowledge_tracing"):
                knowledge_state = self.knowledge_tracer.trace(
                    profile, diagnosis, feedback
                )
            self._trace(
                traces,
                probe,
                "knowledge_tracing",
                self.knowledge_tracer.name,
                "掌握度更新",
                (
                    f"更新 {len(knowledge_state['concepts'])} 个概念掌握度，"
                    f"下一焦点为“{knowledge_state['next_focus']}”。"
                ),
                input_count=len(profile.knowledge_scores),
                output_count=len(knowledge_state["concepts"]),
            )

        with probe.measure("retrieval"):
            papers = self.retriever.retrieve(
                self.kb,
                query,
                profile,
                diagnosis,
                limit=active.retrieval_limit,
                information_gain=flags.information_gain_retrieval,
            )
        self._trace(
            traces,
            probe,
            "retrieval",
            self.retriever.name,
            "证据召回",
            f"从知识库切片召回 {len(papers)} 篇可追溯文献。",
            input_count=len(self.kb.papers),
            output_count=len(papers),
        )

        with probe.measure("proposal"):
            claims = self.proposer.propose(
                self.kb,
                papers,
                sentence_provenance=flags.sentence_provenance,
            )
        self._trace(
            traces,
            probe,
            "proposal",
            self.proposer.name,
            "关联提出",
            f"提出 {len(claims)} 条原子命题，其中包含 1 条压力测试命题。",
            input_count=len(papers),
            output_count=len(claims),
        )

        if flags.critic:
            with probe.measure("critique"):
                claims = self.critic.critique(claims, self.kb)
            flagged = sum(
                1
                for claim in claims
                if any(
                    "缺少" in note or "绝对化" in note
                    for note in claim.criticisms
                )
            )
            self._trace(
                traces,
                probe,
                "critique",
                self.critic.name,
                "反证与约束",
                f"完成证据交叉检查，标记 {flagged} 条高风险命题。",
                input_count=len(claims),
                output_count=flagged,
            )

        if flags.diverse_debate:
            with probe.measure("diverse_debate"):
                claims = self.debate_agent.debate(claims, self.kb)
            challenge_count = sum(
                view["stance"] == "challenge"
                for claim in claims
                for view in claim.debate_views
            )
            self._trace(
                traces,
                probe,
                "diverse_debate",
                self.debate_agent.name,
                "多视角博弈",
                f"从证据、方法与外部有效性三种视角提出 {challenge_count} 次质询。",
                input_count=len(claims),
                output_count=3 * len(claims),
            )

        if flags.sequential_falsification:
            with probe.measure("falsification"):
                claims = self.falsifier.falsify(
                    claims, self.kb, active.max_falsification_rounds
                )
            failed = sum(
                step["outcome"] == "failed"
                for claim in claims
                for step in claim.falsification_steps
            )
            unresolved = sum(
                step["outcome"] == "unresolved"
                for claim in claims
                for step in claim.falsification_steps
            )
            self._trace(
                traces,
                probe,
                "falsification",
                self.falsifier.name,
                "序贯可证伪检查",
                f"执行 {sum(len(c.falsification_steps) for c in claims)} 轮检查，"
                f"失败 {failed}、证据不足 {unresolved}。",
                input_count=len(claims),
                output_count=failed + unresolved,
            )

        if flags.judge:
            with probe.measure("judgement"):
                claims = self.judge.adjudicate(
                    claims,
                    self.kb,
                    acceptance_threshold=active.acceptance_threshold,
                    review_threshold=active.review_threshold,
                    calibrated=flags.calibrated_judge,
                    abstention=flags.abstention,
                )
        else:
            with probe.measure("judgement_bypass"):
                for claim in claims:
                    claim.judge_score = claim.base_confidence
                    claim.status = "accepted"
        accepted = sum(claim.status == "accepted" for claim in claims)
        rejected = sum(claim.status == "rejected" for claim in claims)
        abstained = sum(claim.status == "abstained" for claim in claims)
        if flags.judge:
            self._trace(
                traces,
                probe,
                "judgement",
                self.judge.name,
                "置信裁决",
                (
                    f"通过 {accepted} 条，拒绝 {rejected} 条，拒答 {abstained} 条；"
                    "无证据强断言未进入资源。"
                ),
                input_count=len(claims),
                output_count=accepted,
            )

        discovery: dict[str, Any] = {}
        if flags.temporal_analysis:
            with probe.measure("temporal_discovery"):
                discovery = self.discovery_agent.analyse(papers, claims)
            self._trace(
                traces,
                probe,
                "temporal_discovery",
                self.discovery_agent.name,
                "演化、争议与空白",
                (
                    f"形成 {len(discovery['timeline'])} 个时序里程碑、"
                    f"{len(discovery['controversies'])} 个争议点和 "
                    f"{len(discovery['research_gaps'])} 个研究空白。"
                ),
                input_count=len(papers) + len(claims),
                output_count=len(discovery["research_gaps"]),
            )

        hypotheses: list[dict[str, Any]] = []
        if flags.hypothesis_tournament:
            with probe.measure("hypothesis_tournament"):
                hypotheses = self.tournament_agent.rank(discovery, claims)
            self._trace(
                traces,
                probe,
                "hypothesis_tournament",
                self.tournament_agent.name,
                "假设锦标赛",
                f"对 {len(hypotheses)} 条待验证假设进行可检验性与证据强度排序。",
                input_count=len(claims),
                output_count=len(hypotheses),
            )

        with probe.measure("resource_generation"):
            resources = self.resource_agent.generate(
                profile,
                diagnosis,
                claims,
                self.kb,
                tournament=hypotheses,
                discovery=discovery,
            )
        self._trace(
            traces,
            probe,
            "resource_generation",
            self.resource_agent.name,
            "资源编排",
            "生成定制导读、复现实操指南与分阶测评三类资源。",
            input_count=accepted,
            output_count=3,
        )

        with probe.measure("graph_construction"):
            claim_dicts = [claim.to_dict() for claim in claims]
            graph = self.kb.graph_for_claims(
                claim_dicts,
                include_provenance=flags.sentence_provenance,
            )
        metrics = self._metrics(profile, diagnosis, claims, resources)
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
