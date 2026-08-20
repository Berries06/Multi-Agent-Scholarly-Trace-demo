from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

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
from .models import AgentTrace, LearnerProfile


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
    ) -> dict[str, Any]:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        kb, graph_rag, discovery = self._runtime(domain_id)
        profile = self.profiles[profile_id]
        traces: list[AgentTrace] = []

        diagnosis = self.diagnoser.diagnose(profile, difficulty_adjustment)
        intent = self.intent_agent.perceive(query)
        graph_retrieval = graph_rag.query(query, intent)
        profile_papers = self.retriever.retrieve(
            kb,
            query,
            profile,
            diagnosis,
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

        resources = self.resource_agent.generate(profile, diagnosis, claims, kb)

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
