from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .agents import (
    CriticAgent,
    DiagnosisAgent,
    IntentPerceptionAgent,
    JudgeAgent,
    PaperKnowledgeExtractionAgent,
    ProposerAgent,
    ResourceAgent,
    RetrievalAgent,
)
from .ablation import DecisionAblation
from .discovery import GraphInsightEngine
from .graph_rag import GraphRAGLiteEngine
from .knowledge import KnowledgeBase
from .live_research import LiveResearchService
from .models import AgentTrace, LearnerProfile
from .providers import ProviderConfig, create_provider


DEFAULT_QUERY = "如何从科学论文中抽取可追溯知识图谱，并利用图谱理解技术脉络和生成研究想法？"


class ScholarlyTraceOrchestrator:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        knowledge_root = self.project_root / "data" / "knowledge"
        self.kb = KnowledgeBase(knowledge_root)
        self.default_domain_id = self.kb.default_domain_id
        self.kbs: dict[str, KnowledgeBase] = {
            self.default_domain_id: self.kb,
        }
        self.graph_rag_engines: dict[str, GraphRAGLiteEngine] = {}
        self.discovery_engines: dict[str, GraphInsightEngine] = {}
        profile_path = self.project_root / "data" / "profiles" / "profiles.json"
        raw_profiles = json.loads(profile_path.read_text(encoding="utf-8"))
        self.profiles = {
            profile.profile_id: profile
            for profile in (LearnerProfile.from_dict(item) for item in raw_profiles)
        }
        self.diagnoser = DiagnosisAgent()
        self.intent_agent = IntentPerceptionAgent()
        self.extraction_agent = PaperKnowledgeExtractionAgent()
        self.retriever = RetrievalAgent()
        self.proposer = ProposerAgent()
        self.critic = CriticAgent()
        self.judge = JudgeAgent()
        self.resource_agent = ResourceAgent()
        self.discovery = GraphInsightEngine(self.kb)
        self.graph_rag = GraphRAGLiteEngine(self.kb)
        self.graph_rag_engines[self.default_domain_id] = self.graph_rag
        self.discovery_engines[self.default_domain_id] = self.discovery
        self.ablation = DecisionAblation(self.project_root, self.kb)

    def list_profiles(self) -> list[dict[str, Any]]:
        return [profile.public_dict() for profile in self.profiles.values()]

    def list_domains(self) -> list[dict[str, Any]]:
        domains = []
        for config in self.kb.list_domain_configs():
            domain_id = str(config["domain_id"])
            selected_kb, _, _ = self._runtime(domain_id)
            domains.append(
                {
                    **config,
                    **selected_kb.vertical_corpus.domain,
                }
            )
        return domains

    def _runtime(
        self,
        domain_id: str | None,
    ) -> tuple[KnowledgeBase, GraphRAGLiteEngine, GraphInsightEngine]:
        selected = domain_id or self.default_domain_id
        if selected not in self.kb.domain_configs:
            raise KeyError(f"Unknown domain: {selected}")
        if selected not in self.kbs:
            knowledge_root = self.project_root / "data" / "knowledge"
            self.kbs[selected] = KnowledgeBase(knowledge_root, selected)
        selected_kb = self.kbs[selected]
        self.graph_rag_engines.setdefault(
            selected,
            GraphRAGLiteEngine(selected_kb),
        )
        self.discovery_engines.setdefault(
            selected,
            GraphInsightEngine(selected_kb),
        )
        return (
            selected_kb,
            self.graph_rag_engines[selected],
            self.discovery_engines[selected],
        )

    def query_graph(
        self,
        query: str = DEFAULT_QUERY,
        domain_id: str | None = None,
    ) -> dict[str, Any]:
        kb, graph_rag, _ = self._runtime(domain_id)
        intent = self.intent_agent.perceive(query)
        result = graph_rag.query(query, intent)
        result["domain"] = kb.domain
        return result

    def run(
        self,
        profile_id: str,
        query: str = DEFAULT_QUERY,
        difficulty_adjustment: int = 0,
        domain_id: str | None = None,
        *,
        include_ablation: bool = True,
        on_step: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        kb, graph_rag, discovery = self._runtime(domain_id)
        profile = self.profiles[profile_id]
        traces: list[AgentTrace] = []
        emit = on_step or (lambda step: None)

        diagnosis = self.diagnoser.diagnose(profile, difficulty_adjustment)
        emit(
            {
                "stage": "diagnosis",
                "agent": self.diagnoser.name,
                "role": "学情诊断",
                "status": "completed",
                "summary": (
                    f"准备度 {diagnosis['readiness_score']}，目标难度 "
                    f"L{diagnosis['target_difficulty']}。"
                ),
            }
        )
        intent = self.intent_agent.perceive(query)
        emit(
            {
                "stage": "intent",
                "agent": self.intent_agent.name,
                "role": "意图识别与检索路由",
                "status": "completed",
                "summary": (
                    f"识别为“{intent['label']}”，路由至 {intent['route']}"
                    f"（置信度 {intent['confidence']:.0%}）。"
                ),
            }
        )
        graph_retrieval = graph_rag.query(query, intent)
        emit(
            {
                "stage": "graph_retrieval",
                "agent": "GraphRAGLiteEngine",
                "role": "意图驱动图检索",
                "status": "completed",
                "summary": (
                    f"沿 {intent['route']} 检索，召回 "
                    f"{len(graph_retrieval['recommended_papers'])} 篇推荐论文。"
                ),
            }
        )
        profile_papers = self.retriever.retrieve(
            kb,
            query,
            profile,
            diagnosis,
        )
        emit(
            {
                "stage": "retrieval",
                "agent": self.retriever.name,
                "role": "证据检索",
                "status": "completed",
                "summary": f"证据检索完成，命中 {len(profile_papers)} 篇候选论文。",
            }
        )
        graph_paper_ids = [
            item["paper_id"]
            for item in graph_retrieval["recommended_papers"]
        ]
        ordered_paper_ids = [
            *graph_paper_ids,
            *(paper.paper_id for paper in profile_papers),
        ]
        papers = []
        seen_paper_ids: set[str] = set()
        for paper_id in ordered_paper_ids:
            if paper_id in seen_paper_ids or paper_id not in kb.paper_by_id:
                continue
            seen_paper_ids.add(paper_id)
            papers.append(kb.paper_by_id[paper_id])
            if len(papers) >= 8:
                break
        extraction = self.extraction_agent.inspect_index(kb, papers)
        emit(
            {
                "stage": "extraction",
                "agent": self.extraction_agent.name,
                "role": "论文解析与知识建图",
                "status": extraction["status"],
                "summary": (
                    f"复用版本化索引：{extraction['input_papers']} 篇论文、"
                    f"{extraction['evidence_spans']} 条证据跨度、"
                    f"{extraction['knowledge_concepts']} 个知识概念。"
                ),
            }
        )

        started = time.perf_counter()
        claims = self.proposer.propose(kb, papers)
        proposer_ms = (time.perf_counter() - started) * 1000
        traces.append(
            AgentTrace(
                agent=self.proposer.name,
                role="关联提出",
                status="completed",
                summary=(
                    f"从抽取图谱生成 {len(claims) - 1} 条候选关系，并加入 "
                    "1 条无证据压力测试命题。"
                ),
                duration_ms=round(proposer_ms, 2),
            )
        )
        emit(traces[-1].to_dict())

        started = time.perf_counter()
        claims = self.critic.critique(claims, kb)
        critic_ms = (time.perf_counter() - started) * 1000
        flagged = sum(
            1
            for claim in claims
            if any("缺少" in note or "绝对化" in note for note in claim.criticisms)
        )
        traces.append(
            AgentTrace(
                agent=self.critic.name,
                role="反证与约束",
                status="completed",
                summary=f"完成证据交叉检查，标记 {flagged} 条高风险命题。",
                duration_ms=round(critic_ms, 2),
            )
        )
        emit(traces[-1].to_dict())

        started = time.perf_counter()
        claims = self.judge.adjudicate(claims, kb)
        judge_ms = (time.perf_counter() - started) * 1000
        accepted = sum(claim.status == "accepted" for claim in claims)
        rejected = sum(claim.status == "rejected" for claim in claims)
        traces.append(
            AgentTrace(
                agent=self.judge.name,
                role="置信裁决",
                status="completed",
                summary=f"通过 {accepted} 条，拒绝 {rejected} 条；无证据强断言未进入资源。",
                duration_ms=round(judge_ms, 2),
            )
        )
        emit(traces[-1].to_dict())

        resources = self.resource_agent.generate(profile, diagnosis, claims, kb)
        emit(
            {
                "stage": "resources",
                "agent": self.resource_agent.name,
                "role": "个性化资源",
                "status": "completed",
                "summary": "依据已接收图谱关系生成导读、实操和测评。",
            }
        )

        claim_dicts = [claim.to_dict() for claim in claims]
        graph = kb.graph_for_claims(claim_dicts)
        knowledge_graph = kb.extracted_paper_graph()
        graph_insights = discovery.analyze(query)
        metrics = self._metrics(profile, diagnosis, claims, resources)
        report = {
            "blind_spots": diagnosis["blind_spots"],
            "strengths": diagnosis["strengths"],
            "difficulty_curve": diagnosis["difficulty_curve"],
            "learning_path": diagnosis["learning_path"],
            "resource_match_score": diagnosis["resource_match_score"],
            "feedback_adjustment": difficulty_adjustment,
        }
        result = {
            "run_id": uuid.uuid4().hex,
            "project": "研海寻踪",
            "domain": kb.domain,
            "query": query,
            "profile": profile.public_dict(),
            "diagnosis": diagnosis,
            "agent_trace": [trace.to_dict() for trace in traces],
            "specialist_agent_trace": [
                {
                    "agent": self.extraction_agent.name,
                    "role": "论文解析与知识建图",
                    "status": extraction["status"],
                    "summary": (
                        f"复用版本化索引：{extraction['input_papers']} 篇论文、"
                        f"{extraction['evidence_spans']} 条证据跨度、"
                        f"{extraction['knowledge_concepts']} 个知识概念。"
                    ),
                    "details": extraction,
                },
                {
                    "agent": self.intent_agent.name,
                    "role": "意图识别与检索路由",
                    "status": "completed",
                    "summary": (
                        f"识别为“{intent['label']}”，路由至 "
                        f"{intent['route']}（置信度 {intent['confidence']:.0%}）。"
                    ),
                    "details": intent,
                },
            ],
            "service_trace": [
                {
                    "service": "学习者画像服务",
                    "summary": (
                        f"准备度 {diagnosis['readiness_score']}，目标难度 "
                        f"L{diagnosis['target_difficulty']}。"
                    ),
                },
                {
                    "service": "意图驱动图检索服务",
                    "summary": (
                        f"在“{kb.domain['domain_name']}”切片执行 "
                        f"{intent['route']}，访问 "
                        f"{graph_retrieval['retrieval_plan']['visited_concepts']} "
                        f"个知识概念并召回 {len(papers)} 篇论文。"
                    ),
                },
                {
                    "service": "个性化资源服务",
                    "summary": "依据已接收图谱关系生成导读、实操和测评。",
                },
            ],
            "core_method": {
                "agent_count": 3,
                "agents": ["提出者", "批判者", "裁判"],
                "system_agent_count": 5,
                "specialist_agents": ["论文知识抽取", "用户意图感知"],
                "decision_objective": (
                    "在 accepted precision 与 evidence coverage 约束下最大化 VTY。"
                ),
                "current_provider": "schema-guided-pattern + deterministic evidence judge",
                "planned_provider": (
                    "GLiNER/GLiREL 或 OneKE 候选 + 科学主张验证器 + 校准裁判"
                ),
            },
            "papers": [paper.to_dict() for paper in papers],
            "claims": claim_dicts,
            "graph": graph,
            "knowledge_graph": knowledge_graph,
            "graph_insights": graph_insights,
            "graph_retrieval": graph_retrieval,
            "assistant_response": graph_retrieval["answer"],
            "evidence_details": {
                claim.claim_id: kb.evidence_details(claim.evidence_ids)
                for claim in claims
            },
            "resources": resources,
            "report": report,
            "metrics": metrics,
        }
        if include_ablation:
            result["ablation"] = self.ablation.run()
        return result

    def run_with_provider(
        self,
        profile_id: str,
        query: str = DEFAULT_QUERY,
        domain_id: str | None = None,
        provider_config: ProviderConfig | None = None,
    ) -> dict[str, Any]:
        """运行确定性的离线基线，或走实时、证据支撑的 LLM 路径。

        当未提供 ``provider_config`` 或 ``provider == "mock"`` 时，结果为保留的
        确定性流水线，并带 ``offline_mock`` 的 ``provider_run`` 标记。否则针对所选
        领域知识库创建 ``LiveResearchService``，用其证据支撑的回答替换基线回答，
        同时保留确定性的 report、metrics 与 ablation。
        """
        result = self.run(profile_id, query, 0, domain_id=domain_id)
        if provider_config is None or provider_config.provider == "mock":
            public = (
                provider_config.public_dict()
                if provider_config is not None
                else {"provider": "mock", "provider_label": "离线规则引擎", "model": "deterministic"}
            )
            result["provider_run"] = {
                **public,
                "mode": "offline_mock",
                "source_mode": "local_mock",
                "source_counts": {
                    "local_knowledge_base": len(result["papers"]),
                },
                "selected_paper_count": len(result["papers"]),
                "calls": [],
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "llm_duration_ms": 0.0,
                "retrieval_duration_ms": 0.0,
                "warnings": [],
                "api_key_persisted": False,
            }
            result["mock_baseline"] = {
                "domain": (
                    result["domain"]["domain_id"]
                    if isinstance(result["domain"], dict)
                    else str(result["domain"])
                ),
                "paper_count": len(result["papers"]),
                "claim_count": len(result["claims"]),
            }
            return result

        provider = create_provider(provider_config)
        kb, _, _ = self._runtime(domain_id)
        service = LiveResearchService(provider, provider_config, kb)
        active_profile = self.profiles[profile_id]
        live = service.run(query, active_profile, result["diagnosis"])
        baseline_summary = {
            "domain": (
                result["domain"]["domain_id"]
                if isinstance(result["domain"], dict)
                else str(result["domain"])
            ),
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
            }
        )
        result["agent_trace"] = self._live_trace(
            result["agent_trace"],
            live["provider_run"],
            len(live["papers"]),
            len(live["claims"]),
        )
        result["metrics"] = self._live_metrics(result)
        return result

    @staticmethod
    def _live_trace(
        baseline_trace: list[dict[str, Any]],
        provider_run: dict[str, Any],
        paper_count: int,
        claim_count: int,
    ) -> list[dict[str, Any]]:
        learner = (
            dict(baseline_trace[0])
            if baseline_trace
            else {
                "agent": "学情诊断与学习规划 Agent",
                "role": "学情诊断与学习规划",
                "status": "completed",
                "summary": "已形成结构化学习计划。",
            }
        )
        calls = provider_run.get("calls", [])
        call_by_role = {str(call.get("role")): call for call in calls}
        evidence_duration = provider_run.get("retrieval_duration_ms", 0.0)
        for role in ("检索规划", "证据提出"):
            evidence_duration += float(
                call_by_role.get(role, {}).get("duration_ms", 0.0)
            )
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

    @classmethod
    def _live_metrics(cls, result: dict[str, Any]) -> dict[str, Any]:
        claims = result["claims"]
        accepted = [claim for claim in claims if claim.get("status") == "accepted"]
        unsupported = [
            claim
            for claim in accepted
            if not claim.get("evidence_ids") or not claim.get("evidence_spans")
        ]
        hallucination_proxy = (
            100 * len(unsupported) / len(accepted) if accepted else 100.0
        )
        supported = [
            claim
            for claim in claims
            if claim.get("evidence_ids") and claim.get("evidence_spans")
        ]
        evidence_coverage = 100 * len(supported) / len(claims) if claims else 0.0
        baseline = dict(result["metrics"])
        baseline.update(
            {
                "hallucination_proxy_rate": round(hallucination_proxy, 1),
                "adaptation_accuracy": baseline.get("adaptation_accuracy", 0.0),
                "knowledge_coverage_rate": baseline.get("knowledge_coverage_rate", 0.0),
                "accepted_claims": sum(
                    claim.get("status") == "accepted" for claim in claims
                ),
                "review_claims": sum(
                    claim.get("status") == "review" for claim in claims
                ),
                "rejected_claims": sum(
                    claim.get("status") == "rejected" for claim in claims
                ),
                "abstained_claims": sum(
                    claim.get("status") == "abstained" for claim in claims
                ),
                "evidence_id_coverage": round(evidence_coverage, 1),
                "sentence_provenance_coverage": round(evidence_coverage, 1),
                "metric_scope": (
                    "实时 LLM 摘要上的工程代理指标；证据风险不是人工核验后的真实幻觉率。"
                ),
            }
        )
        return baseline

    def run_with_feedback(
        self,
        profile_id: str,
        feedback: str,
        query: str = DEFAULT_QUERY,
        domain_id: str | None = None,
        *,
        include_ablation: bool = True,
    ) -> dict[str, Any]:
        adjustments = {"too_hard": -1, "suitable": 0, "too_easy": 1}
        if feedback not in adjustments:
            raise ValueError(f"Unknown feedback: {feedback}")
        result = self.run(
            profile_id,
            query,
            adjustments[feedback],
            domain_id,
            include_ablation=include_ablation,
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
        claims: list[Any],
        resources: dict[str, Any],
    ) -> dict[str, Any]:
        accepted = [claim for claim in claims if claim.status == "accepted"]
        unsupported = [claim for claim in accepted if not claim.evidence_ids]
        hallucination_proxy = 100 * len(unsupported) / len(accepted) if accepted else 100.0
        adaptation_accuracy = max(
            0,
            100 - 20 * abs(diagnosis["target_difficulty"] - profile.expected_difficulty),
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
        return {
            "hallucination_proxy_rate": round(hallucination_proxy, 1),
            "adaptation_accuracy": round(adaptation_accuracy, 1),
            "knowledge_coverage_rate": round(coverage_rate, 1),
            "accepted_claims": len(accepted),
            "rejected_claims": sum(claim.status == "rejected" for claim in claims),
            "metric_scope": "基础版工程代理指标，正式值需领域专家盲审。",
        }
