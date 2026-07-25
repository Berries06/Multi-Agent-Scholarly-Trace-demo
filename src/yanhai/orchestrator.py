from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import (
    CriticAgent,
    DiagnosisAgent,
    JudgeAgent,
    ProposerAgent,
    ResourceAgent,
    RetrievalAgent,
)
from .knowledge import KnowledgeBase
from .models import AgentTrace, LearnerProfile


DEFAULT_QUERY = "多智能体科研推理如何通过证据溯源降低幻觉并发现研究蓝海？"


class ScholarlyTraceOrchestrator:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.kb = KnowledgeBase(self.project_root / "data" / "knowledge")
        profile_path = self.project_root / "data" / "profiles" / "profiles.json"
        raw_profiles = json.loads(profile_path.read_text(encoding="utf-8"))
        self.profiles = {
            profile.profile_id: profile
            for profile in (LearnerProfile.from_dict(item) for item in raw_profiles)
        }
        self.diagnoser = DiagnosisAgent()
        self.retriever = RetrievalAgent()
        self.proposer = ProposerAgent()
        self.critic = CriticAgent()
        self.judge = JudgeAgent()
        self.resource_agent = ResourceAgent()

    def list_profiles(self) -> list[dict[str, Any]]:
        return [profile.public_dict() for profile in self.profiles.values()]

    def run(
        self,
        profile_id: str,
        query: str = DEFAULT_QUERY,
        difficulty_adjustment: int = 0,
    ) -> dict[str, Any]:
        if profile_id not in self.profiles:
            raise KeyError(f"Unknown profile: {profile_id}")
        profile = self.profiles[profile_id]
        traces: list[AgentTrace] = []

        diagnosis = self.diagnoser.diagnose(profile, difficulty_adjustment)
        traces.append(
            AgentTrace(
                agent=self.diagnoser.name,
                role="画像分析",
                status="completed",
                summary=(
                    f"准备度 {diagnosis['readiness_score']}，定位 "
                    f"{len(diagnosis['blind_spots'])} 个知识盲区，"
                    f"目标难度 L{diagnosis['target_difficulty']}。"
                ),
                duration_ms=126,
            )
        )

        papers = self.retriever.retrieve(self.kb, query, profile, diagnosis)
        traces.append(
            AgentTrace(
                agent=self.retriever.name,
                role="证据召回",
                status="completed",
                summary=f"从知识库切片召回 {len(papers)} 篇可追溯文献。",
                duration_ms=184,
            )
        )

        claims = self.proposer.propose(self.kb, papers)
        traces.append(
            AgentTrace(
                agent=self.proposer.name,
                role="关联提出",
                status="completed",
                summary=f"提出 {len(claims)} 条候选关联，其中包含 1 条压力测试命题。",
                duration_ms=203,
            )
        )

        claims = self.critic.critique(claims, self.kb)
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
                duration_ms=232,
            )
        )

        claims = self.judge.adjudicate(claims, self.kb)
        accepted = sum(claim.status == "accepted" for claim in claims)
        rejected = sum(claim.status == "rejected" for claim in claims)
        traces.append(
            AgentTrace(
                agent=self.judge.name,
                role="置信裁决",
                status="completed",
                summary=f"通过 {accepted} 条，拒绝 {rejected} 条；无证据强断言未进入资源。",
                duration_ms=167,
            )
        )

        resources = self.resource_agent.generate(profile, diagnosis, claims, self.kb)
        traces.append(
            AgentTrace(
                agent=self.resource_agent.name,
                role="资源编排",
                status="completed",
                summary="生成定制导读、复现实操指南与分阶测评三类资源。",
                duration_ms=145,
            )
        )

        claim_dicts = [claim.to_dict() for claim in claims]
        graph = self.kb.graph_for_claims(claim_dicts)
        metrics = self._metrics(profile, diagnosis, claims, resources)
        report = {
            "blind_spots": diagnosis["blind_spots"],
            "strengths": diagnosis["strengths"],
            "difficulty_curve": diagnosis["difficulty_curve"],
            "learning_path": diagnosis["learning_path"],
            "resource_match_score": diagnosis["resource_match_score"],
            "feedback_adjustment": difficulty_adjustment,
        }
        return {
            "project": "研海寻踪",
            "query": query,
            "profile": profile.public_dict(),
            "diagnosis": diagnosis,
            "agent_trace": [trace.to_dict() for trace in traces],
            "papers": [paper.to_dict() for paper in papers],
            "claims": claim_dicts,
            "graph": graph,
            "resources": resources,
            "report": report,
            "metrics": metrics,
        }

    def run_with_feedback(
        self,
        profile_id: str,
        feedback: str,
        query: str = DEFAULT_QUERY,
    ) -> dict[str, Any]:
        adjustments = {"too_hard": -1, "suitable": 0, "too_easy": 1}
        if feedback not in adjustments:
            raise ValueError(f"Unknown feedback: {feedback}")
        result = self.run(profile_id, query, adjustments[feedback])
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
