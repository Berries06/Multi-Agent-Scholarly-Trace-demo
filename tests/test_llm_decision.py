from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.agents import CriticAgent  # noqa: E402
from yanhai.knowledge import KnowledgeBase  # noqa: E402
from yanhai.llm_decision import LLMCritic, LLMJudge, hard_guard  # noqa: E402
from yanhai.models import Claim  # noqa: E402
from yanhai.providers import ProviderError  # noqa: E402
from yanhai.semantic_check import check_semantic_strength  # noqa: E402


class _FailingProvider:
    """Duck-typed provider that always raises, to exercise the fallback path."""

    def complete_json(self, *args: object, **kwargs: object) -> object:
        raise ProviderError("模拟网络失败，用于测试降级路径。")


class HardGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        evidence = cls.kb.extracted_paper_graph()["evidence"]
        cls.valid_evidence_id = evidence[0]["evidence_id"] if evidence else ""

    def _claim(self, relation: str, evidence_ids: list[str]) -> Claim:
        return Claim(
            claim_id="T-001",
            source="multi-agent debate",
            relation=relation,
            target="hallucination control",
            relation_type="IMPROVES",
            base_confidence=0.9,
            evidence_ids=evidence_ids,
        )

    def test_no_valid_evidence_is_forced_rejected(self) -> None:
        claim = self._claim("improves", ["evidence:does-not-exist"])
        hard_guard(claim, self.kb)
        self.assertEqual("rejected", claim.status)
        self.assertIn("护栏", claim.judge_reason)

    def test_absolute_predicate_is_forced_rejected_even_with_evidence(self) -> None:
        claim = self._claim("guarantees", [self.valid_evidence_id])
        hard_guard(claim, self.kb)
        self.assertEqual("rejected", claim.status)
        self.assertIn("绝对化", claim.judge_reason)


class LLMFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kb = KnowledgeBase(PROJECT_ROOT / "data" / "knowledge")
        evidence = cls.kb.extracted_paper_graph()["evidence"]
        cls.valid_evidence_id = evidence[0]["evidence_id"] if evidence else ""

    def test_critic_falls_back_to_rules_when_provider_fails(self) -> None:
        claim = Claim(
            claim_id="T-002",
            source="multi-agent debate",
            relation="improves",
            target="hallucination control",
            relation_type="IMPROVES",
            base_confidence=0.85,
            evidence_ids=[self.valid_evidence_id],
        )
        critic = LLMCritic(_FailingProvider(), fallback_to_rules=True)
        critic.critique([claim], self.kb)
        self.assertTrue(claim.criticisms)
        self.assertEqual(1, critic.stats.failed_calls)

    def test_judge_falls_back_but_hard_guard_still_blocks(self) -> None:
        claim = Claim(
            claim_id="T-003",
            source="X",
            relation="proves",
            target="Y",
            relation_type="IMPROVES",
            base_confidence=0.95,
            evidence_ids=[],
        )
        judge = LLMJudge(_FailingProvider(), fallback_to_rules=True)
        judge.adjudicate([claim], self.kb)
        self.assertEqual("rejected", claim.status)
        self.assertIn("护栏", claim.judge_reason)

    def test_progressive_relation_gets_unfinished_criticism(self) -> None:
        claim = Claim(
            claim_id="T-004",
            source="A",
            relation="attempting to improve",
            target="B",
            relation_type="IMPROVES",
            base_confidence=0.85,
            evidence_ids=[self.valid_evidence_id],
        )
        CriticAgent().critique([claim], self.kb)
        self.assertTrue(
            any("未完成体悖论" in item for item in claim.criticisms)
        )


class SemanticStrengthTests(unittest.TestCase):
    def test_absolute_claim_is_danger(self) -> None:
        result = check_semantic_strength("我们证明了该方法零幻觉")
        self.assertEqual("danger", result["verdict"])
        self.assertTrue(result["absolute_markers"])

    def test_progressive_claim_is_warning(self) -> None:
        result = check_semantic_strength("作者正在尝试改进该模型")
        self.assertEqual("warning", result["verdict"])
        self.assertTrue(result["progressive_markers"])

    def test_plain_sentence_is_plain(self) -> None:
        result = check_semantic_strength("该方法在 SciERC 上评测")
        self.assertEqual("plain", result["verdict"])


if __name__ == "__main__":
    unittest.main()
