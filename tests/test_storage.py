from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.experiments import (  # noqa: E402
    EXPERIMENT_VARIANTS,
    EvidenceBoundaryEvaluator,
    ExperimentRunner,
)
from yanhai.models import Paper  # noqa: E402
from yanhai.orchestrator import ScholarlyTraceOrchestrator  # noqa: E402
from yanhai.providers import ProviderConfig  # noqa: E402
from yanhai.storage import AppRepository, DomainRouter  # noqa: E402


def profile_payload() -> dict:
    return {
        "name": "本地测试学习者",
        "persona": "希望通过实操理解证据",
        "education": "本科",
        "role": "学生",
        "goal": "掌握多智能体证据约束",
        "interests": ["多智能体", "知识图谱"],
        "knowledge_scores": {"多智能体": 45, "证据检索": 35},
        "preferred_style": "分步实操",
        "expected_difficulty": 3,
        "required_concepts": ["证据溯源", "幻觉"],
    }


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = AppRepository(
            Path(self.temporary.name) / "runtime" / "yanhai.sqlite3"
        )
        raw_papers = json.loads(
            (PROJECT_ROOT / "data" / "knowledge" / "papers.json").read_text(
                encoding="utf-8"
            )
        )
        raw_official = json.loads(
            (
                PROJECT_ROOT
                / "data"
                / "knowledge"
                / "official_sources.json"
            ).read_text(encoding="utf-8")
        )
        self.repository.bootstrap_catalog(
            [Paper.from_dict(item) for item in raw_papers],
            [Paper.from_dict(item) for item in raw_official],
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_account_profile_versions_and_sessions(self) -> None:
        user = self.repository.register_user(
            "learner@example.com",
            "本地学习者",
            "correct-horse-battery",
            profile_payload(),
        )
        self.assertEqual("本地学习者", user["nickname"])
        self.assertFalse(user["profile"]["synthetic"])
        logged_in = self.repository.verify_login(
            "LEARNER@example.com",
            "correct-horse-battery",
        )
        self.assertEqual(user["user_id"], logged_in["user_id"])
        nickname_login = self.repository.verify_login(
            "本地学习者",
            "correct-horse-battery",
        )
        self.assertEqual(user["user_id"], nickname_login["user_id"])
        with self.assertRaisesRegex(ValueError, "昵称已被使用"):
            self.repository.register_user(
                "another@example.com",
                "本地学习者",
                "another-strong-password",
            )

        token = self.repository.create_auth_session(user["user_id"])
        self.assertEqual(
            user["user_id"],
            self.repository.user_for_token(token)["user_id"],
        )
        updated_payload = profile_payload()
        updated_payload["goal"] = "掌握多智能体证据约束并完成复现实验"
        updated = self.repository.update_profile(user["user_id"], updated_payload)
        self.assertEqual(2, updated["profile_version"])
        self.assertIn("复现实验", updated["profile"]["goal"])

        self.repository.revoke_auth_session(token)
        self.assertIsNone(self.repository.user_for_token(token))

    def test_v1_database_backfills_unique_nickname(self) -> None:
        legacy_path = Path(self.temporary.name) / "legacy-v1.sqlite3"
        profile = profile_payload()
        profile["name"] = "旧版学习者"
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                );
                CREATE TABLE user_profiles (
                    profile_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(user_id, version)
                );
                """
            )
            connection.execute(
                """
                INSERT INTO users(
                    user_id, email, password_hash, password_salt, created_at
                ) VALUES ('usr_legacy', 'legacy@example.com', 'unused', 'unused', '2026-01-01')
                """
            )
            connection.execute(
                """
                INSERT INTO user_profiles(
                    profile_id, user_id, version, profile_json, created_at
                ) VALUES (?, 'usr_legacy', 1, ?, '2026-01-01')
                """,
                ("user:usr_legacy:v1", json.dumps(profile, ensure_ascii=False)),
            )
            connection.execute("PRAGMA user_version = 1")
            connection.commit()

        migrated = AppRepository(legacy_path)
        self.assertEqual("旧版学习者", migrated.get_user("usr_legacy")["nickname"])
        with closing(sqlite3.connect(legacy_path)) as connection:
            self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])
            indexes = {
                row[1]
                for row in connection.execute("PRAGMA index_list(users)").fetchall()
            }
        self.assertIn("users_nickname_unique", indexes)

    def test_domain_slices_bootstrap_and_local_search(self) -> None:
        domain, confidence, matched = DomainRouter.classify(
            "如何基于 ESP32 和 I2S 开发便携式扩音器？"
        )
        self.assertEqual("embedded_audio", domain.slug)
        self.assertGreater(confidence, 0)
        self.assertIn("esp32", [item.casefold() for item in matched])

        papers = self.repository.search_local_papers(
            "ESP32 I2S audio amplifier",
            limit=8,
        )
        self.assertGreaterEqual(len(papers), 3)
        self.assertTrue(
            any(
                paper.paper_id == "official:espressif:esp-idf-i2s"
                for paper in papers
            )
        )
        slices = {
            item["domain_slug"]: item
            for item in self.repository.list_slices()
        }
        self.assertGreaterEqual(slices["embedded_audio"]["paper_count"], 4)
        self.assertGreaterEqual(slices["ai_multi_agent"]["paper_count"], 8)

    def test_four_variant_experiment_uses_one_snapshot_and_accepts_survey(self) -> None:
        user = self.repository.register_user(
            "study@example.com",
            "实验学习者",
            "a-strong-test-password",
            profile_payload(),
        )
        profile = self.repository.learner_profile(user["user_id"])
        orchestrator = ScholarlyTraceOrchestrator(
            PROJECT_ROOT,
            repository=self.repository,
        )
        runner = ExperimentRunner(
            orchestrator,
            self.repository,
            variant_selector=lambda variants: variants[-1],
        )
        result = runner.run(
            user_id=user["user_id"],
            profile=profile,
            query="多智能体科研推理如何通过证据溯源降低幻觉？",
            provider_config=ProviderConfig("mock", "offline-rules", ""),
        )
        self.assertEqual("FULL", result["experiment"]["displayed_variant"])
        self.assertTrue(result["experiment"]["shared_evidence_snapshot"])
        self.assertEqual(len(EXPERIMENT_VARIANTS), result["experiment"]["variant_count"])

        counts = self.repository.study_statistics()["counts"]
        self.assertEqual(1, counts["research_sessions"])
        self.assertEqual(1, counts["evidence_snapshots"])
        self.assertEqual(4, counts["answer_variants"])
        self.assertEqual(4, counts["hallucination_evaluations"])

        saved = self.repository.submit_survey(
            user_id=user["user_id"],
            research_session_id=result["experiment"]["research_session_id"],
            answers={
                "satisfaction": 5,
                "personalization": 4,
                "perceived_learning": 4,
                "trust": 5,
                "citation_helpfulness": 5,
                "would_reuse": 4,
                "pre_quiz_score": 40,
                "post_quiz_score": 80,
                "comment": "证据结构很清楚。",
            },
        )
        self.assertTrue(saved["saved"])
        self.assertEqual(1, self.repository.study_statistics()["counts"]["survey_responses"])
        self.assertEqual(1, len(self.repository.user_history(user["user_id"])))

    def test_evaluator_does_not_treat_marked_hypothesis_as_factual_hallucination(
        self,
    ) -> None:
        metrics = EvidenceBoundaryEvaluator().evaluate(
            {
                "papers": [{"paper_id": "p1"}],
                "claims": [
                    {
                        "claim_id": "c1",
                        "status": "accepted",
                        "evidence_ids": ["p1"],
                    },
                    {
                        "claim_id": "c2",
                        "status": "accepted",
                        "evidence_ids": [],
                    },
                ],
                "resources": {
                    "blue_ocean": {"hypothesis": "待验证的新假设。"}
                },
            }
        )
        self.assertEqual(1, metrics["outside_evidence_inference_count"])
        self.assertEqual(1, metrics["marked_hypothesis_count"])
        self.assertEqual(0.5, metrics["hallucination_proxy_rate"])


if __name__ == "__main__":
    unittest.main()
