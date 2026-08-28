"""Unit tests for the minimal EASG kernel and the frozen R006 counterfactuals.

These tests lock the hand-computed gold states in config/实验/easg_r006_cases.json
against the deterministic policy in src/yanhai/easg.py. Replay determinism is
asserted as a code property; the formal replay ×3 run (R007) is a separate
tracked experiment and is not claimed here.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.easg import (  # noqa: E402
    Claim,
    DecisionEvent,
    EASGStore,
    StaticProvenanceStore,
    load_case,
    load_events,
)

CASES_PATH = PROJECT_ROOT / "config" / "实验" / "easg_r006_cases.json"
CONFIG_HASH = "r006-toy-v1"


def make_event(**overrides):
    payload = {
        "event_id": "x1",
        "claim_id": "R1",
        "event_type": "add_support",
        "actor": "proposer",
        "seq": 1,
        "config_hash": CONFIG_HASH,
    }
    payload.update(overrides)
    return DecisionEvent.from_dict(payload)


class DecisionEventSchemaTests(unittest.TestCase):
    def test_unknown_event_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_event(event_type="vote_accept")

    def test_human_override_requires_status(self) -> None:
        with self.assertRaises(ValueError):
            make_event(event_type="human_override", actor="human", override_status=None)

    def test_seq_must_be_strictly_increasing(self) -> None:
        store = EASGStore({"R1": Claim("R1")})
        store.append(make_event(seq=1))
        with self.assertRaises(ValueError):
            store.append(make_event(event_id="x2", seq=1))

    def test_event_roundtrip(self) -> None:
        event = make_event(evidence_id="eA", source="paperA")
        self.assertEqual(event, DecisionEvent.from_dict(event.to_dict()))


class R006FrozenCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = load_case(CASES_PATH)
        cls.cases = cls.payload["cases"]

    def _claims(self, case: dict) -> dict[str, Claim]:
        claims = {
            item["claim_id"]: Claim(
                claim_id=item["claim_id"],
                semantic_strength=item.get("semantic_strength", "plain"),
                condition=item.get("condition"),
            )
            for item in self.payload.get("claims", [])
        }
        override = case.get("claim_override") or {}
        if override:
            focus = case["focus_claim"]
            claims[focus] = Claim(
                claim_id=focus,
                semantic_strength=override.get("semantic_strength", "plain"),
                condition=override.get("condition"),
            )
        return claims

    def _run(self, case: dict) -> tuple[dict, dict]:
        claims = self._claims(case)
        initial = load_events({"events": case["initial_events"]})
        target = DecisionEvent.from_dict(case["target_event"])

        easg = EASGStore(claims, initial)
        easg.append(target)
        easg_projection = easg.projection(case["focus_claim"])

        static = StaticProvenanceStore(claims, initial)
        static.apply(target)
        static_projection = static.projection(case["focus_claim"])
        return easg_projection, static_projection

    def test_every_case_matches_hand_computed_gold(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                easg_projection, static_projection = self._run(case)
                easg_gold = case["gold"]["easg"]
                static_gold = case["gold"]["static"]
                self.assertEqual(
                    easg_gold["admission_status"],
                    easg_projection["admission_status"],
                )
                if "superseded_by" in easg_gold:
                    self.assertEqual(
                        easg_gold["superseded_by"], easg_projection["superseded_by"]
                    )
                self.assertEqual(
                    static_gold["admission_status"],
                    static_projection["admission_status"],
                )

    def test_static_failures_count_matches_design(self) -> None:
        static_failures = 0
        for case in self.cases:
            _, static_projection = self._run(case)
            correct_status = case["gold"]["easg"]["admission_status"]
            if static_projection["admission_status"] != correct_status:
                static_failures += 1
        # 9 designed static failures, 3 fair controls.
        self.assertEqual(9, static_failures)

    def test_static_baseline_has_no_audit_history(self) -> None:
        case = self.cases[0]
        _, static_projection = self._run(case)
        self.assertEqual([], static_projection["reasons"])


class ReplayPropertyTests(unittest.TestCase):
    def test_projection_is_pure_function_of_event_stream(self) -> None:
        payload = load_case(CASES_PATH)
        case = payload["cases"][0]
        claims = {
            item["claim_id"]: Claim(
                claim_id=item["claim_id"],
                semantic_strength=item.get("semantic_strength", "plain"),
                condition=item.get("condition"),
            )
            for item in payload.get("claims", [])
        }
        events = load_events({"events": case["initial_events"]})
        store = EASGStore(claims, events)
        store.append(DecisionEvent.from_dict(case["target_event"]))
        first, second, third = store.replay(case["focus_claim"])
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_case_file_is_valid_json_with_expected_counts(self) -> None:
        payload = load_case(CASES_PATH)
        self.assertEqual(12, len(payload["cases"]))
        event_types = {case["event_type"] for case in payload["cases"]}
        self.assertEqual(
            {"delete_evidence", "add_refute", "replace_span", "add_superseding", "add_support"},
            event_types,
        )


if __name__ == "__main__":
    unittest.main()
