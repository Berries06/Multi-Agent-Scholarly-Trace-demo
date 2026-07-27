from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .config import FeatureFlags, SystemConfig
from .knowledge import KnowledgeBase
from .models import Claim, LearnerProfile, Paper


class DiagnosisTool:
    name = "学情诊断策略"

    def diagnose(self, profile: LearnerProfile, difficulty_adjustment: int = 0) -> dict[str, Any]:
        average = round(mean(profile.knowledge_scores.values()), 1)
        blind_spots = [
            topic
            for topic, score in sorted(profile.knowledge_scores.items(), key=lambda item: item[1])
            if score < 70
        ]
        if average <= 45:
            base_difficulty = 1
        elif average <= 60:
            base_difficulty = 2
        elif average <= 75:
            base_difficulty = 3
        elif average <= 88:
            base_difficulty = 4
        else:
            base_difficulty = 5
        target_difficulty = max(1, min(5, base_difficulty + difficulty_adjustment))
        match_score = max(0, 100 - abs(target_difficulty - profile.expected_difficulty) * 18)
        path = blind_spots[:3] or ["前沿证据综合"]
        path.append("多智能体交叉验证")
        path.append("个性化学习与反馈")
        return {
            "readiness_score": average,
            "blind_spots": blind_spots,
            "strengths": [
                topic for topic, score in profile.knowledge_scores.items() if score >= 75
            ],
            "target_difficulty": target_difficulty,
            "resource_match_score": match_score,
            "difficulty_curve": [
                {"stage": "概念校准", "difficulty": max(1, target_difficulty - 1)},
                {"stage": "证据追踪", "difficulty": target_difficulty},
                {"stage": "博弈推理", "difficulty": min(5, target_difficulty + 1)},
                {"stage": "应用反馈", "difficulty": min(5, target_difficulty + 1)},
            ],
            "learning_path": path,
        }


class RetrievalTool:
    name = "证据检索策略"

    def retrieve(
        self,
        kb: KnowledgeBase,
        query: str,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        *,
        limit: int = 8,
        information_gain: bool = False,
    ) -> list[Paper]:
        return kb.search(
            query,
            profile,
            diagnosis["blind_spots"],
            limit=limit,
            information_gain=information_gain,
        )


class ClaimProposalTool:
    name = "命题生成策略"

    def propose(
        self,
        kb: KnowledgeBase,
        papers: list[Paper],
        *,
        sentence_provenance: bool = False,
    ) -> list[Claim]:
        relations = kb.candidate_relations({paper.paper_id for paper in papers})
        claims = [
            Claim(
                claim_id=f"C{index:03d}",
                source=relation["source"],
                relation=relation["relation"],
                target=relation["target"],
                relation_type=relation["relation_type"],
                base_confidence=float(relation["confidence"]),
                evidence_ids=list(relation["evidence_ids"]),
                evidence_spans=(
                    kb.evidence_spans_for_relation(relation)
                    if sentence_provenance
                    else []
                ),
                counter_evidence_ids=list(relation.get("counter_evidence_ids", [])),
            )
            for index, relation in enumerate(relations, start=1)
        ]
        claims.append(
            Claim(
                claim_id=f"C{len(claims) + 1:03d}",
                source="多智能体辩论",
                relation="guarantees",
                target="零幻觉科研结论",
                relation_type="speculative",
                base_confidence=0.42,
            )
        )
        return claims


class EvidenceCritiqueTool:
    name = "证据批判策略"

    def critique(self, claims: list[Claim], kb: KnowledgeBase) -> list[Claim]:
        for claim in claims:
            invalid_ids = [
                paper_id for paper_id in claim.evidence_ids if paper_id not in kb.paper_by_id
            ]
            if not claim.evidence_ids:
                claim.criticisms.append("缺少可追溯证据，不能进入最终资源。")
            if invalid_ids:
                claim.criticisms.append(f"证据 ID 不存在：{', '.join(invalid_ids)}。")
            if len(claim.evidence_ids) == 1:
                claim.criticisms.append("当前仅有单一来源，需保留外部有效性限制。")
            if claim.relation in {"guarantees", "proves"}:
                claim.criticisms.append("使用绝对化谓词，结论强度超过现有证据。")
            if claim.base_confidence < 0.7:
                claim.criticisms.append("候选置信度低于高保真阈值。")
            if not claim.criticisms:
                claim.criticisms.append("证据与命题结构一致，未发现阻断性问题。")
        return claims


class ResourceBuilder:
    name = "教学资源构建器"

    def generate(
        self,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        claims: list[Claim],
        kb: KnowledgeBase,
        *,
        tournament: list[dict[str, Any]] | None = None,
        discovery: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        accepted = [claim for claim in claims if claim.status == "accepted"]
        citations = sorted({paper_id for claim in accepted for paper_id in claim.evidence_ids})
        difficulty = diagnosis["target_difficulty"]
        explanation = {
            1: "从概念和图示开始，避免一次引入过多术语。",
            2: "先理解角色分工，再观察证据如何改变裁决。",
            3: "结合论文证据比较不同协同机制。",
            4: "重点分析适用条件、反例和实验设计。",
            5: "要求完成可复现实验与方法消融。",
        }[difficulty]
        sections = [
            {
                "heading": f"{claim.source} → {claim.target}",
                "body": (
                    f"现有证据支持“{claim.source}{claim.relation}{claim.target}”。"
                    f"裁判置信度为 {claim.judge_score:.0%}。"
                ),
                "citations": claim.evidence_ids,
            }
            for claim in accepted[:3]
        ]
        guide_steps = [
            {
                "step": 1,
                "title": "建立检索问题",
                "action": f"围绕“{profile.goal}”拆分对象、机制、证据和评价指标。",
            },
            {
                "step": 2,
                "title": "构造证据子图",
                "action": "把论文、方法、结论和支持关系编码成带来源的节点与边。",
            },
            {
                "step": 3,
                "title": "运行博弈裁决",
                "action": "让提出者给出关联，批判者寻找反证，裁判按证据完整性定标。",
            },
            {
                "step": 4,
                "title": "完成消融复现",
                "action": "比较无批判者、无图谱和完整系统的幻觉率与覆盖率。",
            },
        ]
        quiz = [
            {
                "level": "基础",
                "question": "为什么最终命题必须保留 evidence_ids？",
                "options": ["便于改变配色", "支持溯源与复核", "减少前端代码", "替代学习者画像"],
                "answer": 1,
            },
            {
                "level": "应用",
                "question": "批判者发现结论只有单一来源时，最合理的处理是什么？",
                "options": ["直接删除", "无条件接受", "保留限制并寻求交叉证据", "提高模型温度"],
                "answer": 2,
            },
            {
                "level": "挑战",
                "question": "验证博弈机制有效性的首选实验设计是什么？",
                "options": ["只展示成功案例", "与无批判者版本做消融", "增加页面动画", "扩大提示词长度"],
                "answer": 1,
            },
        ]
        covered_concepts = sorted(
            {
                concept
                for claim in accepted
                for concept in (claim.source, claim.target)
            }
        )
        leading_hypothesis = tournament[0] if tournament else None
        blue_ocean = {
            "enabled": leading_hypothesis is not None,
            "hypothesis": (
                leading_hypothesis["hypothesis"] if leading_hypothesis else ""
            ),
            "caveat": (
                "该命题是待验证研究假设，不作为已证实事实进入知识库。"
                if leading_hypothesis
                else "当前问题未触发研究假设生成。"
            ),
            "evidence_ids": (
                leading_hypothesis["evidence_ids"] if leading_hypothesis else []
            ),
            "tournament_score": (
                leading_hypothesis["score"] if leading_hypothesis else None
            ),
        }
        return {
            "briefing": {
                "title": f"{profile.name}的多智能体科研推理导读",
                "level": difficulty,
                "strategy": explanation,
                "sections": sections,
                "citations": citations,
            },
            "practical_guide": {
                "title": "可信科研图谱最小复现实操",
                "estimated_minutes": 35 + 10 * difficulty,
                "steps": guide_steps,
            },
            "quiz": {
                "title": "分阶理解检查",
                "items": quiz[: max(2, min(3, difficulty))],
            },
            "blue_ocean": blue_ocean,
            "discovery_summary": discovery or {},
            "covered_concepts": covered_concepts,
        }


class DiverseDebateTool:
    name = "多视角辩论策略"

    def debate(self, claims: list[Claim], kb: KnowledgeBase) -> list[Claim]:
        for claim in claims:
            valid = [
                paper_id
                for paper_id in claim.evidence_ids
                if paper_id in kb.paper_by_id
            ]
            views = [
                {
                    "perspective": "证据审计员",
                    "stance": "support" if valid else "challenge",
                    "finding": f"定位到 {len(valid)} 个有效来源。",
                },
                {
                    "perspective": "方法论怀疑者",
                    "stance": "challenge" if len(valid) < 2 else "support",
                    "finding": (
                        "单来源不足以排除方法偏差。"
                        if len(valid) < 2
                        else "已具备交叉来源，但仍需真实任务复验。"
                    ),
                },
                {
                    "perspective": "外部有效性审查员",
                    "stance": "challenge",
                    "finding": "论文切片只能支持条件性结论，不能外推为普遍保证。",
                },
            ]
            claim.debate_views.extend(views)
            if len(valid) < 2 and "多视角复核：交叉来源不足。" not in claim.criticisms:
                claim.criticisms.append("多视角复核：交叉来源不足。")
        return claims


class SequentialFalsificationTool:
    name = "序贯反证策略"

    def falsify(
        self,
        claims: list[Claim],
        kb: KnowledgeBase,
        max_rounds: int = 2,
    ) -> list[Claim]:
        for claim in claims:
            valid = [
                paper_id
                for paper_id in claim.evidence_ids
                if paper_id in kb.paper_by_id
            ]
            tests = [
                {
                    "round": 1,
                    "test": "若命题成立，应能定位至少一个支持句及其论文。",
                    "support_ids": valid,
                    "counter_ids": list(claim.counter_evidence_ids),
                    "outcome": (
                        "passed"
                        if claim.evidence_spans and valid
                        else "unresolved"
                    ),
                },
                {
                    "round": 2,
                    "test": "若结论可推广，不应依赖绝对化措辞或未处理反证。",
                    "support_ids": valid,
                    "counter_ids": list(claim.counter_evidence_ids),
                    "outcome": (
                        "failed"
                        if claim.relation in {"guarantees", "proves"}
                        or claim.counter_evidence_ids
                        else "passed"
                    ),
                },
            ]
            claim.falsification_steps.extend(tests[: max(1, max_rounds)])
            if any(step["outcome"] == "failed" for step in claim.falsification_steps):
                claim.criticisms.append("序贯反证发现未通过的可证伪检查。")
        return claims


class KnowledgeTracingTool:
    name = "动态学情追踪策略"

    def trace(
        self,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        feedback: str | None = None,
        *,
        prior_state: dict[str, Any] | None = None,
        concept_feedback: dict[str, Any] | None = None,
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        global_delta = {"too_hard": -0.04, "suitable": 0.03, "too_easy": 0.05}.get(
            feedback, 0.0
        )
        prior_by_concept = {
            str(item.get("concept")): float(item.get("posterior_mastery", 0.5))
            for item in (prior_state or {}).get("concepts", [])
            if isinstance(item, dict) and item.get("concept")
        }
        concept_feedback = concept_feedback or {}
        questionnaire = questionnaire or {}
        concepts = []
        for topic, score in sorted(profile.knowledge_scores.items()):
            prior = prior_by_concept.get(topic, score / 100)
            raw_signal = concept_feedback.get(topic, {})
            if isinstance(raw_signal, (int, float)):
                raw_signal = {"self_rating": raw_signal}
            if not isinstance(raw_signal, dict):
                raw_signal = {}
            concept_delta = 0.0
            if "correct" in raw_signal:
                concept_delta += 0.08 if bool(raw_signal["correct"]) else -0.06
            if "self_rating" in raw_signal:
                rating = max(1.0, min(5.0, float(raw_signal["self_rating"])))
                concept_delta += (rating - 3.0) * 0.02
            posterior = max(
                0.01,
                min(0.99, prior + global_delta + concept_delta),
            )
            concepts.append(
                {
                    "concept": topic,
                    "prior_mastery": round(prior, 3),
                    "posterior_mastery": round(posterior, 3),
                    "uncertainty": round(1 - abs(posterior - 0.5) * 2, 3),
                    "evidence": {
                        "difficulty_feedback": feedback or "profile_prior",
                        "concept_feedback": raw_signal,
                    },
                }
            )
        weakest = min(concepts, key=lambda item: item["posterior_mastery"])
        ratings = [
            float(value)
            for value in questionnaire.values()
            if isinstance(value, (int, float)) and 1 <= float(value) <= 5
        ]
        return {
            "model": "concept-level deterministic demo tracer",
            "concepts": concepts,
            "next_focus": weakest["concept"],
            "target_difficulty": diagnosis["target_difficulty"],
            "questionnaire_score": round(20 * mean(ratings), 1) if ratings else None,
            "warning": (
                "当前状态仅保存在本次结果中；这是概念级反馈 Demo，"
                "接入真实作答历史后再进行统计校准。"
            ),
        }


class TemporalDiscoveryTool:
    name = "时序争议发现策略"

    def analyse(
        self,
        papers: list[Paper],
        claims: list[Claim],
    ) -> dict[str, Any]:
        timeline = [
            {
                "year": paper.year,
                "paper_id": paper.paper_id,
                "milestone": paper.summary,
            }
            for paper in sorted(papers, key=lambda item: (item.year, item.paper_id))
        ]
        target_counts = Counter(claim.target for claim in claims if claim.evidence_ids)
        controversies = [
            {
                "topic": claim.target,
                "reason": (
                    "存在反向证据，需人工复核。"
                    if claim.counter_evidence_ids
                    else "仅有单一来源，跨场景有效性仍不确定。"
                ),
                "claim_id": claim.claim_id,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in claims
            if claim.counter_evidence_ids or len(claim.evidence_ids) == 1
        ]
        gaps = [
            {
                "topic": claim.target,
                "gap_type": (
                    "low_corroboration"
                    if len(claim.evidence_ids) == 1
                    else "cross_domain_validation"
                ),
                "priority": round(
                    min(0.99, 0.45 + 0.15 / max(1, target_counts[claim.target])), 3
                ),
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in claims
            if claim.status in {"accepted", "review"}
        ]
        gaps.sort(key=lambda item: item["priority"], reverse=True)
        return {
            "timeline": timeline,
            "controversies": controversies,
            "research_gaps": gaps[:5],
            "method": "按文献年份、证据数与反证状态进行可复现拓扑启发式分析。",
        }


class HypothesisTournamentTool:
    name = "蓝海假设排序策略"

    def rank(
        self,
        discovery: dict[str, Any],
        claims: list[Claim],
    ) -> list[dict[str, Any]]:
        accepted = [claim for claim in claims if claim.status == "accepted"]
        evidence_ids = sorted(
            {paper_id for claim in accepted for paper_id in claim.evidence_ids}
        )
        gap_topic = (
            discovery.get("research_gaps", [{}])[0].get("topic", "科研发现质量")
            if discovery.get("research_gaps")
            else "科研发现质量"
        )
        candidates = [
            {
                "hypothesis": f"将序贯反证失败率编码为动态图谱边权，可能改善“{gap_topic}”候选的排序。",
                "novelty": 0.86,
                "evidence_strength": min(0.92, 0.52 + 0.05 * len(evidence_ids)),
                "testability": 0.93,
                "uncertainty_value": 0.81,
            },
            {
                "hypothesis": "按学习者概念不确定度调节检索信息增益，可能提高跨学科证据覆盖。",
                "novelty": 0.79,
                "evidence_strength": min(0.88, 0.48 + 0.04 * len(evidence_ids)),
                "testability": 0.88,
                "uncertainty_value": 0.76,
            },
            {
                "hypothesis": "由角色多样性而非智能体数量决定辩论收益，可能降低无效讨论成本。",
                "novelty": 0.75,
                "evidence_strength": min(0.86, 0.5 + 0.04 * len(evidence_ids)),
                "testability": 0.91,
                "uncertainty_value": 0.73,
            },
        ]
        for index, candidate in enumerate(candidates, start=1):
            score = (
                0.30 * candidate["novelty"]
                + 0.25 * candidate["evidence_strength"]
                + 0.30 * candidate["testability"]
                + 0.15 * candidate["uncertainty_value"]
            )
            candidate["candidate_id"] = f"H{index:02d}"
            candidate["score"] = round(score, 3)
            candidate["evidence_ids"] = evidence_ids[:3]
            candidate["status"] = "hypothesis_not_fact"
        candidates.sort(key=lambda item: item["score"], reverse=True)
        for rank, candidate in enumerate(candidates, start=1):
            candidate["rank"] = rank
            candidate["pairwise_wins"] = len(candidates) - rank
        return candidates


class LearnerPlanningAgent:
    """Business Agent 1: diagnose the learner and maintain the learning plan."""

    name = "学情诊断与学习规划 Agent"

    def __init__(self) -> None:
        self._diagnosis = DiagnosisTool()
        self._tracing = KnowledgeTracingTool()

    def plan(
        self,
        profile: LearnerProfile,
        difficulty_adjustment: int = 0,
        *,
        feedback: str | None = None,
        enable_knowledge_tracing: bool = True,
        prior_state: dict[str, Any] | None = None,
        concept_feedback: dict[str, Any] | None = None,
        questionnaire: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnosis = self._diagnosis.diagnose(profile, difficulty_adjustment)
        knowledge_state = (
            self._tracing.trace(
                profile,
                diagnosis,
                feedback,
                prior_state=prior_state,
                concept_feedback=concept_feedback,
                questionnaire=questionnaire,
            )
            if enable_knowledge_tracing
            else {}
        )
        return {
            "diagnosis": diagnosis,
            "knowledge_state": knowledge_state,
            "structured_output": {
                "blind_spots": list(diagnosis["blind_spots"]),
                "target_difficulty": diagnosis["target_difficulty"],
                "learning_path": list(diagnosis["learning_path"]),
                "next_focus": knowledge_state.get("next_focus"),
            },
        }


class EvidenceGraphAgent:
    """Business Agent 2: retrieve evidence and build a grounded subgraph.

    Debate, criticism, falsification and temporal analysis remain internal
    strategies. They are deliberately not exposed as independent Agents.
    """

    name = "证据检索与知识图谱 Agent"

    def __init__(self) -> None:
        self._retrieval = RetrievalTool()
        self._proposal = ClaimProposalTool()
        self._critique = EvidenceCritiqueTool()
        self._debate = DiverseDebateTool()
        self._falsification = SequentialFalsificationTool()
        self._discovery = TemporalDiscoveryTool()
        self._tournament = HypothesisTournamentTool()

    def collect(
        self,
        kb: KnowledgeBase,
        query: str,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        config: SystemConfig,
    ) -> dict[str, Any]:
        flags: FeatureFlags = config.flags
        papers = self._retrieval.retrieve(
            kb,
            query,
            profile,
            diagnosis,
            limit=config.retrieval_limit,
            information_gain=flags.information_gain_retrieval,
        )
        claims = self._proposal.propose(
            kb,
            papers,
            sentence_provenance=flags.sentence_provenance,
        )
        strategies: list[str] = ["local_or_live_retrieval", "claim_proposal"]
        if flags.critic:
            claims = self._critique.critique(claims, kb)
            strategies.append("evidence_critique")
        if flags.diverse_debate:
            claims = self._debate.debate(claims, kb)
            strategies.append("diverse_debate")
        if flags.sequential_falsification:
            claims = self._falsification.falsify(
                claims,
                kb,
                config.max_falsification_rounds,
            )
            strategies.append("sequential_falsification")
        return {"papers": papers, "claims": claims, "strategies": strategies}

    def discover(
        self,
        papers: list[Paper],
        claims: list[Claim],
        config: SystemConfig,
        query: str = "",
    ) -> dict[str, Any]:
        discovery: dict[str, Any] = {}
        hypotheses: list[dict[str, Any]] = []
        if config.flags.temporal_analysis:
            discovery = self._discovery.analyse(papers, claims)
        hypothesis_terms = ("蓝海", "研究空白", "研究假设", "创新方向", "research gap", "hypothesis")
        if config.flags.hypothesis_tournament and any(
            term in query.lower() for term in hypothesis_terms
        ):
            hypotheses = self._tournament.rank(discovery, claims)
        return {"discovery": discovery, "hypotheses": hypotheses}


class PersonalizedTeachingAgent:
    """Business Agent 3: turn admitted evidence into learning resources."""

    name = "个性化教学与反馈 Agent"

    def __init__(self) -> None:
        self._resources = ResourceBuilder()

    @staticmethod
    def feedback_form(next_focus: str | None) -> dict[str, Any]:
        return {
            "version": "demo-v1",
            "scale": {"min": 1, "max": 5},
            "items": [
                {"id": "relevance", "label": "内容与我的学习目标相关"},
                {"id": "difficulty_fit", "label": "内容难度适合当前水平"},
                {"id": "clarity", "label": "解释清楚、容易理解"},
                {"id": "evidence_trust", "label": "来源和证据让我感到可信"},
                {"id": "usefulness", "label": "我知道下一步可以如何行动"},
            ],
            "concept_feedback": {
                "concept": next_focus,
                "label": "本轮重点知识点自评",
                "accepted_fields": ["self_rating", "correct"],
            },
            "note": "Demo 问卷仅更新本次运行中的画像状态，不持久化个人数据。",
        }

    def teach(
        self,
        profile: LearnerProfile,
        diagnosis: dict[str, Any],
        claims: list[Claim],
        kb: KnowledgeBase,
        *,
        knowledge_state: dict[str, Any] | None = None,
        hypotheses: list[dict[str, Any]] | None = None,
        discovery: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resources = self._resources.generate(
            profile,
            diagnosis,
            claims,
            kb,
            tournament=hypotheses,
            discovery=discovery,
        )
        resources["feedback_form"] = self.feedback_form(
            (knowledge_state or {}).get("next_focus")
        )
        return resources
