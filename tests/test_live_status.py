"""Offline checks for displaying recorded live research results."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402


class LiveStatusTests(unittest.TestCase):
    def trace_for(self, calls: list[dict]) -> list[dict]:
        return ScholarlyTraceOrchestrator._live_trace(
            [], {"calls": calls, "source_mode": "multi_source_live"}, 1, 1
        )

    def test_current_resource_call_is_shown_as_completed(self) -> None:
        trace = self.trace_for([
            {"role": "批判裁决与资源生成", "duration_ms": 12.5}
        ])
        self.assertEqual("completed", trace[-1]["status"])
        self.assertEqual(12.5, trace[-1]["duration_ms"])
        self.assertEqual(3, trace[-1]["output_count"])

    def test_legacy_resource_call_is_still_supported(self) -> None:
        trace = self.trace_for([
            {"role": "个性化教学与反馈", "duration_ms": 9.5}
        ])
        self.assertEqual("completed", trace[-1]["status"])
        self.assertEqual(9.5, trace[-1]["duration_ms"])

    def test_current_call_takes_precedence_over_legacy_alias(self) -> None:
        trace = self.trace_for([
            {"role": "个性化教学与反馈", "duration_ms": 9.5},
            {"role": "批判裁决与资源生成", "duration_ms": 12.5},
        ])
        self.assertEqual(12.5, trace[-1]["duration_ms"])

    def test_missing_resource_call_remains_abstained(self) -> None:
        trace = self.trace_for([
            {"role": "证据提出", "duration_ms": 4.0}
        ])
        self.assertEqual("abstained", trace[-1]["status"])
        self.assertEqual(0.0, trace[-1]["duration_ms"])
        self.assertEqual(0, trace[-1]["output_count"])

    def test_review_count_includes_both_existing_status_names(self) -> None:
        claims = [
            {"status": status, "evidence_ids": ["paper-1"], "evidence_spans": ["span-1"]}
            for status in ("accepted", "review", "needs_review", "rejected", "abstained")
        ]
        metrics = ScholarlyTraceOrchestrator._live_metrics({"claims": claims, "metrics": {}})
        self.assertEqual(2, metrics["review_claims"])
        self.assertEqual(1, metrics["accepted_claims"])
        self.assertEqual(1, metrics["rejected_claims"])
        self.assertEqual(1, metrics["abstained_claims"])
        self.assertEqual("needs_review", claims[2]["status"])


if __name__ == "__main__":
    unittest.main()
