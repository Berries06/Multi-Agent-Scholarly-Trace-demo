from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.live_research import LiveResearchService  # noqa: E402
from yanhai.models import LearnerProfile, Paper  # noqa: E402
from yanhai.providers import LLMResponse, ProviderConfig  # noqa: E402


class StubProvider:
    def __init__(self) -> None:
        self.responses = [
            {
                "search_queries": ["multi agent scientific discovery"],
                "research_questions": ["How is evidence validated?"],
            },
            {
                "claims": [
                    {
                        "claim_id": "model-claim",
                        "source": "多智能体流程",
                        "relation": "requires",
                        "target": "可追溯证据",
                        "evidence_ids": ["live-1", "invented-id"],
                        "confidence": 0.84,
                        "limitations": ["仅基于摘要。"],
                    }
                ],
            },
            {
                "final_answer": [
                    {
                        "text": "实时证据表明，多智能体流程需要来源约束。",
                        "citations": ["live-1", "invented-id"],
                    }
                ],
                "reviews": [
                    {
                        "claim_id": "L001",
                        "verdict": "accepted",
                        "score": 0.81,
                        "criticisms": ["仍需全文复核。"],
                    }
                ],
                "briefing": {
                    "title": "实时导读",
                    "strategy": "先看证据。",
                    "sections": [
                        {
                            "heading": "核心结论",
                            "body": "摘要支持条件性结论。",
                            "citations": ["live-1", "invented-id"],
                        }
                    ],
                },
                "practical_guide": {
                    "title": "复现实操",
                    "estimated_minutes": 30,
                    "steps": [
                        {"step": 1, "title": "下载论文", "action": "复核全文。"}
                    ],
                },
                "quiz": {
                    "title": "理解检查",
                    "items": [
                        {
                            "level": "基础",
                            "question": "应保留什么？",
                            "options": ["来源", "配色"],
                            "answer": 0,
                        }
                    ],
                },
                "blue_ocean": {
                    "hypothesis": "证据约束可能改善结果。",
                    "caveat": "待验证，不是事实。",
                    "evidence_ids": ["live-1"],
                },
            },
        ]

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> tuple[dict[str, Any], LLMResponse]:
        payload = self.responses.pop(0)
        return (
            payload,
            LLMResponse(
                content="{}",
                provider="openai",
                model="gpt-test",
                duration_ms=5.0,
                usage={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
                request_id="req-test",
            ),
        )


class StubRetriever:
    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        return [
            Paper(
                paper_id="live-1",
                title="A Live Scholarly Source",
                authors=("Researcher",),
                year=2026,
                published="2026-01-01T00:00:00Z",
                categories=("cs.AI",),
                summary="The abstract supports evidence-grounded collaboration.",
                concepts=(),
                source_url="https://arxiv.org/abs/live-1",
            )
        ]


class EmptyRetriever:
    source_id = "empty"

    def search(self, queries: list[str], limit: int = 6) -> list[Paper]:
        return []


class LiveResearchTests(unittest.TestCase):
    def test_live_pipeline_filters_invented_citations_and_never_returns_key(self) -> None:
        config = ProviderConfig.from_payload(
            {
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "api_key": "never-return-this-key",
            }
        )
        kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        profile = LearnerProfile.from_dict(
            {
                "profile_id": "test",
                "name": "测试学习者",
                "persona": "测试",
                "education": "研究生",
                "role": "研究者",
                "goal": "理解证据约束",
                "interests": ["多智能体"],
                "knowledge_scores": {"证据检索": 60},
                "preferred_style": "结构化",
                "expected_difficulty": 3,
                "required_concepts": ["证据"],
            }
        )
        result = LiveResearchService(
            StubProvider(),
            config,
            kb,
            StubRetriever(),
        ).run(
            "多智能体如何降低科研幻觉？",
            profile,
            {"target_difficulty": 3, "blind_spots": ["证据检索"]},
        )
        self.assertEqual("multi_source_live", result["provider_run"]["source_mode"])
        self.assertEqual(["live-1"], result["claims"][0]["evidence_ids"])
        self.assertEqual(
            ["live-1"],
            result["answer_sections"][0]["citations"],
        )
        self.assertEqual(
            ["live-1"],
            result["resources"]["briefing"]["sections"][0]["citations"],
        )
        self.assertNotIn("never-return-this-key", str(result))
        self.assertFalse(result["provider_run"]["api_key_persisted"])
        self.assertEqual(45, result["provider_run"]["usage"]["total_tokens"])

    def test_zero_proposals_returns_structured_abstention(self) -> None:
        provider = StubProvider()
        provider.responses = [
            {
                "search_queries": ["ESP32 portable audio amplifier"],
                "research_questions": ["Which interfaces are supported?"],
            },
            {"claims": []},
        ]
        config = ProviderConfig.from_payload(
            {
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "api_key": "never-return-this-key",
            }
        )
        kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        profile = LearnerProfile.from_dict(
            {
                "profile_id": "test",
                "name": "测试学习者",
                "persona": "测试",
                "education": "本科",
                "role": "开发者",
                "goal": "制作原型",
                "interests": ["ESP32"],
                "knowledge_scores": {"证据检索": 60},
                "preferred_style": "分步",
                "expected_difficulty": 2,
                "required_concepts": ["I2S"],
            }
        )
        result = LiveResearchService(
            provider,
            config,
            kb,
            StubRetriever(),
        ).run(
            "如何基于 ESP32 开发便携式扩音器？",
            profile,
            {"target_difficulty": 2, "blind_spots": ["证据检索"]},
        )
        self.assertEqual("insufficient", result["provider_run"]["evidence_status"])
        self.assertEqual([], result["claims"])
        self.assertIn("证据不足", result["answer"])
        self.assertEqual(2, len(result["provider_run"]["calls"]))

    def test_irrelevant_local_slice_is_not_used_for_esp32_fallback(self) -> None:
        provider = StubProvider()
        provider.responses = [
            {
                "search_queries": ["ESP32 portable audio amplifier"],
                "research_questions": ["Which audio interfaces are supported?"],
            }
        ]
        config = ProviderConfig.from_payload(
            {
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "api_key": "never-return-this-key",
            }
        )
        kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        profile = LearnerProfile.from_dict(
            {
                "profile_id": "test",
                "name": "测试学习者",
                "persona": "测试",
                "education": "本科",
                "role": "开发者",
                "goal": "制作原型",
                "interests": ["ESP32"],
                "knowledge_scores": {"证据检索": 60},
                "preferred_style": "分步",
                "expected_difficulty": 2,
                "required_concepts": ["I2S"],
            }
        )
        result = LiveResearchService(
            provider,
            config,
            kb,
            EmptyRetriever(),
        ).run(
            "如何基于 ESP32 开发便携式扩音器？",
            profile,
            {"target_difficulty": 2, "blind_spots": ["证据检索"]},
        )
        self.assertEqual("no_relevant_sources", result["provider_run"]["source_mode"])
        self.assertEqual([], result["papers"])
        self.assertEqual(1, len(result["provider_run"]["calls"]))


if __name__ == "__main__":
    unittest.main()
