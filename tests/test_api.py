from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.api import create_app  # noqa: E402
from yanhai.storage import AppRepository  # noqa: E402


class UnifiedApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = AppRepository(Path(self.temp.name) / "product.db")
        self.repository.register_user(
            "member@example.com",
            "测试成员",
            "correct-password",
        )
        self.client = TestClient(create_app(root=PROJECT_ROOT, repository=self.repository))

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def login(self) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"identifier": "测试成员", "password": "correct-password"},
        )
        self.assertEqual(200, response.status_code)

    def test_product_has_login_gate_and_no_public_registration(self) -> None:
        self.assertEqual(200, self.client.get("/api/health").status_code)
        denied = self.client.get("/api/domains")
        self.assertEqual(401, denied.status_code)
        self.assertEqual("login_required", denied.json()["error"]["code"])
        # Static-file fallback may answer an unknown POST with 405 instead of 404.
        # The product contract is that no public registration operation exists.
        self.assertIn(
            self.client.post("/api/auth/register", json={}).status_code,
            {404, 405},
        )
        self.assertNotIn(
            "/api/auth/register",
            self.client.get("/openapi.json").json()["paths"],
        )

    def test_personal_and_demo_profiles_coexist(self) -> None:
        self.login()
        profiles = self.client.get("/api/profiles").json()
        self.assertEqual("personal", profiles[0]["profile_kind"])
        self.assertEqual("my-profile", profiles[0]["profile_id"])
        self.assertTrue(any(item["profile_kind"] == "demo" for item in profiles[1:]))

    def test_offline_run_is_owned_and_saved(self) -> None:
        self.login()
        response = self.client.post(
            "/api/run",
            json={
                "profile_id": "my-profile",
                "query": "知识图谱如何支持科研训练？",
                "llm": {"provider": "mock", "model": "offline-rules"},
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertTrue(result["persistence"]["saved"])
        history = self.client.get("/api/history").json()
        self.assertEqual(1, len(history))

    def test_offline_stream_emits_ordered_progress_and_completion(self) -> None:
        self.login()
        response = self.client.post(
            "/api/run/stream",
            json={
                "profile_id": "my-profile",
                "query": "知识图谱如何支持科研训练？",
                "include_ablation": False,
                "llm": {"provider": "mock", "model": "offline-rules"},
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        blocks = [block for block in response.text.split("\n\n") if block.strip()]
        progress = []
        for block in blocks:
            if not block.startswith("event: progress"):
                continue
            raw = next(line[6:].strip() for line in block.splitlines() if line.startswith("data:"))
            progress.append(json.loads(raw)["progress"])

        self.assertGreaterEqual(len(progress), 10)
        self.assertEqual(list(range(1, len(progress) + 1)), [item["sequence"] for item in progress])
        self.assertEqual("persistence", progress[-1]["phase"])
        self.assertEqual(100, progress[-1]["percent"])
        self.assertIn("event: completed", response.text)

    def test_ingestion_does_not_save_source_without_consent(self) -> None:
        self.login()
        response = self.client.post(
            "/api/ingest-paper",
            json={
                "paper_id": "privacy-check",
                "title": "隐私检查",
                "text": "方法部分。系统从论文证据中抽取实体关系，并由裁判复核证据跨度。" * 4,
                "profile_id": "my-profile",
                "save_source": False,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertFalse(response.json()["persistence"]["source_saved"])
        ingestions = self.client.get("/api/ingestions").json()
        self.assertFalse(ingestions[0]["source_saved"])


if __name__ == "__main__":
    unittest.main()
