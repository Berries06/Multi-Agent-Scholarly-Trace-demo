"""Provider API checks use fake credentials and a local transport only."""

from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.providers import ProviderError  # noqa: E402
from yanhai.extraction import ScientificDocument  # noqa: E402
from yanhai.storage import AppRepository  # noqa: E402


class ProviderAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "YANHAI_DEEPSEEK_KEY_FILE": str(root / "absent-key.txt"),
            "YANHAI_DATABASE_PATH": str(root / "runtime.db"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        from yanhai import api

        self.api = api
        self.global_key_patch = patch.object(api, "SERVER_API_KEY", "test-only-legacy-global-key")
        self.global_key_patch.start()
        self.addCleanup(self.global_key_patch.stop)
        repository = AppRepository(root / "test.db")
        repository.register_user("member@example.com", "测试成员", "correct-password")
        self.app = api.create_app(root=PROJECT_ROOT, repository=repository)
        self.fake_key = "test-only-hosted-key-not-a-real-credential"
        self.app.state.yanhai.deepseek_key = self.fake_key
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.transport_patch = patch("yanhai.providers._default_transport", side_effect=self.transport)
        self.transport_mock = self.transport_patch.start()
        self.addCleanup(self.transport_patch.stop)
        self.requests: list[dict] = []

    def transport(self, url, headers, payload, timeout):
        self.requests.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
        return ({
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
        }, {})

    def login(self) -> None:
        response = self.client.post("/api/auth/login", json={
            "identifier": "测试成员", "password": "correct-password",
        })
        self.assertEqual(200, response.status_code, response.text)

    def test_anonymous_requests_never_call_a_provider(self) -> None:
        for payload in ({"provider": "free-deepseek"}, {"provider": "mock"}, {
            "provider": "deepseek", "api_key": "test-only-personal-key",
        }):
            with self.subTest(provider=payload["provider"]):
                response = self.client.post("/api/provider/test", json=payload)
                self.assertEqual(401, response.status_code, response.text)
                self.assertEqual("login_required", response.json()["error"]["code"])
        self.transport_mock.assert_not_called()

    def test_invalid_session_never_calls_a_provider(self) -> None:
        self.client.cookies.set("yanhai_session", "not-a-session")
        response = self.client.post("/api/provider/test", json={"provider": "free-deepseek"})
        self.assertEqual(401, response.status_code, response.text)
        self.transport_mock.assert_not_called()

    def test_logged_in_offline_test_needs_no_provider(self) -> None:
        self.login()
        response = self.client.post("/api/provider/test", json={"provider": "mock"})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("mock", response.json()["provider"])
        self.transport_mock.assert_not_called()

    def test_hosted_test_uses_app_key_and_does_not_return_it(self) -> None:
        self.login()
        with patch.object(self.api, "SERVER_API_KEY", "different-test-only-global-key"):
            response = self.client.post("/api/provider/test", json={"provider": "free-deepseek"})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(f"Bearer {self.fake_key}", self.requests[0]["headers"]["Authorization"])
        self.assertNotIn(self.fake_key, response.text)
        self.assertNotIn("api_key", response.text)

    def test_unconfigured_app_cannot_fall_back_to_global_key(self) -> None:
        self.login()
        self.app.state.yanhai.deepseek_key = ""
        with patch.object(self.api, "SERVER_API_KEY", "different-test-only-global-key"):
            response = self.client.post("/api/provider/test", json={"provider": "free-deepseek"})
        self.assertEqual(503, response.status_code, response.text)
        self.transport_mock.assert_not_called()

    def test_hosted_model_must_match_existing_free_option(self) -> None:
        self.login()
        response = self.client.post("/api/provider/test", json={
            "provider": "free-deepseek", "model": "deepseek-v4-pro",
        })
        self.assertEqual(400, response.status_code, response.text)
        self.transport_mock.assert_not_called()

    def test_repeated_tests_keep_fixed_endpoint_prompt_and_token_bound(self) -> None:
        self.login()
        for _ in range(3):
            response = self.client.post("/api/provider/test", json={
                "provider": "free-deepseek", "api_key": "ignored-personal-key",
                "endpoint": "https://invalid.example/collect", "base_url": "https://invalid.example",
                "max_tokens": 999999, "prompt": "untrusted request text", "timeout_seconds": 5,
            })
            self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(3, len(self.requests))
        for request in self.requests:
            self.assertEqual("https://api.deepseek.com/chat/completions", request["url"])
            self.assertEqual("deepseek-v4-flash", request["payload"]["model"])
            self.assertEqual(16, request["payload"]["max_tokens"])
            self.assertEqual("只回复 OK。", request["payload"]["messages"][-1]["content"])
            self.assertEqual(5, request["timeout"])
            self.assertEqual(f"Bearer {self.fake_key}", request["headers"]["Authorization"])

    def test_personal_key_does_not_use_hosted_key(self) -> None:
        self.login()
        response = self.client.post("/api/provider/test", json={
            "provider": "deepseek", "model": "deepseek-v4-pro", "api_key": "test-only-personal-key",
        })
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("Bearer test-only-personal-key", self.requests[0]["headers"]["Authorization"])
        self.assertEqual("deepseek-v4-pro", self.requests[0]["payload"]["model"])
        self.assertNotIn("test-only-personal-key", response.text)

    def test_provider_error_does_not_return_hosted_key(self) -> None:
        self.login()
        self.transport_mock.side_effect = ProviderError(f"upstream rejected {self.fake_key}")
        response = self.client.post("/api/provider/test", json={"provider": "free-deepseek"})
        self.assertEqual(502, response.status_code, response.text)
        self.assertNotIn(self.fake_key, response.text)

    def test_logout_prevents_later_provider_requests(self) -> None:
        self.login()
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/provider/test", json={"provider": "free-deepseek"})
        self.assertEqual(401, response.status_code, response.text)
        self.transport_mock.assert_not_called()

    def test_provider_list_uses_app_configuration_without_exposing_key(self) -> None:
        with patch.object(self.api, "SERVER_API_KEY", ""):
            response = self.client.get("/api/providers")
        self.assertTrue(response.json()["free_deepseek_ready"])
        self.assertNotIn(self.fake_key, response.text)

    def ingest(self, kind: str, llm: dict):
        if kind == "text":
            return self.client.post("/api/ingest-paper", json={
                "paper_id": "configuration-check", "title": "配置检查", "llm": llm,
                "text": "方法部分。系统从论文证据中抽取实体关系，并由裁判复核证据跨度。" * 4,
            })
        return self.client.post("/api/ingest-pdf", data={"llm": json.dumps(llm)}, files={
            "file": ("fixture.pdf", b"local-parser-fixture", "application/pdf"),
        })

    def test_offline_text_ingestion_runs_real_pipeline_and_saves_result(self) -> None:
        self.login()
        for config in ({}, {"provider": "mock"}):
            with self.subTest(config=config):
                response = self.ingest("text", config)
                self.assertEqual(200, response.status_code, response.text)
                result = response.json()
                self.assertTrue(result["persistence"]["saved"])
                self.assertFalse(result["persistence"]["source_saved"])
                self.assertEqual("configuration-check", result["document"]["paper_id"])
                self.assertIsNone(result["decision_layer"]["provider"])
        self.assertEqual(2, len(self.client.get("/api/ingestions").json()))
        self.transport_mock.assert_not_called()

    def test_both_ingestion_routes_pass_the_application_key_and_keep_mock_offline(self) -> None:
        self.login()
        document = ScientificDocument("fixture-paper", "Fixture", {"abstract": "Local fixture text."})
        for kind, pipeline_name in (("text", "run_fresh_paper_pipeline"), ("pdf", "run_fresh_document_pipeline")):
            for selected in ("free-deepseek", "mock"):
                with self.subTest(kind=kind, selected=selected), patch.object(
                    self.api, pipeline_name, return_value={}
                ) as pipeline, patch.object(self.api.PyPDFParser, "parse_bytes", return_value=document):
                    response = self.ingest(kind, {"provider": selected})
                    self.assertEqual(200, response.status_code, response.text)
                    config = pipeline.call_args.kwargs["provider_config"]
                    if selected == "mock":
                        self.assertIsNone(config)
                    else:
                        self.assertEqual(self.fake_key, config.api_key)
                        self.assertEqual("deepseek", config.provider)
                        self.assertEqual("deepseek-v4-flash", config.model)
                    self.assertNotIn(self.fake_key, response.text)
        self.transport_mock.assert_not_called()

    def test_both_ingestion_routes_reject_nonfree_model_before_running(self) -> None:
        self.login()
        with patch.object(self.api, "run_fresh_paper_pipeline") as text_pipeline, patch.object(
            self.api, "run_fresh_document_pipeline"
        ) as pdf_pipeline, patch.object(self.api.PyPDFParser, "parse_bytes") as parser:
            for kind in ("text", "pdf"):
                with self.subTest(kind=kind):
                    response = self.ingest(kind, {"provider": "free-deepseek", "model": "deepseek-v4-pro"})
                    self.assertEqual(400, response.status_code, response.text)
            text_pipeline.assert_not_called()
            pdf_pipeline.assert_not_called()
            parser.assert_not_called()
        self.transport_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
